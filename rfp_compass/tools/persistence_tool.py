"""Persist complete run results in SQLite transactions."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..db import connect, migrate


class PersistenceTool:
    """Store run, supplier, score, gate, and computed result records."""
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path
        migrate(db_path) if db_path else migrate()

    def save_run(self, *, rfp_run_id: str, criteria_set_id: str | None, domain_id: str,
                 criteria: list[dict[str, Any]], suppliers: list[dict[str, Any]], model: str,
                 prompt_version: str, warnings: list[str], reproducibility: dict[str, Any] | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with connect(self.db_path) if self.db_path else connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO rfp_runs(rfp_run_id,created_at,updated_at,status,domain_id,criteria_set_id,model,prompt_version,criteria_snapshot_json,reproducibility_json,warnings_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (rfp_run_id, now, now, "Draft", domain_id, criteria_set_id, model, prompt_version,
                 json.dumps(criteria, ensure_ascii=False, sort_keys=True), json.dumps(reproducibility or {}, sort_keys=True), json.dumps(warnings, ensure_ascii=False)))
            for supplier in suppliers:
                sid = supplier.setdefault("supplier_id", str(uuid.uuid4()))
                conn.execute("INSERT INTO suppliers_in_run(supplier_id,rfp_run_id,supplier_name,submission_date,experience_rating,document_hash,document_name,page_count,text_quality,status,compliant,rank,warnings_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, rfp_run_id, supplier["supplier_name"], str(supplier["submission_date"]), supplier["experience_rating"],
                     supplier.get("document_hash", ""), supplier.get("document_name", ""), supplier.get("page_count"),
                     supplier.get("text_quality"), supplier.get("status", "AI Evaluated"), int(bool(supplier.get("compliant", True))),
                     supplier.get("rank"), json.dumps(supplier.get("warnings", []), ensure_ascii=False)))
                conn.execute("INSERT INTO supplier_results(rfp_run_id,supplier_id,supplier_name,submission_date,experience_rating,absolute_score,ppi,final_rank,result_json,tie_break_explanation) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (rfp_run_id, sid, supplier["supplier_name"], str(supplier["submission_date"]), supplier["experience_rating"],
                     supplier["absolute_score"], supplier["ppi"], supplier["rank"], json.dumps(supplier, ensure_ascii=False, sort_keys=True), supplier.get("tie_break_explanation", "")))
                for item in supplier.get("scores", []):
                    evidence = item.get("evidence") or {}
                    if isinstance(evidence, str): evidence = {"quote": evidence, "page": None, "verified": False}
                    conn.execute("INSERT INTO criterion_scores(supplier_id,criterion_key,criterion_name,weight,max_score,ai_score,final_score,justification,evidence_quote,page,evidence_verified,confidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (sid, str(item["criterion_id"]), item.get("criterion_name", str(item["criterion_id"])), item.get("weight", 0), item.get("max_score", 10), item["score"], item.get("final_score", item["score"]), item.get("justification", ""), evidence.get("quote", ""), evidence.get("page"), int(bool(evidence.get("verified"))), item.get("confidence", "medium")))
                for gate in supplier.get("gates", []):
                    conn.execute("INSERT INTO gate_results(supplier_id,gate_id,gate_name,outcome,evidence_quote,page,mandatory) VALUES (?,?,?,?,?,?,?)",
                        (sid, gate["gate_id"], gate.get("name", gate["gate_id"]), gate.get("outcome", "unclear"), gate.get("evidence", ""), gate.get("page"), int(bool(gate.get("mandatory", True)))))
            conn.commit()

    def load_run(self, rfp_run_id: str) -> dict[str, Any]:
        with connect(self.db_path) if self.db_path else connect() as conn:
            run = conn.execute("SELECT * FROM rfp_runs WHERE rfp_run_id=?", (rfp_run_id,)).fetchone()
            if run is None:
                raise KeyError(rfp_run_id)
            results = [json.loads(row[0]) for row in conn.execute("SELECT result_json FROM supplier_results WHERE rfp_run_id=? ORDER BY final_rank", (rfp_run_id,))]
            return {**dict(run), "criteria": json.loads(run["criteria_snapshot_json"]), "warnings": json.loads(run["warnings_json"]), "reproducibility": json.loads(run["reproducibility_json"]), "suppliers": results}
