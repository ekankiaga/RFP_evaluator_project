"""Construct provider adapters from session-scoped connection settings."""

from __future__ import annotations

from ..models import ConnectionConfig
from .base import LLMProvider
from .mock_provider import MockLLM


def create_provider(config: ConnectionConfig) -> LLMProvider:
    """Create the adapter named by provider metadata."""
    provider = config.provider_id.value
    if provider == "mock":
        return MockLLM(config)
    if provider == "litellm":
        from .litellm_adapter import LiteLLMAdapter
        return LiteLLMAdapter(config)
    if provider == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(config)
    if provider == "gemini":
        from .gemini_provider import GeminiProvider
        return GeminiProvider(config)
    if provider == "cohere":
        from .cohere_provider import CohereProvider
        return CohereProvider(config)
    from .openai_compatible import OpenAICompatibleProvider
    return OpenAICompatibleProvider(config)
