"""Executive insights, clarification questions, and negotiation leverage."""

from __future__ import annotations

import streamlit as st

from ...llm.provider_factory import create_provider
from ...models import ProviderKind
from ...tools.insights_tool import InsightsTool
from .common import current_run


def render() -> None:
    st.title("Executive insights")
    run = current_run()
    if not run:
        st.info("Evaluate suppliers to generate run insights.")
        return
    st.caption("These deterministic summaries are calculated from the scores and evidence in this run. Optional AI narrative is labeled separately and should be reviewed before use.")
    connection = st.session_state.get("narrative_insights_connection_id")
    config = st.session_state.get("saved_connections", {}).get(connection) if connection else None
    health = st.session_state.get("connection_health", {}).get(connection) if connection else None
    provider = create_provider(config) if config and health and health.status == "passed" else None
    if st.button("Refresh insights" + (" + optional AI narrative" if provider else "")):
        try:
            st.session_state["run_insights"] = InsightsTool().summarize(run["suppliers"], run["criteria"], provider)
        except Exception as exc:
            from ...llm.key_vault import redact
            st.error(f"Insights generation failed: {redact(exc)}")
    insights = st.session_state.get("run_insights") or InsightsTool().summarize(run["suppliers"], run["criteria"])
    leader = insights.get("leader")
    st.markdown("### Executive summary")
    st.write(f"**{leader or 'No leader'}** currently leads. {insights['executive_summary']}")
    if insights.get("ai_narrative"):
        st.info(f"**{insights['ai_narrative']['label']}** · {insights['ai_narrative']['text']}")
    st.markdown("### Cross-supplier risks")
    if insights["top_risks"]:
        for risk in insights["top_risks"]:
            st.warning(risk)
    else:
        st.success("No low-score criterion risks were identified by the deterministic rules.")
    st.markdown("### Clarification questions")
    generated = insights.get("ai_clarification_questions", {})
    if generated:
        st.caption("AI-generated questions · review and edit before using them.")
    edited_questions = st.session_state.setdefault("edited_questions", {})
    for supplier, questions in insights["clarification_questions"].items():
        with st.expander(supplier):
            proposed = generated.get(supplier, questions) if isinstance(generated, dict) else questions
            edited_questions[supplier] = st.text_area("Questions", value="\n".join(proposed) if isinstance(proposed, list) else str(proposed), key=f"questions_{supplier}", disabled=st.session_state.get("role") == "Viewer")
    st.markdown("### Negotiation leverage")
    for supplier, levers in insights["negotiation_leverage"].items():
        if levers:
            st.markdown(f"**{supplier}**")
            for lever in levers:
                st.write(f"• {lever}")
    if not provider:
        st.caption("Assign and test a Narrative/insights connection on the LLM Connections page to generate optional AI narrative and questions.")
