"""Topic classifier using LLM."""

import logging
from dataclasses import dataclass
from typing import Literal

from classify.prompts import CLASSIFICATION_PROMPT, CLASSIFICATION_SCHEMA
from llm.base import BaseLLM

logger = logging.getLogger(__name__)

Category = Literal["BUG", "FEATURE", "UX", "OTHER"]
Severity = Literal["critical", "major", "minor"] | None


@dataclass
class ClassificationResult:
    """Result of classifying a topic."""

    category: Category
    summary: str
    severity: Severity
    suggested_action: str
    confidence: float

    @property
    def is_actionable(self) -> bool:
        """Return True if this classification is actionable."""
        return self.category in ("BUG", "FEATURE", "UX")


class TopicClassifier:
    """Classifies topics into categories using an LLM."""

    def __init__(self, llm: BaseLLM):
        """Initialize the classifier.

        Args:
            llm: The LLM provider to use for classification.
        """
        self.llm = llm

    async def classify(
        self,
        title: str,
        signals: list[str],
    ) -> ClassificationResult:
        """Classify a topic based on its title and signals.

        Args:
            title: The topic title.
            signals: List of signal texts in this topic.

        Returns:
            ClassificationResult with the category and details.
        """
        # Format signals for the prompt
        signals_text = "\n".join(
            f"- {signal[:500]}..." if len(signal) > 500 else f"- {signal}"
            for signal in signals[:10]  # Limit to 10 signals
        )

        prompt = CLASSIFICATION_PROMPT.format(
            title=title,
            signals=signals_text,
        )

        logger.debug("Classifying topic: %s", title[:50])

        try:
            response = await self.llm.complete(prompt, schema=CLASSIFICATION_SCHEMA)

            result = ClassificationResult(
                category=response["category"],
                summary=response["summary"],
                severity=response["severity"],
                suggested_action=response["suggested_action"],
                confidence=response.get("confidence", 0.8),
            )

            logger.info(
                "Classified topic as %s (confidence: %.2f): %s",
                result.category,
                result.confidence,
                title[:50],
            )

            return result

        except Exception as e:
            logger.error("Failed to classify topic: %s", e)
            # Return a default non-actionable result on error
            return ClassificationResult(
                category="OTHER",
                summary="Classification failed",
                severity=None,
                suggested_action="Manual review required",
                confidence=0.0,
            )

