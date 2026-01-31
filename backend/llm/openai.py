"""OpenAI LLM provider."""

import json
import logging
import os
from typing import Any

import httpx

from llm.base import BaseLLM

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"


class OpenAILLM(BaseLLM):
    """OpenAI LLM provider using the chat completions API.

    Supports structured outputs via JSON schema.
    """

    def __init__(self, model: str | None = None, api_key: str | None = None):
        """Initialize the OpenAI LLM.

        Args:
            model: Model name to use. Defaults to LLM_MODEL env var or gpt-4o-mini.
            api_key: OpenAI API key. Defaults to OPENAI_API_KEY env var.
        """
        self._model = model or os.getenv("LLM_MODEL", DEFAULT_MODEL)
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")

        if not self._api_key:
            raise ValueError(
                "OpenAI API key not provided. Set OPENAI_API_KEY environment variable."
            )

        logger.info("Initialized OpenAI LLM with model: %s", self._model)

    @property
    def model_name(self) -> str:
        """Return the model name being used."""
        return self._model

    async def complete(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate a completion using OpenAI's API.

        Args:
            prompt: The prompt to send to the LLM.
            schema: Optional JSON schema for structured output.

        Returns:
            A dictionary containing the LLM's response.
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        messages = [{"role": "user", "content": prompt}]

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
        }

        # Use structured output if schema provided
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": schema,
                },
            }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]

        # Parse JSON if schema was provided
        if schema:
            try:
                return json.loads(content)
            except json.JSONDecodeError as e:
                logger.error("Failed to parse LLM response as JSON: %s", e)
                return {"error": "Failed to parse response", "raw": content}

        return {"content": content}

