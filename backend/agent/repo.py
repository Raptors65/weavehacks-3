"""Repository utilities for cloning, branching, and creating PRs."""

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com"


@dataclass
class CloneResult:
    """Result of cloning a repository."""

    path: Path
    success: bool
    error: str | None = None


def clone_repo(
    repo: str,
    branch: str = "main",
    task_id: str | None = None,
) -> CloneResult:
    """Clone a GitHub repository to a temporary directory.

    Args:
        repo: Repository in "owner/repo" format.
        branch: Branch to clone.
        task_id: Optional task ID for directory naming.

    Returns:
        CloneResult with the path to the cloned repo.
    """
    # Create temp directory
    if task_id:
        temp_dir = Path(tempfile.gettempdir()) / f"beacon-{task_id}"
    else:
        temp_dir = Path(tempfile.mkdtemp(prefix="beacon-"))

    # Clean up if exists
    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    temp_dir.mkdir(parents=True, exist_ok=True)

    # Get GitHub token for private repos
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        clone_url = f"https://x-access-token:{github_token}@github.com/{repo}.git"
    else:
        clone_url = f"https://github.com/{repo}.git"

    logger.info("Cloning %s to %s", repo, temp_dir)

    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", branch, clone_url, str(temp_dir)],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            logger.error("Clone failed: %s", result.stderr)
            return CloneResult(path=temp_dir, success=False, error=result.stderr)

        logger.info("Clone successful")
        return CloneResult(path=temp_dir, success=True)

    except subprocess.TimeoutExpired:
        logger.error("Clone timed out")
        return CloneResult(path=temp_dir, success=False, error="Clone timed out")
    except Exception as e:
        logger.error("Clone failed: %s", e)
        return CloneResult(path=temp_dir, success=False, error=str(e))


def create_branch(repo_path: Path, branch_name: str) -> bool:
    """Create and checkout a new branch.

    Args:
        repo_path: Path to the repository.
        branch_name: Name of the branch to create.

    Returns:
        True if successful, False otherwise.
    """
    logger.info("Creating branch: %s", branch_name)

    try:
        # Create and checkout branch
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error("Create branch failed: %s", result.stderr)
            return False

        return True

    except Exception as e:
        logger.error("Create branch failed: %s", e)
        return False


def commit_and_push(
    repo_path: Path,
    message: str,
    branch_name: str,
) -> bool:
    """Commit all changes and push to remote.

    Args:
        repo_path: Path to the repository.
        message: Commit message.
        branch_name: Branch to push to.

    Returns:
        True if successful, False otherwise.
    """
    logger.info("Committing and pushing changes")

    try:
        # Configure git user
        subprocess.run(
            ["git", "config", "user.email", "beacon@example.com"],
            cwd=repo_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Beacon Bot"],
            cwd=repo_path,
            capture_output=True,
        )

        # Stage all changes
        result = subprocess.run(
            ["git", "add", "-A"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("Git add failed: %s", result.stderr)
            return False

        # Check if there are changes to commit
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if not status.stdout.strip():
            logger.warning("No changes to commit")
            return False

        # Commit
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("Git commit failed: %s", result.stderr)
            return False

        # Push
        result = subprocess.run(
            ["git", "push", "-u", "origin", branch_name],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.error("Git push failed: %s", result.stderr)
            return False

        logger.info("Push successful")
        return True

    except subprocess.TimeoutExpired:
        logger.error("Push timed out")
        return False
    except Exception as e:
        logger.error("Commit and push failed: %s", e)
        return False


async def create_pr(
    repo: str,
    branch: str,
    title: str,
    body: str,
    base: str = "main",
) -> dict | None:
    """Create a pull request on GitHub.

    Args:
        repo: Repository in "owner/repo" format.
        branch: Head branch with changes.
        title: PR title.
        body: PR description.
        base: Base branch to merge into.

    Returns:
        PR data dict with 'html_url' and 'number', or None on failure.
    """
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        logger.error("GITHUB_TOKEN not set")
        return None

    url = f"{GITHUB_API_URL}/repos/{repo}/pulls"

    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    payload = {
        "title": title,
        "body": body,
        "head": branch,
        "base": base,
    }

    logger.info("Creating PR: %s", title)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=headers,
                json=payload,
                timeout=30.0,
            )

            if response.status_code == 201:
                data = response.json()
                logger.info("PR created: %s", data["html_url"])
                return {
                    "html_url": data["html_url"],
                    "number": data["number"],
                    "url": data["url"],
                }
            else:
                logger.error("PR creation failed: %s %s", response.status_code, response.text)
                return None

    except Exception as e:
        logger.error("PR creation failed: %s", e)
        return None


def cleanup_repo(repo_path: Path) -> None:
    """Remove the temporary repository directory.

    Args:
        repo_path: Path to the repository to clean up.
    """
    if repo_path.exists():
        logger.info("Cleaning up: %s", repo_path)
        shutil.rmtree(repo_path, ignore_errors=True)

