"""Privacy consent, cost cap, and agent workflow execution."""

from __future__ import annotations

import os

import streamlit as st

from ...audit.audit_log import AuditLog
from ...llm.provider_factory import create_provider
from ...models import ConnectionConfig, ProviderKind
from ...orchestrator import Orchestrator
from ...tools.document_tool import DocumentTool
from ...llm.pricing import estimate_cost
from ...llm.key_vault import redact


def render() -> None:
    st.title("Evaluate proposals")
    st.caption("Step 3 of 3 · Check the evaluation mode and estimate, authorize processing, then start the run.")
    suppliers = st.session_state.get("supplier_inputs", [])
    criteria = st.session_state.get("criteria", [])
    domain_id = st.session_state.get("domain_id", "custom_generic")
    st.write(f"**{len(suppliers)} suppliers** · **{len(criteria)} scoring criteria** · domain **{domain_id.replace('_', ' ').title()}**")
    if not suppliers:
        st.warning("No proposal PDFs are ready. Open **Supplier proposals** and upload at least one valid PDF.")
        return
    if not criteria:
        st.warning("No active scoring criteria. Open **Setup** and choose a domain with criteria totaling 100%.")
        return
    demo = bool(st.session_state.get("demo_mode", True))
    config = st.session_state.get("evaluation_connection")
    active_id = st.session_state.get("active_connection_id")
    health = st.session_state.get("connection_health", {}).get(active_id) if active_id else None
    allowed = demo or bool(config and health and health.status == "passed")
    if demo:
        st.success("Demo mode is active. MockLLM runs offline, requires no API key, and does not send proposal text to an external provider.")
        config = ConnectionConfig(connection_id="demo", provider_id=ProviderKind.MOCK, model="mock-rfp-v1")
    elif not allowed:
        st.error("Evaluate is unavailable until the active connection passes its test in this session. Open LLM Connections and test it.")
    if not demo:
        st.warning("Proposal text will be sent to the selected provider. Review its data terms and remove unnecessary personal or confidential information before proceeding.")
    consent_label = ("I confirm these proposal files are authorized for processing." if demo else
                     "I understand proposal text will be sent to the selected provider and authorize processing.")
    consent_identity = f"{config.provider_id.value}_{config.model}" if config else "unconfigured"
    consent = st.checkbox(consent_label, key=f"privacy_consent_{consent_identity}")
    consent_scope = f"privacy_consent_logged_{consent_identity}"
    if consent and not st.session_state.get(consent_scope):
        AuditLog().append(actor=st.session_state.get("actor", "analyst"), role=st.session_state.get("role", "Analyst"),
            event_type="privacy_consent_given", entity_type="session", entity_id="supplier-document-processing",
            after={"provider": config.provider_id.value if config else "unknown"})
        st.session_state[consent_scope] = True
    cap = st.number_input("Maximum API spend for this run (USD)", min_value=0.0, value=10.0, step=1.0,
        help="If the estimated provider charge exceeds this amount, evaluation stops before any model calls.", disabled=demo)
    model_name = config.model if config else ""
    estimated_input = sum(len(DocumentTool().extract(item["pdf"]).text) // 4 + len(criteria) * 450 for item in suppliers)
    estimated_output = len(suppliers) * len(criteria) * 140
    estimate = estimate_cost(model_name, estimated_input, estimated_output) if not demo else 0.0
    if demo:
        st.info("Estimated API cost: **$0.00** · offline demo mode makes no provider calls.")
    elif estimate is None:
        st.warning("No price is configured for this model, so the provider cost estimate is unavailable. Check pricing before running.")
    else:
        st.info(f"Estimated provider cost: **${estimate:.4f}** · approximate, based on extracted document length and selected model pricing.")
    role = st.session_state.get("role", "Analyst")
    can_evaluate = role != "Viewer" and allowed and consent and bool(criteria)
    if st.button("Run evaluation", type="primary", disabled=not can_evaluate):
        try:
            provider = create_provider(config)
            fallback_id = st.session_state.get("fallback_connection_id")
            fallback_config = st.session_state.get("saved_connections", {}).get(fallback_id) if fallback_id else None
            fallback_provider = create_provider(fallback_config) if fallback_config else None
            with st.status("Running RFP Compass workflow…", expanded=True) as status:
                st.write("✓ Reload active criteria and snapshot this evaluation")
                st.write("✓ Extract page-aware PDF text")
                st.write("◌ Evaluate with evidence-grounded JSON")
                engine = Orchestrator(provider, max_workers=3, fallback_provider=fallback_provider)
                result = engine.evaluate(suppliers, criteria=criteria, domain_id=st.session_state.get("domain_id", "custom_generic"),
                    criteria_set_id=st.session_state.get("criteria_set_id"), budget_cap_usd=float(cap))
                st.session_state["current_run"] = result
                st.session_state.pop("run_insights", None)
                for step in result["steps"]:
                    st.write(f"{'✓' if step['status'] == 'complete' else '•'} **{step['name']}** · {step['message']}")
                status.update(label="Evaluation complete", state="complete", expanded=False)
            st.success(f"Run `{result['rfp_run_id']}` is ready for review.")
            st.caption("Next: open **Leaderboard** to review the ranking, then **Scorecard** to validate evidence and gates.")
        except Exception as exc:
            st.error(f"Evaluation did not complete: {redact(exc)}")
            with st.expander("Technical details", expanded=False):
                st.code(redact(exc))
    run = st.session_state.get("current_run")
    if run:
        st.caption(f"Current run: `{run['rfp_run_id']}` · {len(run['suppliers'])} evaluated suppliers")
        for warning in run.get("warnings", []):
            st.warning(warning)
