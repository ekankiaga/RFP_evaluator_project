"""Deterministic run insights and optional labeled AI narrative."""

from __future__ import annotations

import json
from typing import Any


class InsightsTool:
    """Build deterministic summaries, risk lists, questions, and negotiation levers."""
    def summarize(self, suppliers: list[dict[str, Any]], criteria: list[dict[str, Any]], provider: Any | None = None) -> dict[str, Any]:
        ranked = sorted(suppliers, key=lambda row: int(row.get("rank", 10**6)))
        leader = ranked[0] if ranked else None
        risk_items = []
        questions: dict[str, list[str]] = {}
        leverage: dict[str, list[str]] = {}
        for supplier in ranked:
            name = supplier["supplier_name"]
            supplier_risks = list(supplier.get("risks", []))
            supplier_questions: list[str] = []
            supplier_leverage: list[str] = []
            for item in supplier.get("scores", []):
                criterion = item.get("criterion_name", item.get("criterion_id", "criterion"))
                score_pct = float(item.get("final_score", item["score"])) / max(float(item.get("max_score", 10)), 1e-9)
                evidence = item.get("evidence", {})
                quote = evidence.get("quote", "") if isinstance(evidence, dict) else str(evidence)
                if score_pct < 0.55:
                    risk = f"{name}: weak evidence or performance for {criterion} ({score_pct:.0%} of maximum)."
                    risk_items.append(risk)
                    if risk not in supplier_risks:
                        supplier_risks.append(risk)
                    supplier_questions.append(f"Please clarify your approach and provide measurable evidence for {criterion}.")
                elif score_pct < 0.75:
                    supplier_questions.append(f"What commitments or evidence can you add to strengthen {criterion}?")
                if criterion.casefold().startswith("commercial") and score_pct < 0.75:
                    supplier_leverage.append("Ask for a clearer price breakdown, capped change fees, and milestone-based commercial terms.")
                if not quote or quote == "Evidence not found":
                    supplier_questions.append(f"Please identify proposal evidence supporting {criterion}.")
            for gate in supplier.get("gates", []):
                if gate.get("outcome") == "unclear":
                    supplier_questions.append(f"Please confirm whether mandatory gate '{gate.get('name', gate.get('gate_id'))}' is met and provide evidence.")
            questions[name] = sorted(set(supplier_questions))
            leverage[name] = sorted(set(supplier_leverage))
        result: dict[str, Any] = {"executive_summary": f"{leader['supplier_name']} leads the current deterministic ranking." if leader else "No evaluated suppliers.",
            "leader": leader["supplier_name"] if leader else None,
            "top_risks": sorted(set(risk_items)), "clarification_questions": questions,
            "negotiation_leverage": leverage, "ai_narrative": None}
        if provider is not None and ranked:
            prompt = {"leaderboard": [{"name": s["supplier_name"], "rank": s.get("rank"), "ppi": s.get("ppi")} for s in ranked],
                      "risks": result["top_risks"], "questions": questions}
            response = provider.generate_json("Using only these computed facts, write an executive narrative and propose specific clarification questions for each supplier. Do not alter ranking, scores, or risk facts. Return JSON with narrative and clarification_questions.",
                json.dumps(prompt, ensure_ascii=False), {"type": "object", "properties": {"narrative": {"type": "string"}, "clarification_questions": {"type": "object"}}})
            try:
                generated = json.loads(response.text)
                result["ai_narrative"] = {"label": "AI-generated narrative", "text": generated.get("narrative", "")}
                if isinstance(generated.get("clarification_questions"), dict):
                    result["ai_clarification_questions"] = generated["clarification_questions"]
            except json.JSONDecodeError:
                result["ai_narrative"] = {"label": "AI-generated narrative", "text": response.text}
        return result
