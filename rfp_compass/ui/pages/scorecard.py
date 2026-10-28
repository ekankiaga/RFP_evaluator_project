"""Supplier drill-down, evidence, risks, and human override controls."""

from __future__ import annotations

import streamlit as st
from html import escape

from ..charts import peer_heatmap, scorecard_comparison, strength_bar
from ..components import chip
from .common import current_run, save_override, score_for


def render() -> None:
    st.title("Supplier scorecard")
    run = current_run()
    if not run:
        st.info("Run an evaluation to open a detailed scorecard.")
        return
    names = [s["supplier_name"] for s in run["suppliers"]]
    selected_name = st.selectbox("Choose a supplier to review", names,
        format_func=lambda name: f"#{next(s['rank'] for s in run['suppliers'] if s['supplier_name'] == name)} · {name}",
        key="scorecard_supplier")
    supplier = next(s for s in run["suppliers"] if s["supplier_name"] == selected_name)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rank", f"#{supplier['rank']}")
    c2.metric("Absolute score", f"{supplier['absolute_score']:.2f} / 100")
    c3.metric("PPI", f"{supplier['ppi']:.2f}%")
    c4.metric("Experience", f"{supplier['experience_rating']:.1f} / 10")
    st.caption("Absolute score is the weighted score out of 100. PPI compares this supplier with the best score on each criterion in this run; 100% means peer-leading performance.")
    st.markdown(" ".join(chip(f"{gate.get('name', gate.get('gate_id'))}: {gate.get('outcome', 'unclear')}", "bad" if gate.get("outcome") in {"no", "failed"} else "warn" if gate.get("outcome") == "unclear" else "") for gate in supplier.get("gates", [])), unsafe_allow_html=True)
    others = [x for x in run["suppliers"] if x["supplier_name"] != selected_name]
    st.subheader("Criterion performance")
    st.caption("Bars show each score as a percentage of that criterion’s maximum. The peer average excludes the selected supplier.")
    st.plotly_chart(scorecard_comparison(supplier, others, run["criteria"]), use_container_width=True,
                    key=f"scorecard_radar_{run['rfp_run_id']}_{selected_name}")
    st.markdown("#### Peer criterion heatmap")
    st.caption("Rows are criteria and columns are suppliers. Green means closer to the criterion maximum; red means lower. Hover a cell for the exact percentage.")
    st.plotly_chart(peer_heatmap(run["suppliers"], run["criteria"]), use_container_width=True,
                    key=f"scorecard_heatmap_{run['rfp_run_id']}")
    strengths, gaps = [], []
    for criterion in run["criteria"]:
        result = score_for(supplier, criterion)
        if not result:
            continue
        pct = float(result.get("final_score", result["score"])) / float(result.get("max_score", 10))
        (strengths if pct >= .75 else gaps if pct < .55 else []).append(criterion["name"])
    a, b = st.columns(2)
    with a:
        st.markdown("#### Strengths")
        st.write(", ".join(strengths) if strengths else "No criterion has strong evidence yet.")
    with b:
        st.markdown("#### Weaknesses and risks")
        st.write(", ".join(gaps) if gaps else "No low-scoring criterion detected.")
    if supplier.get("risks"):
        for risk in supplier["risks"]:
            st.warning(risk)
    for criterion in run["criteria"]:
        item = score_for(supplier, criterion)
        if not item:
            continue
        key = str(criterion.get("criterion_id", criterion["name"]))
        score = float(item.get("final_score", item["score"]))
        metrics = supplier.get("benchmark_metrics", {}).get(key, {})
        delta = score - float(item.get("ai_score", item["score"]))
        with st.expander(f"{criterion['name']} · {score:g}/{item.get('max_score', 10)} · weight {criterion['weight']}%", expanded=False):
            bar_col, detail_col = st.columns([3, 2])
            bar_col.plotly_chart(strength_bar(score, float(metrics.get("benchmark", 0)), float(item.get("max_score", 10)), float(metrics.get("gap", 0))),
                use_container_width=True, config={"displayModeBar": False},
                key=f"scorecard_strength_{run['rfp_run_id']}_{selected_name}_{key}")
            bar_col.caption("Green bar = final score · amber marker = best peer score")
            bar_col.caption(f"AI score {item.get('ai_score', item['score']):g} · final {score:g} · delta {delta:+g}")
            detail_col.markdown(f"**Weight contribution:** {score / float(item.get('max_score',10)) * float(criterion['weight']):.2f} pts  \n**Benchmark:** {metrics.get('benchmark', 0):g}  \n**Gap:** {metrics.get('gap', 0):+g}  \n**Relative:** {metrics.get('relative_pct', 0):.1f}%")
            st.write(item.get("justification", "No justification supplied."))
            evidence = item.get("evidence", {})
            quote = evidence.get("quote", "") if isinstance(evidence, dict) else str(evidence)
            page = evidence.get("page") if isinstance(evidence, dict) else None
            if quote:
                st.markdown(f'<div class="rc-evidence">“{escape(str(quote))}” · page {page or "not recorded"}</div>', unsafe_allow_html=True)
            else:
                st.markdown(chip("Evidence missing", "warn"), unsafe_allow_html=True)
            if evidence and page:
                st.caption("View in document")
                source = next((p for p in supplier.get("document_pages", []) if p.get("page") == page), None)
                if source:
                    text = escape(str(source.get("text", "")))
                    safe_quote = escape(str(quote))
                    if safe_quote and safe_quote in text:
                        text = text.replace(safe_quote, f"<mark>{safe_quote}</mark>", 1)
                    st.markdown(f"<pre style='white-space:pre-wrap;background:#f5f7f5;padding:1rem;border-radius:10px'>{text}</pre>", unsafe_allow_html=True)
            if st.session_state.get("role") != "Viewer" and run.get("status") != "Finalized":
                if st.button("Re-evaluate this criterion with LLM", key=f"reevaluate_{supplier['supplier_name']}_{key}"):
                    _reevaluate_criterion(run, supplier, criterion, item)
            _override_form(run, supplier, item, key)
    _review_status(run, supplier)
    _comments(run, supplier)


def _override_form(run, supplier, item, key):
    view_only = st.session_state.get("role") == "Viewer" or run.get("status") == "Finalized"
    with st.form(f"override_{supplier['supplier_name']}_{key}"):
        st.markdown("**AI vs Human review**")
        score = st.number_input("Final score", min_value=0.0, max_value=float(item.get("max_score", 10)), value=float(item.get("final_score", item["score"])), step=.5, disabled=view_only)
        justification = st.text_area("Final justification", value=item.get("justification", ""), disabled=view_only)
        reason = st.text_input("Mandatory override reason", disabled=view_only)
        if st.form_submit_button("Save human override", disabled=view_only):
            try:
                save_override(run, supplier, item, score, justification, reason)
                st.success("Override saved. Benchmarks, PPI, gaps, and ranks were recomputed.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def _review_status(run, supplier):
    status_options = ["AI Evaluated", "Under Review", "Reviewed", "Approved", "Rejected"]
    col1, col2 = st.columns([2, 3])
    current = supplier.get("status", "AI Evaluated")
    locked = st.session_state.get("role") == "Viewer" or run.get("status") == "Finalized"
    choice = col1.selectbox("Supplier review status", status_options, index=status_options.index(current) if current in status_options else 0, disabled=locked)
    reason = col2.text_input("Status change reason", key=f"status_reason_{supplier['supplier_name']}", disabled=locked)
    if choice != current and choice == "Approved" and st.session_state.get("role") != "Approver":
        st.warning("Only an Approver can approve a supplier.")
    if choice != current and col1.button("Update status", key=f"status_save_{supplier['supplier_name']}", disabled=locked or (choice == "Approved" and st.session_state.get("role") != "Approver")):
        if not reason.strip():
            st.error("A reason is required for status changes.")
        else:
            from ...audit.audit_log import AuditLog
            supplier["status"] = choice
            from ...db import connect
            with connect() as conn:
                conn.execute("INSERT INTO review_status(supplier_id,status,updated_at,updated_by,reason) SELECT supplier_id,?,?,?,? FROM suppliers_in_run WHERE rfp_run_id=? AND supplier_name=? ON CONFLICT(supplier_id) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at,updated_by=excluded.updated_by,reason=excluded.reason",
                    (choice, __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(), st.session_state.get("actor", "analyst"), reason, run["rfp_run_id"], supplier["supplier_name"]))
            AuditLog().append(actor=st.session_state.get("actor", "analyst"), role=st.session_state.get("role", "Analyst"),
                event_type="supplier_status_changed", entity_type="supplier", entity_id=supplier["supplier_name"], rfp_run_id=run["rfp_run_id"],
                before={"status": current}, after={"status": choice}, reason=reason)
            st.rerun()


def _comments(run, supplier):
    st.markdown("#### Comments")
    comments = st.session_state.setdefault("comments", {}).setdefault(supplier["supplier_name"], [])
    for entry in comments:
        st.caption(f"{entry['actor']} · {entry['time']}")
        st.write(entry["body"])
    if st.session_state.get("role") != "Viewer":
        body = st.text_area("Add a review comment", key=f"comment_{supplier['supplier_name']}")
        if st.button("Post comment", key=f"post_comment_{supplier['supplier_name']}"):
            if body.strip():
                from datetime import datetime, timezone
                from ...audit.audit_log import AuditLog
                entry = {"actor": st.session_state.get("actor", "analyst"), "time": datetime.now(timezone.utc).isoformat(), "body": body}
                comments.append(entry)
                from ...db import connect
                with connect() as conn:
                    supplier_row = conn.execute("SELECT supplier_id FROM suppliers_in_run WHERE rfp_run_id=? AND supplier_name=?", (run["rfp_run_id"], supplier["supplier_name"])).fetchone()
                    conn.execute("INSERT INTO comments(rfp_run_id,supplier_id,actor,body,created_at) VALUES (?,?,?,?,?)",
                        (run["rfp_run_id"], supplier_row[0] if supplier_row else None, entry["actor"], body, entry["time"]))
                AuditLog().append(actor=entry["actor"], role=st.session_state.get("role", "Analyst"), event_type="comment_added", entity_type="supplier", entity_id=supplier["supplier_name"], rfp_run_id=run["rfp_run_id"], after={"comment": body})
                st.rerun()


def _reevaluate_criterion(run, supplier, criterion, item):
    from ...agents.evaluation_agent import EvaluationAgent
    from ...audit.audit_log import AuditLog
    from ...llm.provider_factory import create_provider
    from ...models import ConnectionConfig, ProviderKind
    from .common import recalculate_run
    if st.session_state.get("demo_mode"):
        config = ConnectionConfig(connection_id="demo", provider_id=ProviderKind.MOCK, model="mock-rfp-v1")
    else:
        config = st.session_state.get("evaluation_connection")
        connection_id = st.session_state.get("active_connection_id")
        health = st.session_state.get("connection_health", {}).get(connection_id) if connection_id else None
        if not config or not health or health.status != "passed":
            st.error("The evaluation connection must pass its test before re-evaluation.")
            return
    try:
        provider = create_provider(config)
        agent = EvaluationAgent(lambda system, user, schema, **opts: provider.generate_json(system, user, schema))
        pages = supplier.get("document_pages", [])
        payload, warnings = agent.evaluate(supplier_name=supplier["supplier_name"], criteria=[criterion], pages=pages)
        judgment = payload.criteria[0]
        before = {"ai_score": item.get("ai_score", item["score"]), "justification": item.get("justification"), "evidence": item.get("evidence")}
        item.setdefault("prior_versions", []).append(before)
        item["score"] = float(judgment.score)
        item["ai_score"] = float(judgment.score)
        item["final_score"] = float(judgment.score)
        item["justification"] = judgment.justification
        item["evidence"] = judgment.evidence.model_dump() if hasattr(judgment.evidence, "model_dump") else judgment.evidence
        item["confidence"] = judgment.confidence
        item.pop("override_reason", None)
        item.pop("overridden_by", None)
        item.pop("overridden_at", None)
        recalculate_run(run)
        AuditLog().append(actor=st.session_state.get("actor", "analyst"), role=st.session_state.get("role", "Analyst"),
            event_type="criterion_reevaluated", entity_type="criterion_score", entity_id=f"{supplier['supplier_name']}:{criterion['name']}",
            rfp_run_id=run["rfp_run_id"], before=before, after={"ai_score": item["ai_score"], "confidence": item["confidence"], "warnings": warnings}, reason="Analyst requested new AI evaluation")
        st.success("Criterion re-evaluated. Previous AI result is retained in version history and rankings were recomputed.")
        st.rerun()
    except Exception as exc:
        from ...llm.key_vault import redact
        st.error(f"Re-evaluation failed: {redact(exc)}")
