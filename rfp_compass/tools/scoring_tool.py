"""Deterministic weighted scores and peer benchmark metrics."""

from __future__ import annotations

from typing import Any


def criterion_weighted_contribution(score: dict[str, Any] | None, criterion: dict[str, Any]) -> float:
    """Return one criterion's points toward the 100-point total, using reviewed scores."""
    if score is None:
        return 0.0
    final_score = float(score.get("final_score", score.get("score", 0)))
    maximum = float(criterion.get("max_score", score.get("max_score", 10)) or 0)
    weight = float(criterion.get("weight", 0))
    return (final_score / maximum) * weight if maximum > 0 else 0.0


def absolute_weighted_score(scores: list[dict[str, Any]], criteria: list[dict[str, Any]]) -> float:
    """Sum reviewed criterion contributions; weights are represented in percentage points."""
    by_key = {str(score["criterion_id"]): score for score in scores}
    return sum(criterion_weighted_contribution(
        by_key.get(str(criterion.get("criterion_id", criterion.get("name")))), criterion)
        for criterion in criteria)


def benchmark_metrics(supplier_scores: dict[str, list[dict[str, Any]]], criteria: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, float]]]:
    """Calculate criterion benchmark, gap, relative %, and weighted PPI per supplier."""
    by_key: dict[str, dict[str, float]] = {}
    for supplier, items in supplier_scores.items():
        by_key[supplier] = {str(item["criterion_id"]): float(item["score"]) for item in items}
    result: dict[str, dict[str, dict[str, float]]] = {s: {} for s in supplier_scores}
    for criterion in criteria:
        key = str(criterion.get("criterion_id", criterion.get("name")))
        values = [items.get(key, 0.0) for items in by_key.values()]
        benchmark = max(values, default=0.0)
        for supplier, items in by_key.items():
            score = items.get(key, 0.0)
            relative = (score / benchmark * 100) if benchmark else 100.0
            result[supplier][key] = {"benchmark": benchmark, "gap": score - benchmark, "relative_pct": relative}
    return result


def peer_performance_index(metrics: dict[str, dict[str, float]], criteria: list[dict[str, Any]]) -> float:
    """Weighted average of relative percentages; a zero benchmark uses 100% for zero."""
    weights = {str(c.get("criterion_id", c.get("name"))): float(c["weight"]) for c in criteria}
    total = sum(weights.values())
    return sum(metrics[key]["relative_pct"] * weight for key, weight in weights.items() if key in metrics) / total if total else 0.0
