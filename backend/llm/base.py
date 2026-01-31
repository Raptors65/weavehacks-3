"""Base LLM protocol for extensibility."""

from abc import ABC, abstractmethod
from typing import Any


class BaseLLM(ABC):
    """Abstract base class for LLM providers.

    Implement this to add support for new LLM providers (Anthropic, local, etc.).

    Example:
        class AnthropicLLM(BaseLLM):
            def __init__(self, model: str = "claude-3-haiku"):
                self.model = model
                self.client = Anthropic()

            async def complete(
                self,
                prompt: str,
                schema: dict | None = None,
            ) -> dict:
                # Implementation here
                ...
    """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model name being used."""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate a completion for the given prompt.

        Args:
            prompt: The prompt to send to the LLM.
            schema: Optional JSON schema for structured output.
                   If provided, the LLM should return data matching this schema.

        Returns:
            A dictionary containing the LLM's response.
            If schema was provided, response will match the schema.
        """

