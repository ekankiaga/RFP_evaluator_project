"""Shared review helpers for run state and deterministic override recomputation."""

from __future__ import annotations

from typing import Any

import streamlit as st

from ...audit.audit_log import AuditLog
from ...tools.ranking_tool import RankingTool
from ...tools.scoring_tool import absolute_weighted_score, benchmark_metrics, peer_performance_index
from ...db import connect


def current_run() -> dict[str, Any] | None:
    return st.session_state.get("current_run")


def recalculate_run(run: dict[str, Any]) -> None:
    criteria = run["criteria"]
    suppliers = run["suppliers"]
    scores = {s["supplier_name"]: [{**item, "score": float(item.get("final_score", item["score"]))} for item in s["scores"]] for s in suppliers}
    benchmarks = benchmark_metrics(scores, criteria)
    for supplier in suppliers:
        name = supplier["supplier_name"]
        supplier["absolute_score"] = absolute_weighted_score(scores[name], criteria)
        supplier["benchmark_metrics"] = benchmarks[name]
        supplier["ppi"] = peer_performance_index(benchmarks[name], criteria)
        for item in supplier["scores"]:
            item.update(benchmarks[name].get(str(item["criterion_id"]), {}))
    old_ranks = {s["supplier_name"]: int(s.get("rank", 0)) for s in suppliers}
    ranked = RankingTool().rank(suppliers)
    for item in ranked:
        item["rank_movement"] = old_ranks.get(item["supplier_name"], item["rank"]) - item["rank"]
    run["suppliers"] = ranked
    with connect() as conn:
        for supplier in ranked:
            row = conn.execute("SELECT supplier_id FROM suppliers_in_run WHERE rfp_run_id=? AND supplier_name=?", (run["rfp_run_id"], supplier["supplier_name"])).fetchone()
            if not row:
                continue
            supplier_id = row[0]
            for item in supplier["scores"]:
                conn.execute("UPDATE criterion_scores SET final_score=?,ai_score=?,justification=?,override_reason=?,overridden_by=?,overridden_at=?,prior_versions_json=? WHERE supplier_id=? AND criterion_key=?",
                    (item.get("final_score", item["score"]), item.get("ai_score", item["score"]), item.get("justification", ""), item.get("override_reason"), item.get("overridden_by"), item.get("overridden_at"), __import__("json").dumps(item.get("prior_versions", []), ensure_ascii=False), supplier_id, str(item["criterion_id"])))
            conn.execute("UPDATE suppliers_in_run SET rank=?,status=? WHERE supplier_id=?", (supplier["rank"], supplier.get("status", "AI Evaluated"), supplier_id))
            conn.execute("UPDATE supplier_results SET absolute_score=?,ppi=?,final_rank=?,result_json=?,tie_break_explanation=? WHERE rfp_run_id=? AND supplier_id=?",
                (supplier["absolute_score"], supplier["ppi"], supplier["rank"], __import__("json").dumps(supplier, ensure_ascii=False, sort_keys=True, default=str), supplier.get("tie_break_explanation", ""), run["rfp_run_id"], supplier_id))


def save_override(run: dict[str, Any], supplier: dict[str, Any], item: dict[str, Any],
                  new_score: float, justification: str, reason: str) -> None:
    if not reason.strip():
        raise ValueError("A reason is required for every override.")
    before = {"final_score": item.get("final_score", item["score"]), "justification": item.get("justification", "")}
    after = {"final_score": new_score, "justification": justification, "overridden_by": st.session_state.get("actor", "analyst"), "reason": reason}
    item.setdefault("ai_score", item["score"])
    item["final_score"] = float(new_score)
    item["override_reason"] = reason
    item["overridden_by"] = st.session_state.get("actor", "analyst")
    item["overridden_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    item["justification"] = justification
    with connect() as conn:
        row = conn.execute("SELECT supplier_id FROM suppliers_in_run WHERE rfp_run_id=? AND supplier_name=?", (run["rfp_run_id"], supplier["supplier_name"])).fetchone()
        if row:
            conn.execute("UPDATE criterion_scores SET final_score=?,ai_score=?,justification=?,override_reason=?,overridden_by=?,overridden_at=?,prior_versions_json=? WHERE supplier_id=? AND criterion_key=?",
                (float(new_score), item["ai_score"], justification, reason, item["overridden_by"], item["overridden_at"], __import__("json").dumps(item.get("prior_versions", []), ensure_ascii=False), row[0], str(item["criterion_id"])))
    st.session_state.setdefault("override_history", []).append({"supplier": supplier["supplier_name"], "criterion": item.get("criterion_name"), "before": before, "after": after, "reason": reason})
    recalculate_run(run)
    AuditLog().append(actor=st.session_state.get("actor", "analyst"), role=st.session_state.get("role", "Analyst"),
        event_type="score_overridden", entity_type="criterion_score", entity_id=f"{supplier['supplier_name']}:{item.get('criterion_id')}",
        rfp_run_id=run["rfp_run_id"], before=before, after=after, reason=reason)


def score_for(supplier: dict[str, Any], criterion: dict[str, Any]) -> dict[str, Any] | None:
    key = str(criterion.get("criterion_id", criterion["name"]))
    return next((x for x in supplier.get("scores", []) if str(x["criterion_id"]) == key), None)
