"""Background worker for classifying topics."""

import asyncio
import logging
import os

import redis.asyncio as redis

from agent import run_fix_agent, clone_repo, create_branch, commit_and_push, create_pr
from classify import TopicClassifier
from config import get_repo_for_product
from github import GitHubClient, format_issue_body, format_issue_title, get_labels_for_task
from ingest.cluster import get_topic, TOPIC_PREFIX
from learning import (
    get_top_rules_for_product,
    format_rules_for_prompt,
    increment_rule_usage,
    get_similar_successful_fixes,
    format_similar_fixes,
)
from llm import get_llm
from tasks.storage import (
    create_task,
    get_task,
    pop_classify_queue,
    get_classify_queue_length,
    update_task_github_issue,
    update_task_fix,
)

logger = logging.getLogger(__name__)

# Worker configuration
POLL_INTERVAL = float(os.getenv("CLASSIFY_WORKER_POLL_INTERVAL", "2.0"))
BATCH_SIZE = int(os.getenv("CLASSIFY_WORKER_BATCH_SIZE", "5"))


class ClassifyWorker:
    """Background worker that classifies topics into actionable tasks.

    This worker:
    1. Pops topic IDs from queue:to-classify
    2. Fetches the topic data from Redis
    3. Uses LLM to classify the topic
    4. Creates a task if the topic is actionable
    5. Updates the topic with its category
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        classifier: TopicClassifier | None = None,
    ):
        """Initialize the classify worker.

        Args:
            redis_client: Redis client instance.
            classifier: TopicClassifier to use. Creates one if not provided.
        """
        self.redis = redis_client

        if classifier:
            self.classifier = classifier
        else:
            llm = get_llm(os.getenv("LLM_PROVIDER", "openai"))
            self.classifier = TopicClassifier(llm)

        # Initialize GitHub client if token is available
        self._github_client: GitHubClient | None = None
        if os.getenv("GITHUB_TOKEN"):
            try:
                self._github_client = GitHubClient()
                logger.info("GitHub integration enabled")
            except ValueError as e:
                logger.warning("GitHub integration disabled: %s", e)

        self._running = False
        self._task: asyncio.Task | None = None

    async def process_one(self) -> bool:
        """Process a single topic from the queue.

        Returns:
            True if a topic was processed, False if queue was empty.
        """
        # Pop from queue
        topic_id = await pop_classify_queue(self.redis)
        if not topic_id:
            return False

        logger.debug("Classifying topic: %s", topic_id)

        # Get topic data
        topic_data = await get_topic(self.redis, topic_id)
        if not topic_data:
            logger.warning("Topic not found in Redis: %s", topic_id)
            return True

        title = topic_data.get("title", "")
        if not title:
            logger.warning("Topic has no title: %s", topic_id)
            return True

        # Get product for propagation to task
        product = topic_data.get("product") or None

        # Get signals for this topic (for now, just use the title)
        # TODO: Fetch actual signals linked to this topic
        signals = [title]

        # Classify the topic
        try:
            result = await self.classifier.classify(title, signals)
        except Exception as e:
            logger.error("Failed to classify topic %s: %s", topic_id, e)
            return True

        # Update topic with category
        topic_key = f"{TOPIC_PREFIX}{topic_id}"
        await self.redis.hset(topic_key, "category", result.category)

        # Create task if actionable
        if result.is_actionable:
            task_id = await create_task(self.redis, topic_id, result, product)
            logger.info(
                "Created task %s for topic %s (category: %s, severity: %s)",
                task_id,
                topic_id,
                result.category,
                result.severity,
            )

            # Create GitHub issue if configured
            await self._create_github_issue(task_id, topic_id, product)
            
            # DEMO ONLY: Auto-trigger fix for tasks containing "Workflowy"
            # In production, we would always auto-trigger fixes for all tasks.
            # For demo purposes, we only do this for "Workflowy" because:
            # 1. We only have time to show 1 PR during the demo
            # 2. We don't want to burn through all Claude credits
            if "workflowy" in result.title.lower():
                logger.info(
                    "DEMO: Auto-triggering fix for Workflowy task %s",
                    task_id,
                )
                await self._auto_trigger_fix(task_id, product)
        else:
            logger.info(
                "Topic %s classified as %s (not actionable)",
                topic_id,
                result.category,
            )

        return True

    async def _create_github_issue(
        self,
        task_id: str,
        topic_id: str,
        product: str | None,
    ) -> None:
        """Create a GitHub issue for a task if configured.

        Args:
            task_id: The task ID.
            topic_id: The topic ID.
            product: The product name.
        """
        if not self._github_client:
            logger.debug("GitHub integration not configured, skipping issue creation")
            return

        if not product:
            logger.debug("No product specified for task %s, skipping issue creation", task_id)
            return

        # Look up repo for product
        repo = get_repo_for_product(product)
        if not repo:
            logger.warning(
                "No repo mapping found for product '%s', skipping issue creation",
                product,
            )
            return

        # Get task data for formatting
        task_data = await get_task(self.redis, task_id)
        if not task_data:
            logger.error("Task not found: %s", task_id)
            return

        try:
            # Format issue
            title = format_issue_title(task_data)
            body = format_issue_body(task_data, topic_id)
            labels = get_labels_for_task(task_data)

            # Create issue
            issue = await self._github_client.create_issue(repo, title, body, labels)

            # Update task with issue info
            await update_task_github_issue(
                self.redis, task_id, issue.html_url, issue.number
            )

            logger.info(
                "Created GitHub issue #%d for task %s: %s",
                issue.number,
                task_id,
                issue.html_url,
            )
        except Exception as e:
            logger.error("Failed to create GitHub issue for task %s: %s", task_id, e)

    async def _auto_trigger_fix(
        self,
        task_id: str,
        product: str | None,
    ) -> None:
        """Auto-trigger the fix agent for a task.

        DEMO ONLY: In production, we'd always auto-trigger fixes.
        This is only called for tasks containing "Workflowy" to:
        1. Only show 1 PR during the demo (limited time)
        2. Avoid burning through Claude credits

        Args:
            task_id: The task ID.
            product: The product name.
        """
        if not product:
            logger.debug("No product specified for task %s, skipping auto-fix", task_id)
            return

        repo = get_repo_for_product(product)
        if not repo:
            logger.warning(
                "No repo mapping found for product '%s', skipping auto-fix",
                product,
            )
            return

        task_data = await get_task(self.redis, task_id)
        if not task_data:
            logger.error("Task not found for auto-fix: %s", task_id)
            return

        try:
            # Update status to running
            await update_task_fix(self.redis, task_id, "running")

            # Clone repository (run in thread pool to avoid blocking)
            logger.info("Auto-fix: Cloning repo %s for task %s", repo, task_id)
            clone_result = await asyncio.to_thread(clone_repo, repo, task_id=task_id)

            if not clone_result.success:
                await update_task_fix(self.redis, task_id, "failed")
                logger.error("Auto-fix: Failed to clone repository: %s", clone_result.error)
                return

            repo_path = clone_result.path
            branch_name = f"darwin/fix-{task_id}"

            # Create fix branch (run in thread pool to avoid blocking)
            branch_created = await asyncio.to_thread(create_branch, repo_path, branch_name)
            if not branch_created:
                await update_task_fix(self.redis, task_id, "failed")
                logger.error("Auto-fix: Failed to create branch")
                return

            # Get similar successful fixes for self-improvement
            similar_fixes = await get_similar_successful_fixes(task_data, self.redis)
            similar_fixes_text = format_similar_fixes(similar_fixes)
            if similar_fixes:
                logger.info("Auto-fix: Found %d similar successful fixes", len(similar_fixes))

            # Get style rules learned from past reviews
            style_rules = []
            style_rules_text = ""
            if product:
                style_rules = await get_top_rules_for_product(self.redis, product, limit=10)
                style_rules_text = format_rules_for_prompt(style_rules)
                if style_rules:
                    logger.info("Auto-fix: Found %d style rules for product %s", len(style_rules), product)
                    for rule in style_rules:
                        await increment_rule_usage(self.redis, product, rule.get("id", ""))

            # Run the fix agent
            logger.info("Auto-fix: Running fix agent for task %s", task_id)
            fix_result = await run_fix_agent(
                repo_path,
                task_data,
                similar_fixes_text,
                style_rules_text,
            )

            if not fix_result.success:
                await update_task_fix(self.redis, task_id, "failed")
                logger.error("Auto-fix: Fix agent failed: %s", fix_result.error or fix_result.message)
                return

            # Commit and push (run in thread pool to avoid blocking)
            title = task_data.get("title", "Fix issue")
            commit_message = f"fix: {title}\n\nAutomated fix by Darwin for task {task_id}"

            push_success = await asyncio.to_thread(commit_and_push, repo_path, commit_message, branch_name)
            if not push_success:
                await update_task_fix(self.redis, task_id, "failed")
                logger.error("Auto-fix: Failed to push changes")
                return

            # Create PR
            pr_title = f"[Darwin] {title}"

            # Build issue reference if available
            issue_number = task_data.get('github_issue_number')
            issue_url = task_data.get('github_issue_url')
            if issue_number:
                issue_ref = f"Fixes #{issue_number}"
                issue_link = f"- **Related Issue**: [{issue_ref}]({issue_url})"
            else:
                issue_ref = ""
                issue_link = ""

            pr_body = f"""## Automated Fix

This pull request was automatically generated by Darwin.
{f'{chr(10)}{issue_ref}' if issue_ref else ''}

### Task Details
- **Category**: {task_data.get('category', 'N/A')}
- **Summary**: {task_data.get('summary', 'N/A')}
- **Suggested Action**: {task_data.get('suggested_action', 'N/A')}
{issue_link}

### Files Changed
{chr(10).join(f'- `{f}`' for f in fix_result.files_changed)}

---
*Created by [Darwin](https://github.com/Raptors65/darwin) | Task ID: {task_id}*
"""

            pr_data = await create_pr(repo, branch_name, pr_title, pr_body, base=clone_result.default_branch)

            if pr_data:
                await update_task_fix(
                    self.redis, task_id, "completed",
                    fix_pr_url=pr_data["html_url"],
                    fix_branch=branch_name,
                )
                logger.info(
                    "Auto-fix: Created PR for task %s: %s",
                    task_id,
                    pr_data["html_url"],
                )
            else:
                await update_task_fix(
                    self.redis, task_id, "completed",
                    fix_branch=branch_name,
                )
                logger.warning("Auto-fix: Changes pushed but PR creation failed for task %s", task_id)

        except Exception as e:
            await update_task_fix(self.redis, task_id, "failed")
            logger.exception("Auto-fix: Failed for task %s: %s", task_id, e)

    async def process_batch(self, batch_size: int = BATCH_SIZE) -> int:
        """Process a batch of topics.

        Args:
            batch_size: Maximum topics to process in this batch.

        Returns:
            Number of topics processed.
        """
        processed = 0
        for _ in range(batch_size):
            if await self.process_one():
                processed += 1
            else:
                break
        return processed

    async def run(self) -> None:
        """Run the worker loop."""
        self._running = True
        logger.info("Classify worker started")

        while self._running:
            try:
                queue_len = await get_classify_queue_length(self.redis)
                if queue_len > 0:
                    logger.debug("Classification queue length: %d", queue_len)
                    processed = await self.process_batch()
                    if processed > 0:
                        logger.info("Classified %d topics", processed)
                else:
                    await asyncio.sleep(POLL_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error in classify worker: %s", e)
                await asyncio.sleep(POLL_INTERVAL)

        logger.info("Classify worker stopped")

    def start(self) -> asyncio.Task:
        """Start the worker as a background task.

        Returns:
            The asyncio Task running the worker.
        """
        self._task = asyncio.create_task(self.run())
        return self._task

    async def stop(self) -> None:
        """Stop the worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

