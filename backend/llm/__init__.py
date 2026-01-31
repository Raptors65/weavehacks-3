"""LLM providers for text generation and classification."""

from llm.base import BaseLLM
from llm.openai import OpenAILLM

# Registry of available LLM providers
_PROVIDERS: dict[str, type[BaseLLM]] = {
    "openai": OpenAILLM,
}


def get_llm(provider: str = "openai", **kwargs) -> BaseLLM:
    """Factory function to get an LLM by provider name.

    Args:
        provider: Name of the LLM provider ("openai", etc.)
        **kwargs: Additional arguments passed to the LLM constructor.

    Returns:
        An instance of the requested LLM.

    Raises:
        ValueError: If the provider is not registered.
    """
    if provider not in _PROVIDERS:
        available = ", ".join(_PROVIDERS.keys())
        raise ValueError(f"Unknown LLM provider: {provider}. Available: {available}")

    return _PROVIDERS[provider](**kwargs)


def register_llm(name: str, llm_class: type[BaseLLM]) -> None:
    """Register a new LLM provider.

    Args:
        name: Name to register the LLM under.
        llm_class: The LLM class to register.
    """
    _PROVIDERS[name] = llm_class


__all__ = ["BaseLLM", "OpenAILLM", "get_llm", "register_llm"]

