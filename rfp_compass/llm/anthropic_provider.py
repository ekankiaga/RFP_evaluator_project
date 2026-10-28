"""Native Anthropic Messages API adapter."""

from __future__ import annotations

import time
from typing import Any

from anthropic import Anthropic

from ..models import ConnectionConfig
from .base import GenerationResult, LLMProvider


class AnthropicProvider(LLMProvider):
    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        key = config.api_key.get_secret_value() if config.api_key else ""
        self.client = Anthropic(api_key=key, timeout=config.timeout_seconds, max_retries=0)

    def generate_json(self, system: str, user: str, schema: dict[str, Any], **opts: Any) -> GenerationResult:
        start = time.perf_counter()
        response = self.client.messages.create(model=self.config.model, max_tokens=opts.get("max_output_tokens", self.config.max_output_tokens),
                                               temperature=0, system=system + " Return JSON only.", messages=[{"role": "user", "content": user}])
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        return GenerationResult(text, self.config.model, response.usage.input_tokens, response.usage.output_tokens,
                                (time.perf_counter() - start) * 1000, response)

    def list_models(self) -> list[str]:
        return [self.config.model]
