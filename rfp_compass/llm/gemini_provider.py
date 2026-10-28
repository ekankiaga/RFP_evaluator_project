"""Native Google GenAI adapter."""

from __future__ import annotations

import time
from typing import Any

from google import genai
from google.genai import types

from ..models import ConnectionConfig
from .base import GenerationResult, LLMProvider


class GeminiProvider(LLMProvider):
    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        key = config.api_key.get_secret_value() if config.api_key else ""
        self.client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=int(config.timeout_seconds * 1000)))

    def generate_json(self, system: str, user: str, schema: dict[str, Any], **opts: Any) -> GenerationResult:
        start = time.perf_counter()
        response = self.client.models.generate_content(model=self.config.model, contents=user,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0,
                max_output_tokens=opts.get("max_output_tokens", self.config.max_output_tokens), response_mime_type="application/json"))
        usage = getattr(response, "usage_metadata", None)
        return GenerationResult(response.text or "{}", self.config.model,
            getattr(usage, "prompt_token_count", None), getattr(usage, "candidates_token_count", None),
            (time.perf_counter() - start) * 1000, response)

    def list_models(self) -> list[str]:
        return [self.config.model]
