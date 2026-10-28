"""Dynamic evidence-grounded evaluation prompts and deterministic chunk merging."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, Callable

from ..models import EvaluationPayload
from ..tools.validation_tool import ValidationTool


class EvaluationAgent:
    """Ask a provider for criterion judgments and merge chunk judgments reproducibly."""
    def __init__(self, generator: Callable[..., Any], validator: ValidationTool | None = None,
                 prompt_version: str = "rfp-evaluation-v1", chunk_chars: int = 18000):
        self.generator = generator
        self.validator = validator or ValidationTool()
        self.prompt_version = prompt_version
        self.chunk_chars = chunk_chars
        prompt_dir = Path(__file__).resolve().parents[1] / "prompts"
        self.system_prompt = (prompt_dir / "evaluation_system.txt").read_text(encoding="utf-8")
        self.user_template = (prompt_dir / "evaluation_user.txt").read_text(encoding="utf-8")

    def evaluate(self, *, supplier_name: str, criteria: list[dict[str, Any]], pages: list[dict[str, Any]],
                 domain_addendum: str = "", gates: list[dict[str, Any]] | None = None) -> tuple[EvaluationPayload, list[str]]:
        chunks = self._chunks(pages)
        outputs: list[EvaluationPayload] = []
        warnings: list[str] = []
        schema = {"type": "object", "properties": {"supplier_name": {"type": "string"}, "criteria": {"type": "array"}, "gates": {"type": "array"}}}
        for chunk_pages in chunks:
            excerpt = "\n\n".join(f"[Page {p['page']}]\n{p['text']}" for p in chunk_pages)
            user = self.user_template.format(domain_addendum=domain_addendum or "Use evidence-based procurement judgment.",
                criteria_json=json.dumps(criteria, ensure_ascii=False), gates_json=json.dumps(gates or [], ensure_ascii=False), document_text=excerpt)
            generated = self.generator(self.system_prompt, user, schema, document_hash="", criteria=criteria)
            generation = generated[0] if isinstance(generated, tuple) else generated
            try:
                payload, chunk_warnings = self.validator.validate(generation.text, criteria, chunk_pages, gates)
            except (ValueError, json.JSONDecodeError) as exc:
                repair = self.validator.repair_prompt(generation.text, str(exc))
                generated = self.generator("Repair the previous output and return strict JSON only.", repair, schema,
                                             document_hash="", criteria=criteria, bypass_cache=True)
                generation = generated[0] if isinstance(generated, tuple) else generated
                payload, chunk_warnings = self.validator.validate(generation.text, criteria, chunk_pages, gates)
                chunk_warnings.append("Malformed model JSON repaired once.")
            outputs.append(payload)
            warnings.extend(chunk_warnings)
        if not outputs:
            raise ValueError("Document has no evaluable pages")
        merged: list[dict[str, Any]] = []
        confidence_order = {"low": 0, "medium": 1, "high": 2}
        for index, criterion in enumerate(criteria):
            judgments = [output.criteria[index] for output in outputs if index < len(output.criteria)]
            scores = [float(item.score) for item in judgments]
            chosen = max(judgments, key=lambda item: (confidence_order.get(item.confidence.casefold(), 0), bool(item.evidence)))
            merged.append({**chosen.model_dump(), "score": float(statistics.median(scores)) if scores else 0.0,
                           "max_score": float(criterion.get("max_score", 10))})
        risks = sorted({risk for output in outputs for risk in output.risks})
        summaries = [output.overall_summary for output in outputs if output.overall_summary]
        gates_out = self._merge_gates([gate for output in outputs for gate in output.gates])
        if len(outputs) > 1:
            warnings.append(f"Evaluated {len(outputs)} page chunks; used median criterion scores and confidence-ranked evidence.")
        return EvaluationPayload(supplier_name=supplier_name, criteria=merged, risks=risks,
                                 overall_summary=" ".join(summaries[:3]), gates=gates_out), warnings

    def _chunks(self, pages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        chunks: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        size = 0
        for page in pages:
            text = str(page.get("text", ""))
            if current and size + len(text) > self.chunk_chars:
                chunks.append(current)
                current, size = [], 0
            if len(text) > self.chunk_chars:
                for offset in range(0, len(text), self.chunk_chars):
                    if current:
                        chunks.append(current)
                        current = []
                    chunks.append([{**page, "text": text[offset:offset + self.chunk_chars]}])
                continue
            current.append(page)
            size += len(text)
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _merge_gates(gates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for gate in gates:
            key = str(gate.get("gate_id", gate.get("name", "gate")))
            previous = merged.get(key)
            if previous is None or (previous.get("outcome") == "unclear" and gate.get("outcome") != "unclear"):
                merged[key] = gate
        return [merged[key] for key in sorted(merged)]
