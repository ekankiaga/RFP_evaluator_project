"""Optional universal adapter for LiteLLM-supported model providers."""

from __future__ import annotations

import time
from typing import Any

from .base import GenerationResult, LLMProvider


class LiteLLMAdapter(LLMProvider):
    """Route provider/model strings through LiteLLM's broad provider catalog."""
    def generate_json(self, system: str, user: str, schema: dict[str, Any], **opts: Any) -> GenerationResult:
        try:
            from litellm import completion
        except ImportError as exc:
            raise RuntimeError("The universal provider requires LiteLLM. Install it with: python -m pip install litellm") from exc

        start = time.perf_counter()
        request: dict[str, Any] = {
            "model": self.config.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": int(opts.get("max_output_tokens", self.config.max_output_tokens)),
            "timeout": self.config.timeout_seconds,
            "num_retries": self.config.retries,
        }
        if self.config.api_key:
            request["api_key"] = self.config.api_key.get_secret_value()
        if self.config.base_url:
            request["api_base"] = self.config.base_url

        # Do not force response_format: many supported providers guarantee JSON
        # differently. The shared strict-JSON prompt and validator handle output.
        response = completion(**request)
        choice = response.choices[0]
        message = choice.message
        content = getattr(message, "content", None) or "{}"
        usage = getattr(response, "usage", None)
        return GenerationResult(str(content), self.config.model,
            getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None),
            (time.perf_counter()-start)*1000, response)

    def list_models(self) -> list[str]:
        # LiteLLM model ids are provider-specific; the entered route is the source of truth.
        return [self.config.model]
