"""Provider interface and structured generation response."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..models import ConnectionConfig


@dataclass
class GenerationResult:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None
    raw: Any = None


class LLMProvider(ABC):
    """Uniform JSON-generation API for remote and local model providers."""
    def __init__(self, config: ConnectionConfig):
        self.config = config

    @abstractmethod
    def generate_json(self, system: str, user: str, schema: dict[str, Any], **opts: Any) -> GenerationResult:
        """Generate a JSON response matching schema."""

    @abstractmethod
    def list_models(self) -> list[str]:
        """List models available to this connection."""

    def healthcheck(self) -> bool:
        """Perform provider-specific minimal health check."""
        self.list_models()
        return True
