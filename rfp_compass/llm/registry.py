"""Data-driven metadata for supported LLM connections."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    display_name: str
    icon: str
    key_format_hint: str
    default_base_url: str | None
    auth_style: str
    needs_api_key: bool
    native_json_mode: bool
    docs_url: str
    adapter: str


PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec("openai", "OpenAI", "◉", "sk-…", "https://api.openai.com/v1", "bearer", True, True, "https://platform.openai.com/docs", "openai_compatible"),
    "anthropic": ProviderSpec("anthropic", "Anthropic Claude", "✳", "sk-ant-…", None, "x-api-key", True, False, "https://docs.anthropic.com/", "anthropic"),
    "gemini": ProviderSpec("gemini", "Google Gemini", "✦", "AIza…", None, "google-api-key", True, True, "https://ai.google.dev/gemini-api/docs", "gemini"),
    "azure_openai": ProviderSpec("azure_openai", "Azure OpenAI", "▦", "Azure key", None, "api-key", True, True, "https://learn.microsoft.com/azure/ai-services/openai/", "openai_compatible"),
    "mistral": ProviderSpec("mistral", "Mistral", "◆", "…", "https://api.mistral.ai/v1", "bearer", True, True, "https://docs.mistral.ai/", "openai_compatible"),
    "groq": ProviderSpec("groq", "Groq", "ϟ", "gsk_…", "https://api.groq.com/openai/v1", "bearer", True, True, "https://console.groq.com/docs", "openai_compatible"),
    "together": ProviderSpec("together", "Together AI", "◈", "…", "https://api.together.xyz/v1", "bearer", True, True, "https://docs.together.ai/", "openai_compatible"),
    "openrouter": ProviderSpec("openrouter", "OpenRouter", "⇄", "sk-or-…", "https://openrouter.ai/api/v1", "bearer", True, True, "https://openrouter.ai/docs", "openai_compatible"),
    "deepseek": ProviderSpec("deepseek", "DeepSeek", "◌", "sk-…", "https://api.deepseek.com/v1", "bearer", True, True, "https://api-docs.deepseek.com/", "openai_compatible"),
    "cohere": ProviderSpec("cohere", "Cohere", "●", "…", None, "bearer", True, False, "https://docs.cohere.com/", "cohere"),
    "ollama": ProviderSpec("ollama", "Ollama (local)", "⬡", "No key", "http://localhost:11434/v1", "none", False, True, "https://github.com/ollama/ollama", "openai_compatible"),
    "lm_studio": ProviderSpec("lm_studio", "LM Studio (local)", "▣", "No key", "http://localhost:1234/v1", "none", False, True, "https://lmstudio.ai/docs", "openai_compatible"),
    "vllm": ProviderSpec("vllm", "vLLM (local/self-hosted)", "⬢", "Optional", "http://localhost:8000/v1", "bearer", False, True, "https://docs.vllm.ai/", "openai_compatible"),
    "custom_openai": ProviderSpec("custom_openai", "Custom OpenAI-compatible", "⌘", "Provider key", None, "bearer", True, False, "", "openai_compatible"),
    "litellm": ProviderSpec("litellm", "LiteLLM · 100+ provider routes", "🌐", "Provider key (optional if configured in environment)", None, "provider-specific", False, False, "https://docs.litellm.ai/docs/providers", "litellm"),
    "mock": ProviderSpec("mock", "Demo mode (Mock LLM)", "◉", "No key", None, "none", False, True, "", "mock"),
}


def get_provider(provider_id: str) -> ProviderSpec:
    """Return provider metadata or a clear ValueError for unsupported ids."""
    try:
        return PROVIDERS[provider_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported provider: {provider_id}") from exc
