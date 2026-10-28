"""Editable approximate token pricing and preflight cost estimates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    input_per_million_usd: float
    output_per_million_usd: float
    context_window: int | None = None


# Estimates in USD per million tokens; update against provider price sheets.
MODEL_PRICING: dict[str, ModelPrice] = {
    "gpt-6-luna": ModelPrice(0.10, 0.50, 1050000),
    "gpt-6.1-terra": ModelPrice(1.00, 5.00, 1050000),
    "gpt-4o-mini": ModelPrice(0.15, 0.60, 128000),
    "gpt-4o": ModelPrice(2.50, 10.00, 128000),
    "claude-3-5-haiku-latest": ModelPrice(0.80, 4.00, 200000),
    "claude-3-5-sonnet-latest": ModelPrice(3.00, 15.00, 200000),
    "gemini-2.0-flash": ModelPrice(0.10, 0.40, 1000000),
    "mistral-small-latest": ModelPrice(0.20, 0.60, 32000),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimate cost using known model rates; None means no configured rate."""
    price = MODEL_PRICING.get(model)
    if price is None:
        return None
    return (input_tokens * price.input_per_million_usd + output_tokens * price.output_per_million_usd) / 1_000_000
