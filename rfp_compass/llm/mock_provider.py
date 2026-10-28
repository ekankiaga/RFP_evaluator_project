"""Deterministic offline model for demos and test pipelines."""

from __future__ import annotations

import json
import re
from typing import Any

from .base import GenerationResult, LLMProvider


class MockLLM(LLMProvider):
    """Deterministic provider that scores criteria from document keyword evidence."""
    def generate_json(self, system: str, user: str, schema: dict[str, Any], **opts: Any) -> GenerationResult:
        # Prefer the canonical criteria supplied by the orchestrator over reparsing
        # nested JSON arrays from the prompt.
        criteria = opts.get("criteria") or []
        if not criteria:
            criteria_match = re.search(r"ACTIVE CRITERIA:\s*(\[.*?\])\s*MANDATORY GATES:", user, re.S)
            criteria = json.loads(criteria_match.group(1)) if criteria_match else []
        document = user.split("SUPPLIER DOCUMENT EXCERPT:", 1)[-1] if "SUPPLIER DOCUMENT EXCERPT:" in user else user.split("DOCUMENT_TEXT:", 1)[-1]
        document = re.sub(r"\[Page\s+\d+\]\s*", "", document)
        lower = document.casefold()
        document = re.sub(r"SYNTHETIC DEMO PROPOSAL[^\n]*|Page \d+", "", document, flags=re.I)
        all_sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", document)
                         if len(part.strip()) >= 25]
        names = [str(item.get("name", "")).strip() for item in criteria]
        normalized_names = {re.sub(r"\s+", " ", name).casefold(): name for name in names if name}
        document_lines = document.splitlines()
        criterion_sections: dict[str, str] = {}
        for line_no, line in enumerate(document_lines):
            heading = re.sub(r"\s+", " ", line.strip()).casefold()
            if heading not in normalized_names:
                continue
            body = []
            for candidate in document_lines[line_no + 1:]:
                normalized = re.sub(r"\s+", " ", candidate.strip()).casefold()
                if normalized in normalized_names or normalized.startswith(("key exception", "references")):
                    break
                if candidate.strip():
                    body.append(candidate.strip())
            criterion_sections[normalized_names[heading]] = "\n".join(body)
        aliases = {
            "technical capability": ["users", "capacity"],
            "implementation plan": ["program director", "migration lead", "week rollout", "rehearsals", "rollback", "administrator training"],
            "commercial value": ["five-year total", "million", "including implementation", "priced separately", "extraction fee"],
            "security & compliance": ["SOC 2", "ISO 27001", "AES-256", "incident plan"],
            "support & experience": ["priority 1", "24 by 7", "response target", "comparable deployments"],
            "service levels & availability": ["uptime", "service credit", "response target", "recovery time"],
            "api & integration depth": ["API", "connector", "integration", "SCIM", "REST"],
            "data residency & privacy": ["region", "US", "EU", "hosting"],
            "exit & portability": ["export", "portability", "transition assistance", "deletion certificate", "CSV", "JSON"],
            "security certification": ["ISO 27001", "SOC 2", "certificate"],
        }
        records = []
        risks: list[str] = []
        for criterion in criteria:
            name = str(criterion.get("name", ""))
            criterion_text = criterion_sections.get(name, document)
            criterion_lower = criterion_text.casefold()
            sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", criterion_text)
                         if len(part.strip()) >= 25]
            max_score = float(criterion.get("max_score", 10))
            evidence_terms = list(criterion.get("evidence_hints", []) or [])
            if name.casefold() in aliases:
                evidence_terms = aliases[name.casefold()]
            if not evidence_terms:
                inspect_text = str(criterion.get("what_to_inspect", ""))
                evidence_terms = [part.strip() for part in re.split(r"[,;/\n]|\band\b|\bor\b", inspect_text, flags=re.I) if part.strip()]
            evidence_terms = [term.casefold() for term in evidence_terms if len(term.strip()) >= 2]
            if not evidence_terms:
                evidence_terms = [word for word in re.findall(r"[a-z]{4,}", name.casefold())]
            found = [term for term in evidence_terms if term in criterion_lower]
            matching = [(sum(term in sentence.casefold() for term in evidence_terms), len(sentence), sentence)
                        for sentence in sentences]
            hits, _, matched_sentence = max(matching, default=(0, 0, ""), key=lambda item: (item[0], item[1]))
            # Keep the offline score readable: several cues may describe the same
            # evidence, so a long keyword list must not dilute a well-supported
            # criterion. Explicit gaps cap coverage even when their wording
            # happens to contain the expected keyword (for example, "region not listed").
            coverage = len(found) / max(1, min(2, len(evidence_terms)))
            explicit_gaps = (
                "not specified", "does not specify", "not identified", "not listed",
                "not stated", "not described", "no current", "in progress", "planned",
                "not included", "not supplied", "to be agreed", "without a named",
                "does not include", "no report", "no certificate", "not provided",
            )
            if any(phrase in criterion_lower for phrase in explicit_gaps):
                coverage = min(coverage, 0.25)
            if name.casefold() == "commercial value":
                exclusions = criterion_lower.count("excludes") + criterion_lower.count("excluded")
                if exclusions:
                    coverage = min(coverage, 0.78 if exclusions == 1 else 0.58)
            if any(char.isdigit() for char in criterion_text):
                coverage = min(1.0, coverage + 0.12)
            score = round(min(max_score, 2.0 + 8.0 * coverage), 1)
            matched_flags = [str(flag) for flag in criterion.get("red_flags", []) if str(flag).casefold() in criterion_lower]
            if name.casefold() == "security certification":
                if any(term in criterion_lower for term in ("no current soc 2", "no iso 27001 certificate", "audit is planned")):
                    score = min(score, 2.5)
                    risks.append(f"{name}: required current assurance evidence is missing or planned")
                elif "in progress" in criterion_lower:
                    score = min(score, 3.5)
                    risks.append(f"{name}: certification or audit is still in progress")
            if matched_flags:
                score = max(0.0, round(score - min(3.0, 1.5 * len(matched_flags)), 1))
                risks.extend(f"{name}: {flag}" for flag in matched_flags)
            quote = matched_sentence[:220] if hits or criterion_text.strip() else ""
            if not quote:
                justification = "No criterion-specific evidence was located in the proposal; review this requirement manually."
            elif coverage >= .75:
                justification = "The response gives several concrete details for this requirement. Confirm the cited terms in the final contract."
            elif coverage >= .4:
                justification = "The response addresses part of this requirement, but some details or commitments remain unclear."
            else:
                justification = "The proposal provides limited evidence for this requirement; clarify the gap before relying on the score."
            records.append({"criterion_id": criterion.get("criterion_id", name), "score": score,
                            "max_score": max_score, "justification": justification,
                            "evidence": quote, "confidence": "high" if coverage >= .75 and quote else "medium" if quote else "low"})
        gates_match = re.search(r"MANDATORY GATES:\s*(\[.*?\])\s*SUPPLIER DOCUMENT EXCERPT:", user, re.S)
        definitions = json.loads(gates_match.group(1)) if gates_match else []
        gate_results = []
        for gate in definitions:
            name = str(gate.get("name", "Mandatory gate"))
            gate_id = str(gate.get("gate_id", name))
            rule = f"{name} {gate.get('rule', '')}".casefold()
            if any(term in rule for term in ("iso", "soc 2", "certificate", "assurance")):
                matches = [sentence for sentence in all_sentences if any(term in sentence.casefold() for term in ("iso 27001", "soc 2", "security certificate"))]
                negative = ("in progress", "not current", "expired", "no current", "not included", "will obtain", "no baa", "no business associate agreement", "does not include a baa", "doesn't include a baa")
                if matches:
                    quote = matches[0]
                    outcome = "no" if any(term in quote.casefold() for term in negative) else "yes" if any(term in quote.casefold() for term in ("current", "valid", "certified", "issued")) else "unclear"
                else:
                    quote, outcome = "", "unclear"
            else:
                gate_terms = [term for term in ("business associate agreement", "baa", "gxp", "hipaa") if term in rule]
                matches = [sentence for sentence in sentences if any(term in sentence.casefold() for term in gate_terms)]
                if matches:
                    quote = matches[0]
                    outcome = "no" if any(term in quote.casefold() for term in ("not offered", "not available", "will not", "decline", "no baa", "no business associate agreement", "does not include a baa")) else "yes" if any(term in quote.casefold() for term in ("offered", "included", "will sign", "compliant")) else "unclear"
                else:
                    quote, outcome = "", "unclear"
            gate_results.append({"gate_id": gate_id, "name": name, "met": outcome, "evidence": quote, "mandatory": bool(gate.get("mandatory", True))})
        payload = {"supplier_name": "", "criteria": records, "risks": risks, "overall_summary": "Offline keyword-based demo evaluation. Confirm every score and mandatory gate against the proposal before relying on the result.", "gates": gate_results}
        text = json.dumps(payload, ensure_ascii=False)
        return GenerationResult(text=text, model=self.config.model, input_tokens=len(user.split()), output_tokens=len(text.split()))

    def list_models(self) -> list[str]:
        return [self.config.model]
