"""RFP Compass Streamlit application entry point."""

from __future__ import annotations

import streamlit as st

from rfp_compass.config import APP_NAME, APP_VERSION
from rfp_compass.db import migrate
from scripts.seed_db import seed
from rfp_compass.ui.theme import apply_theme
from rfp_compass.ui.components import header_status
from rfp_compass.ui.pages import audit, compare, evaluate, export, insights, leaderboard, llm_connections, scorecard, setup, suppliers, whatif
from rfp_compass.llm.key_vault import install_redaction_filter


PAGES = {
    "1 · Setup & criteria": setup.render,
    "2 · Supplier proposals": suppliers.render,
    "3 · Evaluate proposals": evaluate.render,
    "4 · Leaderboard": leaderboard.render,
    "5 · Scorecard & evidence": scorecard.render,
    "6 · Compare suppliers": compare.render,
    "7 · What-if scenarios": whatif.render,
    "8 · Insights": insights.render,
    "9 · Audit trail": audit.render,
    "10 · Export & run details": export.render,
    "11 · Provider connections": llm_connections.render,
}


def main() -> None:
    st.set_page_config(page_title=APP_NAME, page_icon="🧭", layout="wide", initial_sidebar_state="expanded")
    apply_theme()
    install_redaction_filter()
    migrate()
    seed()
    st.session_state.setdefault("actor", "analyst")
    st.session_state.setdefault("role", "Analyst")
    st.session_state.setdefault("demo_mode", True)
    st.session_state.setdefault("domain_id", "it_software_saas")
    st.session_state.setdefault("merge_mode", "Generic + Domain pack")
    if "criteria" not in st.session_state:
        from rfp_compass.tools.criteria_tool import CriteriaTool
        st.session_state["criteria"] = CriteriaTool().resolve_domain(st.session_state["domain_id"])["resolved_criteria"]
        st.session_state["criteria_domain_id"] = st.session_state["domain_id"]
    with st.sidebar:
        st.markdown("# 🧭 RFP Compass")
        st.caption(f"Procurement evaluation workbench · v{APP_VERSION}")
        st.markdown("**Run and review**")
        page_name = st.radio("Workspace steps", list(PAGES), label_visibility="collapsed", key="workspace_page")
        criteria = st.session_state.get("criteria", [])
        weights_total = sum(float(item.get("weight", 0)) for item in criteria if item.get("is_active", True))
        criteria_ready = bool(criteria) and abs(weights_total - 100) < 1e-6
        supplier_count = len(st.session_state.get("supplier_inputs", []))
        has_run = bool(st.session_state.get("current_run"))
        st.caption("Progress")
        st.caption(f"{sum((criteria_ready, supplier_count > 0, has_run))} of 3 workflow steps complete")
        st.markdown(f"{'✓' if criteria_ready else '○'}  Criteria ready · {weights_total:.0f}%")
        st.markdown(f"{'✓' if supplier_count else '○'}  Proposals ready · {supplier_count}")
        st.markdown(f"{'✓' if has_run else '○'}  Evaluation complete")
        st.divider()
        st.selectbox("Role", ["Analyst", "Reviewer", "Approver", "Viewer"], key="role")
        st.text_input("Actor name", key="actor")
        st.toggle("Offline demo mode", key="demo_mode", help="Uses deterministic MockLLM locally. No API key or external provider is required.")
        if st.button("Reset this session", help="Clears uploaded proposals, the active run, and provider connections for this session."):
            from rfp_compass.ui.pages.export import _clear_connection_secrets
            _clear_connection_secrets()
            for key in ("current_run", "supplier_inputs", "supplier_metadata", "criteria", "criteria_set_id", "comments", "run_insights"):
                st.session_state.pop(key, None)
            st.success("Session workspace reset; provider keys cleared.")
            st.rerun()
        st.caption("Proposal data may contain sensitive information. Use the privacy controls before evaluation.")
    header_status()
    PAGES[page_name]()


if __name__ == "__main__":
    main()
