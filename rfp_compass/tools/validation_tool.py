"""Pydantic-backed JSON parsing, normalization, and evidence verification."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from ..models import EvaluationPayload
from .document_tool import verify_quote


class ValidationTool:
    """Normalize provider output into one traceable result for each criterion."""

    def parse_json(self, raw: str) -> Any:
        candidate = raw.strip()
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.I)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Keep only the outermost JSON object if provider adds short preamble text.
            start, end = candidate.find("{"), candidate.rfind("}")
            if start >= 0 and end > start:
                return json.loads(candidate[start:end + 1])
            raise

    def validate(self, raw: str | dict[str, Any], criteria: list[dict[str, Any]], pages: list[dict[str, object]] | None = None,
                 gates: list[dict[str, Any]] | None = None) -> tuple[EvaluationPayload, list[str]]:
        warnings: list[str] = []
        data = self.parse_json(raw) if isinstance(raw, str) else raw
        if not isinstance(data, dict):
            raise ValueError("LLM response must be a JSON object")
        active = []
        for index, item in enumerate(criteria, start=1):
            if not item.get("is_active", True):
                continue
            criterion = dict(item)
            if criterion.get("criterion_id") is None or not str(criterion.get("criterion_id")).strip():
                criterion["criterion_id"] = str(criterion.get("name") or f"criterion-{index}")
            active.append(criterion)
        criterion_map = {str(c["criterion_id"]): c for c in active}
        # Some providers echo a null/missing ID when it was absent in imported
        # template data. Match by criterion name first, then by requested order
        # only when the response contains exactly one row per active criterion.
        raw_results = data.get("criteria")
        if isinstance(raw_results, list):
            name_to_id = {str(c.get("name", "")).casefold().strip(): key for key, c in criterion_map.items()}
            for index, item in enumerate(raw_results):
                if not isinstance(item, dict) or item.get("criterion_id") not in (None, ""):
                    continue
                result_name = str(item.get("criterion_name", item.get("name", ""))).casefold().strip()
                matched_id = name_to_id.get(result_name)
                if matched_id is None and len(raw_results) == len(active) and index < len(active):
                    matched_id = str(active[index]["criterion_id"])
                if matched_id is not None:
                    item["criterion_id"] = matched_id
                    warnings.append(f"Matched a missing model criterion_id to {criterion_map[matched_id]['name']}.")
        try:
            parsed = EvaluationPayload.model_validate(data)
        except ValidationError as exc:
            raise ValueError(f"LLM response schema invalid: {exc}") from exc
        normalized = []
        seen: set[str] = set()
        for result in parsed.criteria:
            key = str(result.criterion_id)
            if key not in criterion_map:
                warnings.append(f"Dropped unknown criterion_id {key!r}.")
                continue
            if key in seen:
                warnings.append(f"Dropped duplicate criterion_id {key!r}; retained first result.")
                continue
            seen.add(key)
            crit = criterion_map[key]
            max_score = float(crit.get("max_score", 10))
            score = float(result.score)
            clipped = min(max(score, 0.0), max_score)
            if clipped != score:
                warnings.append(f"Clipped score for {crit['name']} from {score:g} to {clipped:g}.")
            quote = result.evidence.quote if hasattr(result.evidence, "quote") else str(result.evidence)
            page = result.evidence.page if hasattr(result.evidence, "page") else None
            verified, found_page = verify_quote(quote, pages or []) if pages is not None else (False, None)
            if pages is not None and quote and not verified:
                warnings.append(f"Evidence not found for {crit['name']}; confidence lowered.")
                quote, page = "Evidence not found", None
                confidence = "low"
            else:
                confidence = result.confidence
                if verified:
                    page = found_page
            normalized.append({"criterion_id": result.criterion_id, "score": clipped,
                               "max_score": max_score, "justification": result.justification,
                               "evidence": {"quote": quote, "page": page, "verified": verified},
                               "confidence": confidence})
        for key, crit in criterion_map.items():
            if key not in seen:
                warnings.append(f"Missing criterion {crit['name']}; normalized to score 0.")
                normalized.append({"criterion_id": crit.get("criterion_id", key), "score": 0,
                                   "max_score": float(crit.get("max_score", 10)),
                                   "justification": "No criterion result returned by the model.",
                                   "evidence": {"quote": "", "page": None, "verified": False}, "confidence": "low"})
        gate_defs = gates or []
        gate_map = {str(g.get("gate_id", g.get("name", f"gate-{i}"))): g for i, g in enumerate(gate_defs)}
        normalized_gates: list[dict[str, Any]] = []
        seen_gates: set[str] = set()
        for result in parsed.gates:
            gate_id = str(result.get("gate_id", result.get("name", "")))
            if gate_map and gate_id not in gate_map:
                warnings.append(f"Dropped unknown mandatory gate {gate_id!r}.")
                continue
            definition = gate_map.get(gate_id, {})
            gate_id = gate_id or str(definition.get("gate_id", definition.get("name", "gate")))
            outcome = str(result.get("met", result.get("outcome", "unclear"))).casefold()
            outcome = {"true": "yes", "pass": "yes", "passed": "yes", "met": "yes", "false": "no", "fail": "no", "failed": "no"}.get(outcome, outcome)
            if outcome not in {"yes", "no", "unclear"}:
                outcome = "unclear"
                warnings.append(f"Invalid outcome for gate {gate_id}; normalized to unclear.")
            if outcome == "unclear":
                warnings.append(f"Mandatory gate {gate_id} is unclear and needs human review.")
            quote = str(result.get("evidence", ""))
            page = result.get("page")
            verified, found_page = verify_quote(quote, pages or []) if pages is not None else (False, None)
            if pages is not None and quote and not verified:
                quote, page = "Evidence not found", None
                outcome = "unclear"
                warnings.append(f"Gate evidence not found for {gate_id}; routed to human review.")
            elif verified:
                page = found_page
            normalized_gates.append({"gate_id": gate_id, "name": result.get("name", definition.get("name", gate_id)),
                "outcome": outcome, "evidence": quote, "page": page,
                "mandatory": bool(result.get("mandatory", definition.get("mandatory", True)))})
            seen_gates.add(gate_id)
        for gate_id, definition in gate_map.items():
            if gate_id not in seen_gates:
                normalized_gates.append({"gate_id": gate_id, "name": definition.get("name", gate_id), "outcome": "unclear",
                    "evidence": "", "page": None, "mandatory": bool(definition.get("mandatory", True))})
                warnings.append(f"Missing mandatory gate result for {gate_id}; routed to human review.")
        normalized.sort(key=lambda r: list(criterion_map).index(str(r["criterion_id"])))
        validated = EvaluationPayload.model_validate({**parsed.model_dump(), "criteria": normalized, "gates": normalized_gates})
        return validated, warnings

    @staticmethod
    def repair_prompt(raw: str, error: str) -> str:
        return ("Repair the following response into valid JSON matching the requested schema. Preserve only stated facts; "
                "do not invent evidence. Return JSON only.\nValidation error: " + error + "\nResponse:\n" + raw)
