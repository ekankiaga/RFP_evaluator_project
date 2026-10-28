"""Explicit evaluation workflow orchestration with deterministic Python scoring."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit.audit_log import AuditLog
from .config import PROMPT_VERSION
from .db import connect, migrate
from .llm.base import LLMProvider
from .llm.key_vault import key_fingerprint, redact
from .models import ConnectionConfig
from .tools.criteria_tool import CriteriaTool
from .tools.document_tool import DocumentTool
from .tools.persistence_tool import PersistenceTool
from .tools.ranking_tool import RankingTool
from .tools.scoring_tool import absolute_weighted_score, benchmark_metrics, peer_performance_index
from .tools.validation_tool import ValidationTool
from .llm.provider_factory import create_provider
from .llm.pricing import estimate_cost
from .agents.evaluation_agent import EvaluationAgent

logger = logging.getLogger(__name__)


class Orchestrator:
    """Coordinate tools in order; proposal judgment is delegated to an LLM provider."""
    def __init__(self, provider: LLMProvider | ConnectionConfig, db_path: str | Path | None = None,
                 max_workers: int = 3, prompt_version: str = PROMPT_VERSION,
                 fallback_provider: LLMProvider | ConnectionConfig | None = None,
                 retries: int | None = None):
        self.provider = create_provider(provider) if isinstance(provider, ConnectionConfig) else provider
        self.fallback_provider = (create_provider(fallback_provider) if isinstance(fallback_provider, ConnectionConfig)
                                  else fallback_provider)
        self.db_path = db_path
        self.max_workers = max(1, min(4, max_workers))
        self.prompt_version = prompt_version
        self.retries = retries if retries is not None else int(getattr(getattr(provider, "config", None), "retries", 2))
        self.response_cache: dict[str, Any] = {}
        self.cache_lock = threading.Lock()
        self._worker_state = threading.local()
        self._key_salt = os.urandom(16)
        self.document_tool = DocumentTool()
        self.criteria_tool = CriteriaTool(db_path)
        self.validation_tool = ValidationTool()
        self.persistence_tool = PersistenceTool(db_path)
        self.ranking_tool = RankingTool()
        self.audit_log = AuditLog(db_path)
        self.steps: list[dict[str, Any]] = []

    def _step(self, name: str, status: str, message: str = "") -> None:
        self.steps.append({"name": name, "status": status, "message": message, "timestamp": datetime.now(timezone.utc).isoformat()})

    def evaluate(self, suppliers: list[dict[str, Any]], criteria: list[dict[str, Any]] | None = None,
                 domain_id: str = "custom_generic", criteria_set_id: str | None = None,
                 run_id: str | None = None, budget_cap_usd: float | None = None) -> dict[str, Any]:
        """Evaluate supplier PDFs, compute peer metrics/ranks, and persist one run."""
        rfp_run_id = run_id or f"RFP-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:10].upper()}"
        self.steps = []
        migrate(self.db_path)
        self._step("Create batch", "running", rfp_run_id)
        if criteria is None:
            criteria = self.criteria_tool.active_criteria()
        criteria = [dict(c) for c in criteria]
        # Imported templates may omit criterion_id. Give each row a stable ID
        # before the ID is serialized into a provider prompt or used in scoring.
        for index, criterion in enumerate(criteria, start=1):
            if criterion.get("criterion_id") is None or not str(criterion.get("criterion_id")).strip():
                criterion["criterion_id"] = str(criterion.get("name") or f"criterion-{index}")
        if not self.criteria_tool.validate_weights(criteria):
            raise ValueError("Active criterion weights must total 100% before evaluation")
        self._step("Reload active criteria", "complete", f"{len(criteria)} criteria; total weight 100%")
        try:
            domain_pack = self.criteria_tool.resolve_domain(domain_id)
        except FileNotFoundError:
            domain_pack = {"domain_prompt_addendum": "Use only the supplied criteria and proposal evidence.", "gates": []}
        prepared: list[dict[str, Any]] = []
        for original in suppliers:
            item = dict(original)
            document = self.document_tool.extract(item["pdf"])
            item["document"] = document
            item["document_hash"] = document.document_hash
            item["page_count"] = document.page_count
            item["warnings"] = list(document.warnings)
            if not document.text.strip():
                item["warnings"].append("No readable PDF text; supplier cannot be evaluated reliably.")
            prepared.append(item)
            self.audit_log.append(actor="system", role="Analyst", event_type="document_uploaded", entity_type="supplier", entity_id=item.get("supplier_name", "unknown"), rfp_run_id=rfp_run_id, after={"document_hash": item["document_hash"], "page_count": item["page_count"], "warnings": item["warnings"]})
        self._step("Extract supplier documents", "complete", f"{len(prepared)} PDFs processed")
        self._step("Estimate budget", "running", "Preflight estimate based on text and criterion size")
        input_tokens = sum((len(item["document"].text) // 4 + len(criteria) * 450) for item in prepared)
        output_tokens = len(prepared) * len(criteria) * 140
        model_obj = getattr(self.provider, "config", None)
        estimate = estimate_cost(getattr(model_obj, "model", ""), input_tokens, output_tokens)
        if estimate is None:
            # Conservative configurable fallback estimate when provider prices are unknown.
            estimate = (input_tokens * 0.50 + output_tokens * 1.50) / 1_000_000
        if budget_cap_usd is not None and estimate > budget_cap_usd:
            self.audit_log.append(actor="system", role="Analyst", event_type="budget_cap_reached", entity_type="run", entity_id=rfp_run_id, rfp_run_id=rfp_run_id, after={"estimate_usd": estimate, "cap_usd": budget_cap_usd})
            raise ValueError(f"Estimated cost ${estimate:.4f} exceeds budget cap ${budget_cap_usd:.4f}; run aborted before LLM calls")
        self._step("Budget check", "complete", f"Estimated cost ${estimate:.4f}")
        self._step("Evaluate proposals", "running", f"Using {self.provider.__class__.__name__} with up to {self.max_workers} workers")
        evaluated: list[dict[str, Any]] = []
        failures: list[str] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(self._evaluate_one, item, criteria, domain_pack): item for item in prepared}
            for future in as_completed(futures):
                supplier = futures[future]
                try:
                    evaluated.append(future.result())
                except Exception as exc:
                    safe_error = redact(exc)
                    failures.append(f"{supplier.get('supplier_name', 'supplier')}: {safe_error}")
                    supplier["warnings"].append(f"Evaluation failed: {safe_error}")
        if failures and not evaluated:
            raise RuntimeError("All supplier evaluations failed: " + "; ".join(failures))
        self._step("Validate model output", "complete", "Evidence and schema validation complete")
        score_map = {supplier["supplier_name"]: supplier["scores"] for supplier in evaluated}
        metrics = benchmark_metrics(score_map, criteria)
        for supplier in evaluated:
            supplier["absolute_score"] = absolute_weighted_score(supplier["scores"], criteria)
            supplier["benchmark_metrics"] = metrics[supplier["supplier_name"]]
            supplier["ppi"] = peer_performance_index(metrics[supplier["supplier_name"]], criteria)
            for score in supplier["scores"]:
                score.update(metrics[supplier["supplier_name"]].get(str(score["criterion_id"]), {}))
        self._step("Compute scores and benchmarks", "complete", "All arithmetic performed deterministically in Python")
        ranked = self.ranking_tool.rank(evaluated)
        self._step("Rank suppliers", "complete", "Stable PPI/date/experience/name sort applied")
        warnings = failures + [f"{s['supplier_name']}: {w}" for s in evaluated for w in s.get("warnings", [])]
        for index, warning in enumerate(warnings):
            self.audit_log.append(actor="system", role="Analyst", event_type="validation_warning", entity_type="run",
                entity_id=rfp_run_id, rfp_run_id=rfp_run_id, after={"warning": warning}, reason=f"warning-{index + 1}")
        model = getattr(self.provider, "config", None)
        model_name = getattr(model, "model", getattr(self.provider, "model", "unknown"))
        provider_config = getattr(self.provider, "config", None)
        provider_id = getattr(getattr(provider_config, "provider_id", None), "value", self.provider.__class__.__name__)
        base_url = getattr(provider_config, "base_url", None) or getattr(provider_config, "azure_endpoint", None) or ""
        base_url_host = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(base_url).hostname
        fingerprint = key_fingerprint(provider_config.api_key.get_secret_value(), self._key_salt) if provider_config and provider_config.api_key else None
        reproducibility = {"provider": self.provider.__class__.__name__, "provider_id": provider_id,
            "base_url_host": base_url_host, "key_fingerprint": fingerprint, "model": model_name,
            "prompt_version": self.prompt_version, "criteria_hash": hashlib.sha256(json.dumps(criteria, sort_keys=True).encode()).hexdigest(),
            "documents": {s["supplier_name"]: s["document_hash"] for s in evaluated}, "budget_estimate_usd": estimate}
        self.persistence_tool.save_run(rfp_run_id=rfp_run_id, criteria_set_id=criteria_set_id, domain_id=domain_id,
            criteria=criteria, suppliers=ranked, model=model_name, prompt_version=self.prompt_version,
            warnings=warnings, reproducibility=reproducibility)
        self.audit_log.append(actor="system", role="Analyst", event_type="run_evaluated", entity_type="run", entity_id=rfp_run_id, rfp_run_id=rfp_run_id,
                             after={"supplier_count": len(ranked), "model": model_name, "warnings": warnings})
        self._step("Persist run", "complete", f"Saved {rfp_run_id} with {len(ranked)} suppliers")
        return {"rfp_run_id": rfp_run_id, "created_at": datetime.now(timezone.utc).isoformat(), "status": "Draft",
                "model": model_name, "criteria": criteria, "suppliers": ranked, "warnings": warnings,
                "estimated_cost_usd": estimate, "steps": list(self.steps), "reproducibility": reproducibility}

    def _evaluate_one(self, supplier: dict[str, Any], criteria: list[dict[str, Any]], domain_pack: dict[str, Any] | None = None) -> dict[str, Any]:
        document = supplier["document"]
        call_started = time.perf_counter()
        agent = EvaluationAgent(self._generate, self.validation_tool, self.prompt_version)
        payload, warnings = agent.evaluate(supplier_name=supplier["supplier_name"], criteria=criteria,
            pages=document.pages, domain_addendum=(domain_pack or {}).get("domain_prompt_addendum", ""),
            gates=(domain_pack or {}).get("gates", []))
        generation, used_provider, cache_hit = self._worker_state.last_call
        prompt_hash = hashlib.sha256((document.document_hash + json.dumps(criteria, sort_keys=True) + self.prompt_version).encode()).hexdigest()
        scores = []
        for result in payload.criteria:
            crit = next(c for c in criteria if str(c.get("criterion_id", c.get("name"))) == str(result.criterion_id))
            scores.append({"criterion_id": result.criterion_id, "criterion_name": crit["name"], "score": float(result.score),
                           "final_score": float(result.score), "weight": float(crit["weight"]), "max_score": float(crit.get("max_score", 10)),
                           "justification": result.justification, "evidence": result.evidence.model_dump() if hasattr(result.evidence, "model_dump") else result.evidence,
                           "confidence": result.confidence})
        gates = []
        for gate in payload.gates:
            outcome = str(gate.get("met", gate.get("outcome", "unclear"))).casefold()
            if outcome not in {"yes", "no", "unclear", "met", "failed"}: outcome = "unclear"
            gates.append({"gate_id": str(gate.get("gate_id", gate.get("name", "gate"))), "name": gate.get("name", "Mandatory gate"),
                          "outcome": outcome, "evidence": gate.get("evidence", ""), "page": gate.get("page"), "mandatory": bool(gate.get("mandatory", True))})
        compliant = not any(g["mandatory"] and g["outcome"] in {"no", "failed"} for g in gates)
        call_id = str(uuid.uuid4())
        used_config = getattr(used_provider, "config", None)
        used_provider_id = getattr(getattr(used_config, "provider_id", None), "value", used_provider.__class__.__name__)
        used_base_url = getattr(used_config, "base_url", None) or getattr(used_config, "azure_endpoint", None) or ""
        used_base_url_host = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(used_base_url).hostname
        used_fingerprint = key_fingerprint(used_config.api_key.get_secret_value(), self._key_salt) if used_config and used_config.api_key else None
        with connect(self.db_path) if self.db_path else connect() as conn:
            conn.execute("INSERT INTO llm_calls(llm_call_id,provider_id,model,base_url_host,key_fingerprint,prompt_version,prompt_hash,document_hash,criteria_set_hash,input_tokens,output_tokens,latency_ms,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (call_id, used_provider_id, generation.model, used_base_url_host, used_fingerprint, self.prompt_version,
                 prompt_hash, document.document_hash,
                 hashlib.sha256(json.dumps(criteria, sort_keys=True).encode()).hexdigest(), generation.input_tokens,
                 generation.output_tokens, (time.perf_counter()-call_started)*1000, "success", datetime.now(timezone.utc).isoformat()))
        self.audit_log.append(actor="system", role="Analyst", event_type="llm_call", entity_type="supplier",
            entity_id=supplier["supplier_name"], after={"provider": used_provider.__class__.__name__, "model": generation.model,
            "prompt_version": self.prompt_version, "prompt_hash": prompt_hash,
            "input_tokens": generation.input_tokens, "output_tokens": generation.output_tokens,
            "latency_ms": (time.perf_counter()-call_started)*1000, "cache_hit": cache_hit,
            "provider_id": used_provider_id, "base_url_host": used_base_url_host, "key_fingerprint": used_fingerprint})
        return {"supplier_name": supplier["supplier_name"], "submission_date": str(supplier["submission_date"]),
                "experience_rating": float(supplier["experience_rating"]), "document_hash": document.document_hash,
                "document_name": supplier.get("document_name", ""), "page_count": document.page_count,
                "document_pages": document.pages,
                "text_quality": min(1.0, len(document.text) / max(1, document.page_count * 800)), "scores": scores,
                "risks": payload.risks, "overall_summary": payload.overall_summary, "gates": gates,
                "compliant": compliant, "status": "Under Review" if any(g["mandatory"] and g["outcome"] == "unclear" for g in gates) else "AI Evaluated",
                "warnings": supplier.get("warnings", []) + warnings}

    def _generate(self, system: str, user: str, schema: dict[str, Any], document_hash: str,
                  criteria: list[dict[str, Any]], bypass_cache: bool = False):
        """Retry transient provider failures, cache reproducible responses, and switch fallback."""
        chosen = self.provider
        cfg = getattr(chosen, "config", None)
        host = ""
        if cfg:
            base_url = cfg.base_url or cfg.azure_endpoint or ""
            host = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(base_url).hostname or ""
        criteria_hash = hashlib.sha256(json.dumps(criteria, sort_keys=True).encode()).hexdigest()
        cache_key = hashlib.sha256("|".join((chosen.__class__.__name__, getattr(cfg, "model", getattr(chosen, "model", "")),
            host, self.prompt_version, document_hash, criteria_hash, system, user)).encode()).hexdigest()
        with self.cache_lock:
            cached = None if bypass_cache else self.response_cache.get(cache_key)
        if cached is not None:
            self._worker_state.last_call = (cached, chosen, True)
            return cached, chosen, True
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                result = chosen.generate_json(system, user, schema)
                with self.cache_lock:
                    self.response_cache[cache_key] = result
                self._worker_state.last_call = (result, chosen, False)
                return result, chosen, False
            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    retry_after = getattr(exc, "retry_after", None)
                    delay = float(retry_after) if retry_after else min(8.0, 0.25 * (2 ** attempt)) + random.random() * 0.1
                    time.sleep(delay)
        if self.fallback_provider is not None and chosen is self.provider:
            fallback = self.fallback_provider
            self.audit_log.append(actor="system", role="Analyst", event_type="llm_provider_fallback_used",
                entity_type="llm", entity_id=getattr(getattr(fallback, "config", None), "model", fallback.__class__.__name__),
                after={"primary_provider": chosen.__class__.__name__, "fallback_provider": fallback.__class__.__name__})
            for attempt in range(self.retries + 1):
                try:
                    result = fallback.generate_json(system, user, schema)
                    self._worker_state.last_call = (result, fallback, False)
                    return result, fallback, False
                except Exception as exc:
                    last_error = exc
                    if attempt < self.retries:
                        time.sleep(min(8.0, 0.25 * (2 ** attempt)) + random.random() * 0.1)
        raise RuntimeError(f"LLM provider failed after retries: {redact(last_error)}") from last_error
