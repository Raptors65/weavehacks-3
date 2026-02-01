"""GitHub webhook handlers for PR feedback loop."""

import asyncio
import hashlib
import hmac
import logging
import os
import re

from redis.asyncio import Redis

from agent import run_feedback_fix_agent, clone_repo, commit_and_push, cleanup_repo
from config import get_repo_for_product
from github import GitHubClient
from learning.rules import create_rule
from learning.rule_extractor import extract_rules_from_feedback
from tasks import get_task

logger = logging.getLogger(__name__)

# Maximum number of fix iterations per PR (to avoid infinite loops)
MAX_FIX_ITERATIONS = 3


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
    """Extract Darwin task ID from PR title or body.
    
    PR titles look like: "[Darwin] Fix issue title"
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
    
    # Fallback: check branch name (darwin/fix-{task_id})
    branch = pr_data.get("head", {}).get("ref", "")
    branch_match = re.search(r"darwin/fix-([a-f0-9]+)", branch)
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
        logger.debug("PR %s is not a Darwin PR (no task ID found)", pr_number)
        return {"status": "ignored", "reason": "not a darwin PR"}
    
    logger.info("Darwin PR detected: task_id=%s", task_id)
    
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
        return {"status": "ignored", "reason": "not a darwin PR"}
    
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
            
            # Extract and store rules from feedback
            if review_body and len(review_body.strip()) >= 10:
                await _extract_and_store_rules(
                    feedback=review_body,
                    task_id=task_id,
                    reviewer=reviewer,
                    redis_client=redis_client,
                )
            
            # Trigger automatic fix for the feedback
            await _trigger_feedback_fix(
                task_id=task_id,
                pr_data=pr_data,
                redis_client=redis_client,
            )
    
    return {"status": "success", "task_id": task_id, "review_state": review_state}


async def _extract_and_store_rules(
    feedback: str,
    task_id: str,
    reviewer: str,
    redis_client: Redis,
) -> int:
    """Extract rules from feedback and store them.
    
    Args:
        feedback: The review feedback text.
        task_id: The task ID for context.
        reviewer: The reviewer username.
        redis_client: Redis client.
        
    Returns:
        Number of rules created.
    """
    try:
        # Get task to find product
        task = await get_task(redis_client, task_id)
        if not task:
            logger.warning("Task %s not found for rule extraction", task_id)
            return 0
        
        product = task.get("product")
        if not product:
            logger.warning("Task %s has no product for rule extraction", task_id)
            return 0
        
        # Extract rules using LLM
        rules = await extract_rules_from_feedback(feedback, task)
        
        if not rules:
            logger.debug("No rules extracted from feedback for task %s", task_id)
            return 0
        
        # Store each rule
        created_count = 0
        for rule in rules:
            await create_rule(
                redis_client=redis_client,
                product=product,
                content=rule["content"],
                category=rule["category"],
                source="review_feedback",
                source_task_id=task_id,
                reviewer=reviewer,
            )
            created_count += 1
        
        logger.info("Created %d rules from review feedback for product %s", 
                   created_count, product)
        return created_count
        
    except Exception as e:
        logger.error("Failed to extract/store rules: %s", e)
        return 0


async def _trigger_feedback_fix(
    task_id: str,
    pr_data: dict,
    redis_client: Redis,
) -> bool:
    """Trigger the fix agent to address PR review feedback.
    
    This function:
    1. Checks if we haven't exceeded max iterations
    2. Fetches all comments from the PR
    3. Clones the repo and checks out the PR branch
    4. Runs the feedback fix agent
    5. Commits and pushes the changes
    
    Args:
        task_id: The Darwin task ID.
        pr_data: The pull request object from the webhook.
        redis_client: Redis client.
        
    Returns:
        True if fix was triggered and succeeded, False otherwise.
    """
    import asyncio
    
    task_key = f"task:{task_id}"
    
    # Check fix iteration count
    iteration_count = await redis_client.hget(task_key, "fix_iterations")
    iteration_count = int(iteration_count) if iteration_count else 0
    
    if iteration_count >= MAX_FIX_ITERATIONS:
        logger.warning(
            "Task %s has reached max fix iterations (%d), skipping auto-fix",
            task_id, MAX_FIX_ITERATIONS
        )
        return False
    
    # Check if a fix is already in progress
    fix_status = await redis_client.hget(task_key, "fix_status")
    if fix_status and fix_status.decode() if isinstance(fix_status, bytes) else fix_status == "running":
        logger.warning("Fix already in progress for task %s, skipping", task_id)
        return False
    
    # Get task data
    task = await get_task(redis_client, task_id)
    if not task:
        logger.error("Task %s not found", task_id)
        return False
    
    product = task.get("product")
    if not product:
        logger.warning("Task %s has no product, cannot fix", task_id)
        return False
    
    repo = get_repo_for_product(product)
    if not repo:
        logger.warning("No repo mapping for product %s", product)
        return False
    
    # Get PR details
    pr_number = pr_data.get("number")
    pr_branch = pr_data.get("head", {}).get("ref", "")
    
    if not pr_branch:
        logger.error("Could not get PR branch for task %s", task_id)
        return False
    
    logger.info(
        "Triggering feedback fix for task %s (PR #%d, branch: %s, iteration: %d)",
        task_id, pr_number, pr_branch, iteration_count + 1
    )
    
    # Update status to running
    await redis_client.hset(task_key, mapping={
        "fix_status": "running",
        "fix_iterations": iteration_count + 1,
    })
    
    try:
        # Initialize GitHub client and fetch comments
        github_client = GitHubClient()
        
        reviews = await github_client.get_pr_reviews(repo, pr_number)
        inline_comments = await github_client.get_pr_comments(repo, pr_number)
        
        # Convert to dicts for the agent
        reviews_data = [
            {"body": r.body, "user": r.user, "state": r.state}
            for r in reviews
            if r.body  # Only include reviews with comments
        ]
        inline_data = [
            {"body": c.body, "path": c.path, "line": c.line, "user": c.user}
            for c in inline_comments
        ]
        
        if not reviews_data and not inline_data:
            logger.info("No review comments to address for task %s", task_id)
            await redis_client.hset(task_key, "fix_status", "completed")
            return False
        
        logger.info(
            "Found %d reviews and %d inline comments for task %s",
            len(reviews_data), len(inline_data), task_id
        )
        
        # Clone the repo and checkout the PR branch (run in thread pool to avoid blocking)
        clone_result = await asyncio.to_thread(clone_repo, repo, branch=pr_branch, task_id=f"{task_id}-feedback")
        
        if not clone_result.success:
            logger.error("Failed to clone repo: %s", clone_result.error)
            await redis_client.hset(task_key, "fix_status", "failed")
            return False
        
        repo_path = clone_result.path
        
        try:
            # Run the feedback fix agent
            fix_result = await run_feedback_fix_agent(
                repo_path=repo_path,
                task=task,
                reviews=reviews_data,
                inline_comments=inline_data,
            )
            
            if not fix_result.success:
                logger.warning(
                    "Feedback fix agent failed for task %s: %s",
                    task_id, fix_result.error or fix_result.message
                )
                await redis_client.hset(task_key, "fix_status", "failed")
                return False
            
            # Commit and push the changes (run in thread pool to avoid blocking)
            commit_message = f"fix: address review feedback (iteration {iteration_count + 1})\n\nAutomated fix by Darwin for task {task_id}"
            
            push_success = await asyncio.to_thread(commit_and_push, repo_path, commit_message, pr_branch)
            if not push_success:
                logger.error("Failed to push feedback fixes for task %s", task_id)
                await redis_client.hset(task_key, "fix_status", "failed")
                return False
            
            logger.info(
                "Successfully pushed feedback fixes for task %s (files: %s)",
                task_id, fix_result.files_changed
            )
            
            await redis_client.hset(task_key, "fix_status", "completed")
            return True
            
        finally:
            # Clean up the cloned repo (run in thread pool to avoid blocking)
            await asyncio.to_thread(cleanup_repo, repo_path)
            
    except Exception as e:
        logger.exception("Failed to trigger feedback fix for task %s: %s", task_id, e)
        await redis_client.hset(task_key, "fix_status", "failed")
        return False


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
        task_id: The Darwin task ID.
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

