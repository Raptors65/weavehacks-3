"""Format task data into GitHub issue content."""

# Category to emoji mapping
CATEGORY_EMOJI = {
    "BUG": "🐛",
    "FEATURE": "✨",
    "UX": "🎨",
    "OTHER": "📝",
}

# Category to labels mapping
CATEGORY_LABELS = {
    "BUG": ["bug"],
    "FEATURE": ["enhancement"],
    "UX": ["ux", "enhancement"],
    "OTHER": [],
}

# Severity to labels mapping (for bugs)
SEVERITY_LABELS = {
    "critical": ["priority: critical"],
    "major": ["priority: high"],
    "minor": [],
}


def format_issue_title(task: dict) -> str:
    """Format the GitHub issue title from a task.

    Args:
        task: Task data dictionary.

    Returns:
        Formatted issue title.
    """
    # Use the LLM-generated title if available, otherwise fall back to summary
    title = task.get("title") or task.get("summary", "")
    # Truncate to 100 chars for GitHub title limit
    if len(title) > 100:
        return title[:97] + "..."
    return title


def format_issue_body(task: dict, topic_id: str | None = None) -> str:
    """Format the GitHub issue body from a task.

    Args:
        task: Task data dictionary.
        topic_id: Optional topic ID for reference.

    Returns:
        Markdown-formatted issue body.
    """
    category = task.get("category", "OTHER")
    emoji = CATEGORY_EMOJI.get(category, "📝")
    severity = task.get("severity", "")
    summary = task.get("summary", "No summary available")
    suggested_action = task.get("suggested_action", "")
    confidence = task.get("confidence", 0)
    signal_count = task.get("signal_count", 1)

    # Build category line
    category_line = f"{emoji} **{category}**"
    if severity:
        category_line += f" (Severity: {severity.title()})"

    # Build the body
    parts = [
        "## Summary",
        summary,
        "",
        "## Category",
        category_line,
    ]

    if suggested_action:
        parts.extend([
            "",
            "## Suggested Action",
            suggested_action,
        ])

    # Add metadata footer
    confidence_pct = int(confidence * 100) if isinstance(confidence, float) else confidence
    footer_parts = [
        f"Confidence: {confidence_pct}%",
        f"Signals: {signal_count}",
    ]
    if topic_id:
        footer_parts.append(f"Topic: `{topic_id}`")

    parts.extend([
        "",
        "---",
        f"*Created by [Beacon](https://github.com/beacon) | {' | '.join(footer_parts)}*",
    ])

    return "\n".join(parts)


def get_labels_for_task(task: dict) -> list[str]:
    """Get the appropriate labels for a task.

    Args:
        task: Task data dictionary.

    Returns:
        List of label names to apply.
    """
    labels = []

    # Add category labels
    category = task.get("category", "OTHER")
    labels.extend(CATEGORY_LABELS.get(category, []))

    # Add severity labels for bugs
    if category == "BUG":
        severity = task.get("severity", "")
        if severity:
            labels.extend(SEVERITY_LABELS.get(severity, []))

    return labels

