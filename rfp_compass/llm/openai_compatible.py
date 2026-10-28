"""Adapter for OpenAI and OpenAI-compatible commercial/local endpoints."""

from __future__ import annotations

import json
import time
from typing import Any

from openai import OpenAI

from ..models import ConnectionConfig
from .base import GenerationResult, LLMProvider
from .registry import get_provider


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI SDK adapter configured by registry metadata and connection details."""
    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        spec = get_provider(config.provider_id.value)
        base_url = config.base_url or config.azure_endpoint or spec.default_base_url
        if config.provider_id.value == "azure_openai":
            if not config.azure_endpoint or not config.azure_deployment or not config.azure_api_version:
                raise ValueError("Azure requires endpoint, deployment name, and API version")
            base_url = config.azure_endpoint.rstrip("/") + f"/openai/deployments/{config.azure_deployment}"
            self.model = config.azure_deployment
        else:
            self.model = config.model
        key = config.api_key.get_secret_value() if config.api_key else "local-no-key"
        self.client = OpenAI(api_key=key, base_url=base_url, timeout=config.timeout_seconds,
                             max_retries=0, default_headers={"api-version": config.azure_api_version} if config.provider_id.value == "azure_openai" else None)

    def generate_json(self, system: str, user: str, schema: dict[str, Any], **opts: Any) -> GenerationResult:
        start = time.perf_counter()
        token_limit = opts.get("max_output_tokens", self.config.max_output_tokens)
        request = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        # OpenAI reasoning models use max_completion_tokens; older compatible
        # endpoints commonly still expect max_tokens.
        model_family = self.model.casefold().rsplit("/", 1)[-1]
        is_reasoning_model = model_family.startswith(("o1", "o3", "o4", "gpt-5", "gpt-6"))
        request["max_completion_tokens" if is_reasoning_model else "max_tokens"] = token_limit
        if self.config.provider_id.value == "openai" and model_family.startswith("gpt-6"):
            request["reasoning_effort"] = "none"
        if not is_reasoning_model:
            request["temperature"] = 0
        response = self.client.chat.completions.create(**request)
        choice = response.choices[0]
        usage = response.usage
        return GenerationResult(choice.message.content or "{}", self.model,
                                getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None),
                                (time.perf_counter() - start) * 1000, response)

    def list_models(self) -> list[str]:
        if self.config.provider_id.value == "azure_openai":
            return [self.config.azure_deployment or self.config.model]
        try:
            return sorted(m.id for m in self.client.models.list().data)
        except Exception:
            return [self.config.model]
