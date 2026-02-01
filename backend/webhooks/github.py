"""GitHub webhook handlers for PR feedback loop."""

import hashlib
import hmac
import logging
import os
import re

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


def verify_signature(payload: bytes, signature: str | None) -> bool:
    """Verify GitHub webhook signature.
    
    Args:
        payload: Raw request body bytes.
        signature: X-Hub-Signature-256 header value.
        
    Returns:
        True if signature is valid, False otherwise.
    """
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    
    if not secret:
        logger.warning("GITHUB_WEBHOOK_SECRET not set - skipping verification")
        return True  # Allow in development
    
    if not signature:
        logger.warning("No signature provided in webhook request")
        return False
    
    expected = "sha256=" + hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected, signature)


def extract_task_id_from_pr(pr_data: dict) -> str | None:
    """Extract Beacon task ID from PR title or body.
    
    PR titles look like: "[Beacon] Fix issue title"
    PR body contains: "Task ID: abc123"
    
    Args:
        pr_data: GitHub PR object from webhook payload.
        
    Returns:
        Task ID if found, None otherwise.
    """
    body = pr_data.get("body", "") or ""
    
    # Look for "Task ID: xyz" pattern in body
    match = re.search(r"Task ID:\s*([a-f0-9]+)", body, re.IGNORECASE)
    if match:
        return match.group(1)
    
    # Fallback: check branch name (beacon/fix-{task_id})
    branch = pr_data.get("head", {}).get("ref", "")
    branch_match = re.search(r"beacon/fix-([a-f0-9]+)", branch)
    if branch_match:
        return branch_match.group(1)
    
    return None


async def handle_pr_event(
    action: str,
    pr_data: dict,
    redis_client: Redis,
) -> dict:
    """Handle pull_request webhook event.
    
    Args:
        action: The action that triggered the event (opened, closed, merged, etc.)
        pr_data: The pull request object from the webhook payload.
        redis_client: Redis client for storage.
        
    Returns:
        Dict with processing result.
    """
    pr_number = pr_data.get("number")
    pr_url = pr_data.get("html_url")
    merged = pr_data.get("merged", False)
    state = pr_data.get("state")  # open, closed
    
    logger.info("PR event: action=%s, number=%s, state=%s, merged=%s", 
                action, pr_number, state, merged)
    
    # Extract task ID from PR
    task_id = extract_task_id_from_pr(pr_data)
    if not task_id:
        logger.debug("PR %s is not a Beacon PR (no task ID found)", pr_number)
        return {"status": "ignored", "reason": "not a beacon PR"}
    
    logger.info("Beacon PR detected: task_id=%s", task_id)
    
    # Check if task exists
    task_key = f"task:{task_id}"
    exists = await redis_client.exists(task_key)
    if not exists:
        logger.warning("Task %s not found in Redis", task_id)
        return {"status": "ignored", "reason": "task not found"}
    
    if action == "closed":
        if merged:
            # PR was merged - SUCCESS!
            logger.info("PR %s was MERGED! Storing successful fix for task %s", pr_number, task_id)
            await store_successful_fix(task_id, pr_data, redis_client)
            
            # Update task status
            await redis_client.hset(task_key, mapping={
                "fix_pr_status": "merged",
                "fix_outcome": "success",
            })
            
            return {"status": "success", "task_id": task_id, "outcome": "merged"}
        else:
            # PR was closed without merging - rejected
            logger.info("PR %s was CLOSED without merge for task %s", pr_number, task_id)
            
            await redis_client.hset(task_key, mapping={
                "fix_pr_status": "closed",
                "fix_outcome": "rejected",
            })
            
            return {"status": "success", "task_id": task_id, "outcome": "rejected"}
    
    elif action == "reopened":
        # PR was reopened
        await redis_client.hset(task_key, mapping={
            "fix_pr_status": "open",
            "fix_outcome": "pending",
        })
        return {"status": "success", "task_id": task_id, "outcome": "reopened"}
    
    return {"status": "ignored", "reason": f"unhandled action: {action}"}


async def handle_review_event(
    action: str,
    review_data: dict,
    pr_data: dict,
    redis_client: Redis,
) -> dict:
    """Handle pull_request_review webhook event.
    
    Args:
        action: The action (submitted, edited, dismissed).
        review_data: The review object.
        pr_data: The pull request object.
        redis_client: Redis client.
        
    Returns:
        Dict with processing result.
    """
    review_state = review_data.get("state")  # approved, changes_requested, commented
    reviewer = review_data.get("user", {}).get("login", "unknown")
    review_body = review_data.get("body", "")
    
    logger.info("PR review: action=%s, state=%s, reviewer=%s", 
                action, review_state, reviewer)
    
    task_id = extract_task_id_from_pr(pr_data)
    if not task_id:
        return {"status": "ignored", "reason": "not a beacon PR"}
    
    task_key = f"task:{task_id}"
    exists = await redis_client.exists(task_key)
    if not exists:
        return {"status": "ignored", "reason": "task not found"}
    
    if action == "submitted":
        if review_state == "approved":
            logger.info("PR approved by %s for task %s", reviewer, task_id)
            # Could store approval as positive signal
            
        elif review_state == "changes_requested":
            logger.info("Changes requested by %s for task %s: %s", 
                       reviewer, task_id, review_body[:200])
            # Store feedback for learning (future enhancement)
            # This could be used to improve prompts
    
    return {"status": "success", "task_id": task_id, "review_state": review_state}


async def store_successful_fix(
    task_id: str,
    pr_data: dict,
    redis_client: Redis,
) -> None:
    """Store a successful fix for future learning.
    
    This is the core of the self-improvement loop. When a PR is merged,
    we store the fix details so they can be used as examples for similar
    future tasks.
    
    Args:
        task_id: The Beacon task ID.
        pr_data: The merged PR data from GitHub.
        redis_client: Redis client.
    """
    import json
    import time
    
    # Get the original task data
    task_key = f"task:{task_id}"
    task_data = await redis_client.hgetall(task_key)
    
    if not task_data:
        logger.warning("Cannot store successful fix: task %s not found", task_id)
        return
    
    # Decode bytes to strings
    task = {k.decode() if isinstance(k, bytes) else k: 
            v.decode() if isinstance(v, bytes) else v 
            for k, v in task_data.items()}
    
    # Create successful fix record
    fix_record = {
        "task_id": task_id,
        "category": task.get("category", ""),
        "title": task.get("title", ""),
        "summary": task.get("summary", ""),
        "suggested_action": task.get("suggested_action", ""),
        "product": task.get("product", ""),
        "pr_url": pr_data.get("html_url", ""),
        "pr_title": pr_data.get("title", ""),
        "merged_at": pr_data.get("merged_at", ""),
        "stored_at": int(time.time()),
        # Files changed could be parsed from PR diff, but we have it in task
        "files_changed": task.get("files_changed", "[]"),
    }
    
    # Store the successful fix
    fix_key = f"fix:success:{task_id}"
    await redis_client.hset(fix_key, mapping=fix_record)
    
    logger.info("Stored successful fix: %s (category=%s, product=%s)", 
                task_id, fix_record["category"], fix_record["product"])
    
    # Create embedding for similarity search
    try:
        from embedders import get_embedder
        from ingest.cluster import embedding_to_bytes, embedding_to_base64
        
        embedder = get_embedder()
        text = f"{fix_record['category']}: {fix_record['title']}. {fix_record['summary']}"
        embedding = await embedder.embed(text)
        
        # Store embedding in both formats:
        # - embedding: raw bytes for RediSearch vector index
        # - embedding_b64: base64 for Python retrieval (with decode_responses=True)
        await redis_client.hset(
            fix_key,
            mapping={
                "embedding": embedding_to_bytes(embedding),
                "embedding_b64": embedding_to_base64(embedding),
            }
        )
        
        logger.info("Stored embedding for successful fix %s", task_id)
        
    except Exception as e:
        logger.warning("Failed to create embedding for fix %s: %s", task_id, e)

