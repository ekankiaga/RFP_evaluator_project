"""Deterministic weight what-if analysis and fixed-seed robustness simulation."""

from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..db import connect, migrate
from .ranking_tool import RankingTool
from .scoring_tool import absolute_weighted_score, benchmark_metrics, peer_performance_index


class WhatIfEngine:
    """Recompute rankings under proposed weights without altering official results."""
    def evaluate(self, suppliers: list[dict[str, Any]], criteria: list[dict[str, Any]],
                 weights: dict[str, float] | None = None) -> dict[str, Any]:
        applied = self._validated_weights(criteria, weights)
        scenario_criteria = [dict(c, weight=applied[str(c.get("criterion_id", c["name"]))]) for c in criteria]
        evaluated = [dict(s) for s in suppliers]
        scores = {s["supplier_name"]: [dict(item, score=float(item.get("final_score", item["score"]))) for item in s["scores"]] for s in evaluated}
        benchmarks = benchmark_metrics(scores, scenario_criteria)
        for supplier in evaluated:
            name = supplier["supplier_name"]
            supplier["absolute_score"] = absolute_weighted_score(scores[name], scenario_criteria)
            supplier["ppi"] = peer_performance_index(benchmarks[name], scenario_criteria)
            supplier["benchmark_metrics"] = benchmarks[name]
        calculated_base = RankingTool().rank(evaluated)
        calculated_ranks = {s["supplier_name"]: int(s["rank"]) for s in calculated_base}
        baseline = {s["supplier_name"]: int(s.get("rank") or calculated_ranks[s["supplier_name"]]) for s in suppliers}
        ranked = RankingTool().rank(evaluated)
        for supplier in ranked:
            supplier["baseline_rank"] = baseline[supplier["supplier_name"]]
            supplier["rank_movement"] = baseline[supplier["supplier_name"]] - supplier["rank"]
        return {"weights": applied, "ranked_suppliers": ranked,
                "winner": ranked[0]["supplier_name"] if ranked else None,
                "official": False, "scenario_id": None}

    def sensitivity(self, suppliers: list[dict[str, Any]], criteria: list[dict[str, Any]],
                    perturbation: float = 10.0, simulations: int = 300, seed: int = 42) -> dict[str, Any]:
        """Perturb each weight with a fixed RNG seed and report winner stability."""
        if perturbation < 0 or simulations < 1:
            raise ValueError("Perturbation must be nonnegative and simulations must be positive")
        base = {str(c.get("criterion_id", c["name"])): float(c["weight"]) for c in criteria}
        if not base:
            raise ValueError("At least one criterion is required")
        baseline = self.evaluate(suppliers, criteria, base)
        rng = random.Random(seed)
        winners: dict[str, int] = {}
        switch_counts: dict[str, int] = {name: 0 for name in base}
        for _ in range(simulations):
            candidate = {key: max(0.01, value + rng.uniform(-perturbation, perturbation)) for key, value in base.items()}
            result = self.evaluate(suppliers, criteria, candidate)
            winner = result["winner"] or ""
            winners[winner] = winners.get(winner, 0) + 1
            for key, value in candidate.items():
                if abs(value - base[key]) > 1e-12:
                    switch_counts[key] += int(winner != baseline["winner"])
        top_winner = baseline["winner"]
        stable = winners.get(top_winner or "", 0)
        return {"baseline_winner": top_winner, "winner_counts": dict(sorted(winners.items())),
                "winner_stability_pct": round(stable * 100 / simulations, 2),
                "simulations": simulations, "seed": seed,
                "criterion_winner_change_counts": switch_counts}

    @staticmethod
    def _validated_weights(criteria: list[dict[str, Any]], weights: dict[str, float] | None) -> dict[str, float]:
        base = {str(c.get("criterion_id", c["name"])): float(c["weight"]) for c in criteria}
        requested = {**base, **(weights or {})}
        unknown = set(requested) - set(base)
        if unknown:
            raise ValueError(f"Unknown criterion weight keys: {sorted(unknown)}")
        if any(value < 0 for value in requested.values()):
            raise ValueError("Weights must be nonnegative")
        total = sum(requested.values())
        if total <= 0:
            raise ValueError("At least one criterion weight must be positive")
        keys = list(base)
        normalized: dict[str, float] = {}
        allocated = 0.0
        for key in keys[:-1]:
            normalized[key] = round(requested[key] * 100 / total, 6)
            allocated += normalized[key]
        normalized[keys[-1]] = round(100.0 - allocated, 6)
        return normalized

    def save_scenario(self, db_path: str | Path, rfp_run_id: str, name: str,
                      result: dict[str, Any]) -> str:
        """Persist an explicitly saved what-if scenario as non-official."""
        migrate(db_path)
        scenario_id = str(uuid.uuid4())
        with connect(db_path) as conn:
            conn.execute("INSERT INTO scenarios(scenario_id,rfp_run_id,name,weights_json,results_json,is_official,created_at) VALUES (?,?,?,?,?,0,?)",
                (scenario_id, rfp_run_id, name, json.dumps(result["weights"], sort_keys=True),
                 json.dumps(result["ranked_suppliers"], ensure_ascii=False, sort_keys=True), datetime.now(timezone.utc).isoformat()))
        return scenario_id
