"""Coding fix agent using Claude Agent SDK."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import weave
from claude_agent_sdk import query, ClaudeAgentOptions

logger = logging.getLogger(__name__)

# Track whether Weave has been initialized
_weave_initialized = False


def init_weave() -> bool:
    """Initialize Weave if WANDB_API_KEY is set.
    
    Uses WEAVE_PROJECT env var for project name (default: beacon-agent).
    Format should be "team/project" or just "project" (uses default team).
    
    Returns:
        True if Weave was initialized, False otherwise.
    """
    global _weave_initialized
    if _weave_initialized:
        return True
    
    if os.getenv("WANDB_API_KEY"):
        project_name = os.getenv("WEAVE_PROJECT", "beacon-agent")
        try:
            weave.init(project_name)
            _weave_initialized = True
            logger.info("Weave initialized for project: %s", project_name)
            return True
        except Exception as e:
            logger.warning("Failed to initialize Weave: %s", e)
            return False
    else:
        logger.debug("WANDB_API_KEY not set, Weave tracing disabled")
        return False


@weave.op()
def log_tool_call(tool_name: str, tool_input: dict) -> dict:
    """Log a tool call as a Weave child span.
    
    This creates a nested span in the Weave trace for each tool the agent uses.
    
    Args:
        tool_name: Name of the tool (Read, Edit, Glob, Grep, Bash, etc.)
        tool_input: Input parameters passed to the tool.
        
    Returns:
        A dict summarizing the tool call for the trace.
    """
    # Create a concise summary based on tool type
    summary = ""
    if tool_name == "Read":
        summary = tool_input.get("file_path", "unknown file")
    elif tool_name == "Edit":
        summary = tool_input.get("file_path", "unknown file")
    elif tool_name == "Glob":
        summary = tool_input.get("pattern", "unknown pattern")
    elif tool_name == "Grep":
        summary = tool_input.get("pattern", "unknown pattern")
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")
        summary = cmd[:100] + "..." if len(cmd) > 100 else cmd
    else:
        summary = str(tool_input)[:100]
    
    logger.info("[Agent] %s: %s", tool_name, summary)
    
    return {
        "tool": tool_name,
        "summary": summary,
        "input": tool_input,
    }

# Prompt template for the fix agent
FIX_AGENT_PROMPT = """You are a skilled software engineer fixing a bug or implementing a feature.

## Task Information
- **Category**: {category}
- **Title**: {title}
- **Summary**: {summary}
- **Suggested Action**: {suggested_action}

## Instructions

1. **Explore**: First, understand the codebase structure. Use Glob and Grep to find relevant files.
2. **Analyze**: Read the relevant files to understand the current implementation.
3. **Plan**: Think about the minimal changes needed to fix the issue.
4. **Fix**: Make the necessary code changes using Edit. Keep changes focused and minimal.
5. **Verify**: Review your changes to ensure they address the issue.

## Guidelines

- Make minimal, targeted changes
- Follow the existing code style and conventions
- Add comments if the fix is non-obvious
- Do NOT run tests or commit - just make the file changes
- If you're unsure about something, err on the side of making a smaller change

Begin by exploring the codebase to find the relevant code for this issue.
"""


@dataclass
class FixResult:
    """Result of running the fix agent."""

    success: bool
    message: str
    files_changed: list[str]
    error: str | None = None


@weave.op()
async def run_fix_agent(
    repo_path: Path,
    task: dict,
) -> FixResult:
    """Run the Claude Agent to fix an issue in a repository.

    Args:
        repo_path: Path to the cloned repository.
        task: Task data dictionary with category, title, summary, suggested_action.

    Returns:
        FixResult with the outcome.
    """
    category = task.get("category", "UNKNOWN")
    title = task.get("title", "")
    summary = task.get("summary", "")
    suggested_action = task.get("suggested_action", "")

    prompt = FIX_AGENT_PROMPT.format(
        category=category,
        title=title,
        summary=summary,
        suggested_action=suggested_action,
    )

    logger.info("Running fix agent for task: %s", title[:50])
    logger.info("Working directory: %s", repo_path)

    files_changed: list[str] = []
    last_result = ""

    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(repo_path),
                allowed_tools=["Read", "Edit", "Glob", "Grep", "Bash"],
                permission_mode="acceptEdits",  # Auto-accept file edits
            ),
        ):
            # Log the message class for debugging
            msg_class = type(message).__name__
            logger.debug("Agent message: %s", msg_class)

            # Handle AssistantMessage with ToolUseBlock in content
            # Structure: AssistantMessage(content=[ToolUseBlock(name='Read', input={...})])
            if hasattr(message, "content") and isinstance(message.content, list):
                for block in message.content:
                    # Check if this is a ToolUseBlock
                    block_type = type(block).__name__
                    if block_type == "ToolUseBlock":
                        tool_name = getattr(block, "name", None)
                        tool_input = getattr(block, "input", {}) or {}
                        
                        if tool_name:
                            # Create a Weave child span for this tool call
                            log_tool_call(tool_name, tool_input)
                            
                            # Track file changes from Edit tool
                            if tool_name == "Edit":
                                file_path = tool_input.get("file_path", "")
                                if file_path:
                                    # Convert to relative path if it starts with repo_path
                                    try:
                                        rel_path = str(Path(file_path).relative_to(repo_path))
                                    except ValueError:
                                        # Already relative or different base
                                        rel_path = file_path
                                    
                                    if rel_path not in files_changed:
                                        files_changed.append(rel_path)
                                        logger.info("File changed: %s", rel_path)

            # Capture final result from ResultMessage
            if hasattr(message, "result"):
                last_result = message.result

        logger.info("Fix agent completed. Files changed: %d", len(files_changed))

        if files_changed:
            return FixResult(
                success=True,
                message=last_result or f"Fixed {len(files_changed)} file(s)",
                files_changed=files_changed,
            )
        else:
            return FixResult(
                success=False,
                message="Agent completed but no files were changed",
                files_changed=[],
            )

    except Exception as e:
        logger.exception("Fix agent failed: %s", e)
        return FixResult(
            success=False,
            message="Agent failed",
            files_changed=files_changed,
            error=str(e),
        )

