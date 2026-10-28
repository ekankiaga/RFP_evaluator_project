"""Optional domain suggestion agent; suggestions always require human confirmation."""

from __future__ import annotations

import json
from typing import Any

from ..models import DomainSuggestion


class DomainClassifier:
    """Suggest a shipped domain pack based on supplied procurement text."""
    def __init__(self, provider: Any):
        self.provider = provider

    def suggest(self, text: str, domain_packs: list[dict[str, Any]]) -> DomainSuggestion:
        choices = [{"domain_id": p["domain_id"], "name": p["name"], "description": p["description"]} for p in domain_packs]
        result = self.provider.generate_json("Classify procurement text into one listed domain. Use only supplied text and return JSON only.",
            "Domains: " + json.dumps(choices, ensure_ascii=False) + "\nText:\n" + text[:12000],
            {"type": "object", "properties": {"domain_id": {"type": "string"}, "confidence": {"type": "number"}, "rationale": {"type": "string"}, "evidence": {"type": "string"}}})
        suggestion = DomainSuggestion.model_validate_json(result.text)
        if suggestion.domain_id not in {p["domain_id"] for p in domain_packs}:
            raise ValueError("Classifier returned a domain that is not in the available pack list")
        return suggestion
