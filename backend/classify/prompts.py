"""Classification prompts for topic categorization."""

CLASSIFICATION_PROMPT = """You are analyzing user feedback about a software product.

Classify the following topic (a cluster of similar user feedback) into one of these categories:

- **BUG**: A bug report, error, crash, or something not working as expected
- **FEATURE**: A feature request or suggestion for new functionality  
- **UX**: UI/UX confusion, usability issue, or design improvement request
- **OTHER**: Not actionable - general discussion, praise, off-topic, or unclear

## Topic Title
{title}

## Sample Signals (user posts in this topic)
{signals}

## Instructions
1. Analyze the topic and its signals
2. Determine the most appropriate category
3. Write a short title (like a GitHub issue title, max 60 chars)
4. Write a concise 1-2 sentence summary
5. If BUG: assign severity (critical = data loss/crash, major = broken feature, minor = cosmetic)
6. Suggest what action a developer should take

Respond with your classification."""

CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": ["BUG", "FEATURE", "UX", "OTHER"],
            "description": "The classification category",
        },
        "title": {
            "type": "string",
            "description": "A short GitHub-issue-style title, max 60 characters",
        },
        "summary": {
            "type": "string",
            "description": "A concise 1-2 sentence summary of the issue/request",
        },
        "severity": {
            "type": ["string", "null"],
            "enum": ["critical", "major", "minor", None],
            "description": "Severity level for bugs, null for other categories",
        },
        "suggested_action": {
            "type": "string",
            "description": "What a developer should do to address this",
        },
        "confidence": {
            "type": "number",
            "description": "Confidence score from 0 to 1",
        },
    },
    "required": ["category", "title", "summary", "severity", "suggested_action", "confidence"],
    "additionalProperties": False,
}

