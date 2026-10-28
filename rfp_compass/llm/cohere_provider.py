"""Native Cohere chat adapter."""

from __future__ import annotations

import time
from typing import Any

import cohere

from ..models import ConnectionConfig
from .base import GenerationResult, LLMProvider


class CohereProvider(LLMProvider):
    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self.client = cohere.ClientV2(api_key=config.api_key.get_secret_value() if config.api_key else "")

    def generate_json(self, system: str, user: str, schema: dict[str, Any], **opts: Any) -> GenerationResult:
        start = time.perf_counter()
        response = self.client.chat(model=self.config.model, messages=[{"role": "system", "content": system + " Return JSON only."}, {"role": "user", "content": user}], temperature=0)
        content = getattr(getattr(response, "message", None), "content", None) or []
        text_parts = []
        for block in content:
            value = getattr(block, "text", None)
            if isinstance(value, str) and value.strip():
                text_parts.append(value)
            elif isinstance(block, dict) and isinstance(block.get("text"), str) and block["text"].strip():
                text_parts.append(block["text"])
        text = "\n".join(text_parts).strip()
        if not text:
            raise ValueError("Cohere returned no text content. Confirm the selected model supports chat completions and returned a text response.")
        usage = getattr(response, "usage", None)
        return GenerationResult(text, self.config.model,
            getattr(getattr(usage, "tokens", None), "input_tokens", None),
            getattr(getattr(usage, "tokens", None), "output_tokens", None), (time.perf_counter()-start)*1000, response)

    def list_models(self) -> list[str]:
        return [self.config.model]
