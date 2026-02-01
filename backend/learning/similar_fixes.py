"""Retrieve similar successful fixes for self-improvement."""

import json
import logging

from redis.asyncio import Redis
from redis.commands.search.query import Query

from embedders import get_embedder
from ingest.cluster import embedding_to_bytes
from redis_setup import SUCCESSFUL_FIXES_INDEX

logger = logging.getLogger(__name__)


async def get_similar_successful_fixes(
    task: dict,
    redis_client: Redis,
    limit: int = 3,
    min_score: float = 0.5,
) -> list[dict]:
    """Find similar past fixes that were successfully merged.
    
    This is the core of the self-improvement loop. We embed the current
    task and find similar successful fixes to use as examples.
    
    Args:
        task: The current task dict with category, title, summary.
        redis_client: Redis client.
        limit: Maximum number of similar fixes to return.
        min_score: Minimum similarity score (0-1, higher is more similar).
        
    Returns:
        List of similar fix dicts with title, summary, files_changed.
    """
    try:
        # Check if any successful fixes exist
        keys = await redis_client.keys("fix:success:*")
        if not keys:
            logger.debug("No successful fixes stored yet")
            return []
        
        # Embed the current task
        embedder = get_embedder()
        text = f"{task.get('category', '')}: {task.get('title', '')}. {task.get('summary', '')}"
        query_embedding = embedder.embed(text)
        
        # Convert to bytes for search
        query_bytes = embedding_to_bytes(query_embedding)
        
        # KNN search
        query = Query(
            f"*=>[KNN {limit} @embedding $vec AS score]"
        ).return_fields(
            "title", "summary", "category", "product", "files_changed", "pr_url", "score"
        ).sort_by("score").dialect(2)
        
        results = await redis_client.ft(SUCCESSFUL_FIXES_INDEX).search(
            query, {"vec": query_bytes}
        )
        
        similar_fixes = []
        for doc in results.docs:
            # Score is cosine distance, convert to similarity (1 - distance)
            score = 1 - float(doc.score) if hasattr(doc, "score") else 0
            
            if score >= min_score:
                # Parse files_changed if it's JSON
                files_changed = doc.files_changed if hasattr(doc, "files_changed") else "[]"
                try:
                    files_list = json.loads(files_changed)
                except (json.JSONDecodeError, TypeError):
                    files_list = []
                
                similar_fixes.append({
                    "title": doc.title if hasattr(doc, "title") else "",
                    "summary": doc.summary if hasattr(doc, "summary") else "",
                    "category": doc.category if hasattr(doc, "category") else "",
                    "product": doc.product if hasattr(doc, "product") else "",
                    "files_changed": files_list,
                    "pr_url": doc.pr_url if hasattr(doc, "pr_url") else "",
                    "similarity": score,
                })
        
        logger.info("Found %d similar successful fixes for task", len(similar_fixes))
        return similar_fixes
        
    except Exception as e:
        logger.warning("Failed to get similar fixes: %s", e)
        return []


def format_similar_fixes(fixes: list[dict]) -> str:
    """Format similar fixes for inclusion in the agent prompt.
    
    Args:
        fixes: List of similar fix dicts.
        
    Returns:
        Formatted string for the prompt.
    """
    if not fixes:
        return "No similar past fixes found yet. You're pioneering new territory!"
    
    sections = []
    for i, fix in enumerate(fixes, 1):
        files_str = ", ".join(fix.get("files_changed", [])[:5]) or "N/A"
        if len(fix.get("files_changed", [])) > 5:
            files_str += f" (+{len(fix['files_changed']) - 5} more)"
        
        section = f"""### Similar Fix #{i} (Successfully Merged)
- **Category**: {fix.get('category', 'N/A')}
- **Title**: {fix.get('title', 'N/A')}
- **Summary**: {fix.get('summary', 'N/A')[:200]}{"..." if len(fix.get('summary', '')) > 200 else ""}
- **Files Changed**: {files_str}
- **Similarity**: {fix.get('similarity', 0):.0%}"""
        
        if fix.get("pr_url"):
            section += f"\n- **PR**: {fix['pr_url']}"
        
        sections.append(section)
    
    return "\n\n".join(sections)

