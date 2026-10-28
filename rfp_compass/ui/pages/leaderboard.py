"""Readable ranked supplier dashboard with compliance and evidence review."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from ..components import chip
from .common import current_run


def render() -> None:
    st.title("Leaderboard")
    run = current_run()
    if not run:
        st.info("No evaluation yet. Add proposal PDFs under Suppliers, then choose Evaluate → Run evaluation.")
        return

    suppliers = sorted(run.get("suppliers", []), key=lambda item: int(item.get("rank", 9999)))
    if not suppliers:
        st.warning("This run has no evaluated suppliers.")
        return
    compliant_count = sum(bool(item.get("compliant", True)) for item in suppliers)
    review_count = sum(_needs_review(item) for item in suppliers)
    mean_score = sum(float(item.get("absolute_score", 0)) for item in suppliers) / len(suppliers)
    st.caption(f"Run {run.get('rfp_run_id', '—')} · {run.get('domain_id', 'criteria-based evaluation')} · sorted by compliance policy, peer performance, then tie-break rules")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Suppliers", len(suppliers))
    m2.metric("Compliant", f"{compliant_count} / {len(suppliers)}")
    m3.metric("Average absolute score", f"{mean_score:.1f} / 100")
    m4.metric("Needs review", review_count)

    show_compliant_only = st.toggle("Show compliant suppliers only", value=False)
    min_ppi, max_ppi = st.slider("Filter by peer performance index", 0.0, 100.0, (0.0, 100.0), step=1.0)
    visible = [item for item in suppliers
               if (not show_compliant_only or item.get("compliant", True))
               and min_ppi <= float(item.get("ppi", 0)) <= max_ppi]
    if not visible:
        st.info("No suppliers match these filters. Adjust the PPI range or compliance filter.")
        return

    st.subheader("Absolute score by rank")
    st.caption("Absolute score is the weighted score out of 100. Teal bars passed mandatory gates; red bars failed a mandatory gate. Hover for rank and PPI.")
    st.plotly_chart(_ranking_chart(visible, run.get("rfp_run_id", "active")),
                    use_container_width=True, config={"displayModeBar": False},
                    key=f"leaderboard_chart_{run.get('rfp_run_id', 'active')}")

    if visible[0].get("rank") == suppliers[0].get("rank"):
        st.subheader("Leading suppliers")
        podium = visible[:min(3, len(visible))]
        columns = st.columns(len(podium))
        medals = ["🥇", "🥈", "🥉"]
        for index, (column, supplier) in enumerate(zip(columns, podium)):
            with column:
                with st.container(border=True):
                    st.caption(f"{medals[index]}  RANK #{supplier.get('rank', index + 1)}")
                    st.markdown(f"### {supplier.get('supplier_name', 'Supplier')}")
                    st.metric("Absolute score", f"{float(supplier.get('absolute_score', 0)):.1f} / 100")
                    st.caption(f"Peer performance index: **{float(supplier.get('ppi', 0)):.1f}%**")
                    st.markdown(chip("Compliant" if supplier.get("compliant", True) else "Gate failed",
                                     "" if supplier.get("compliant", True) else "bad"), unsafe_allow_html=True)

    st.subheader("Ranked suppliers")
    for supplier in visible:
        _supplier_row(supplier)

    with st.expander("How ranking and tie-breaks work"):
        st.write("Mandatory-gate compliant suppliers rank first, followed by higher PPI, earlier submission date, higher experience rating, and supplier name alphabetically.")
        explanations = [item for item in suppliers if item.get("tie_break_explanation")]
        if explanations:
            for supplier in explanations:
                st.write(f"**{supplier['supplier_name']}** · {supplier['tie_break_explanation']}")
        else:
            st.caption("No supplier tie-breaks were needed in this run.")


def _supplier_row(supplier: dict) -> None:
    compliant = bool(supplier.get("compliant", True))
    status_label = "Compliant" if compliant else "Mandatory gate failed"
    with st.container(border=True):
        rank_col, name_col, score_col, ppi_col, status_col = st.columns([0.8, 3.1, 1.5, 1.5, 1.7])
        rank_col.markdown(f"## #{supplier.get('rank', '—')}")
        name_col.markdown(f"### {supplier.get('supplier_name', 'Supplier')}")
        name_col.caption(f"Submitted {supplier.get('submission_date', 'date not recorded')} · experience {float(supplier.get('experience_rating', 0)):g}/10")
        score_col.metric("Absolute score", f"{float(supplier.get('absolute_score', 0)):.1f}")
        ppi_col.metric("Peer index", f"{float(supplier.get('ppi', 0)):.1f}%")
        status_col.markdown(chip(status_label, "" if compliant else "bad"), unsafe_allow_html=True)
        max_score = max(float(supplier.get("absolute_score", 0)), 0)
        st.progress(min(1.0, max_score / 100), text=f"Absolute weighted score · {max_score:.1f} / 100")

        with st.expander("Criteria, gates, and review details"):
            scores = supplier.get("scores", [])
            if scores:
                st.dataframe([{
                    "Criterion": item.get("criterion_name", item.get("criterion_id", "")),
                    "Score": f"{float(item.get('final_score', item.get('score', 0))):g} / {float(item.get('max_score', 10)):g}",
                    "Weight": f"{float(item.get('weight', 0)):g}%",
                    "Confidence": item.get("confidence", "—"),
                } for item in scores], hide_index=True, use_container_width=True)
            gates = supplier.get("gates", [])
            if gates:
                st.markdown("**Mandatory gates**")
                for gate in gates:
                    outcome = str(gate.get("outcome", "unclear")).capitalize()
                    st.write(f"{gate.get('name', gate.get('gate_id', 'Gate'))}: **{outcome}**")
                    if gate.get("evidence"):
                        st.caption(f"Evidence: {gate['evidence']}")
            for warning in supplier.get("warnings", []):
                st.warning(warning)
            if _needs_review(supplier) and not supplier.get("warnings"):
                st.info("Review low-confidence or missing criterion evidence in the Scorecard.")
            if supplier.get("tie_break_explanation"):
                st.caption(supplier["tie_break_explanation"])


def _needs_review(supplier: dict) -> bool:
    for item in supplier.get("scores", []):
        evidence = item.get("evidence") or {}
        quote = evidence.get("quote", "") if isinstance(evidence, dict) else str(evidence)
        if str(item.get("confidence", "")).casefold() == "low" or not quote:
            return True
    if any(str(gate.get("outcome", "")).casefold() == "unclear" for gate in supplier.get("gates", [])):
        return True
    return bool(supplier.get("warnings"))


def _ranking_chart(suppliers: list[dict], run_id: str) -> go.Figure:
    ordered = list(reversed(suppliers))
    names = [str(item.get("supplier_name", "Supplier")) for item in ordered]
    scores = [float(item.get("absolute_score", 0)) for item in ordered]
    ppi = [float(item.get("ppi", 0)) for item in ordered]
    ranks = [item.get("rank", "—") for item in ordered]
    colors = ["#39836f" if item.get("compliant", True) else "#bd625d" for item in ordered]
    figure = go.Figure(go.Bar(x=scores, y=names, orientation="h", marker={"color": colors, "line": {"width": 0}},
        text=[f"{score:.1f}" for score in scores], textposition="outside",
        customdata=list(zip(ranks, ppi)),
        hovertemplate="Rank #%{customdata[0]}<br>%{y}<br>Absolute score: %{x:.1f}/100<br>PPI: %{customdata[1]:.1f}%<extra></extra>"))
    figure.update_layout(height=max(230, len(ordered) * 58), margin={"l": 12, "r": 48, "t": 12, "b": 30},
        xaxis={"range": [0, 108], "title": "Absolute score (0–100)"}, yaxis={"title": "", "automargin": True},
        showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#243b36"}, bargap=.38)
    figure.update_xaxes(gridcolor="#e6ece9", zeroline=False)
    figure.update_yaxes(showgrid=False)
    return figure
