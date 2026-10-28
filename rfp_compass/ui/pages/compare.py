"""Visual supplier comparison workspace."""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from ..charts import score_contribution_chart, PALETTE
from .common import current_run


def render() -> None:
    st.title("Compare suppliers")
    run = current_run()
    if not run:
        st.info("Evaluate proposals before opening comparison.")
        return
    names = [s["supplier_name"] for s in run["suppliers"]]
    selected = st.multiselect("Choose 2–4 suppliers to compare", names, default=names[:min(3, len(names))], max_selections=4,
        format_func=lambda name: f"#{next(s['rank'] for s in run['suppliers'] if s['supplier_name'] == name)} · {name}")
    suppliers = [s for s in run["suppliers"] if s["supplier_name"] in selected]
    if len(suppliers) < 2:
        st.info("Select at least two suppliers.")
        return
    st.subheader("Scores by criterion")
    st.caption("Horizontal bars compare each supplier’s score against the same criterion. Hover a bar for its exact score; use the legend to identify suppliers.")
    grouped = go.Figure()
    for index, supplier in enumerate(suppliers):
        scores = {str(x["criterion_id"]): float(x.get("final_score", x["score"])) for x in supplier["scores"]}
        values = [scores.get(str(c.get("criterion_id", c["name"])), 0) for c in run["criteria"]]
        grouped.add_trace(go.Bar(name=supplier["supplier_name"], y=[c["name"] for c in run["criteria"]],
            x=values, orientation="h", marker_color=PALETTE[index % len(PALETTE)],
            hovertemplate=f"{supplier['supplier_name']}<br>%{{y}}<br>Score: %{{x:g}}<extra></extra>"))
    max_score = max((float(c.get("max_score", 10)) for c in run["criteria"]), default=10)
    grouped.update_layout(barmode="group", height=max(340, len(run["criteria"]) * 48),
        margin={"l": 12, "r": 18, "t": 15, "b": 45}, xaxis={"title": f"Criterion score (maximum {max_score:g})", "range": [0, max_score * 1.12]},
        yaxis={"title": "", "automargin": True, "autorange": "reversed"}, legend={"orientation": "h", "y": 1.08, "x": 0},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    grouped.update_xaxes(gridcolor="#e6ece9", zeroline=False)
    grouped.update_yaxes(showgrid=False)
    st.plotly_chart(grouped, use_container_width=True, key=f"compare_grouped_{run['rfp_run_id']}")
    st.subheader("Where each supplier wins")
    wins: dict[str, list[str]] = {s["supplier_name"]: [] for s in suppliers}
    for criterion in run["criteria"]:
        key = str(criterion.get("criterion_id", criterion["name"]))
        scored = [(s["supplier_name"], next((float(x.get("final_score", x["score"])) for x in s["scores"] if str(x["criterion_id"]) == key), 0.0)) for s in suppliers]
        high = max(value for _, value in scored)
        winners = [name for name, value in scored if value == high]
        for name in winners:
            wins[name].append(criterion["name"])
    st.dataframe([{"Supplier": supplier["supplier_name"], "Criteria with top score": ", ".join(wins[supplier["supplier_name"]]) or "No criterion lead"}
                  for supplier in suppliers], hide_index=True, use_container_width=True)
    st.subheader("What makes up the total score")
    st.caption("Each bar shows points added by one criterion: (reviewed score ÷ criterion maximum) × criterion weight. Bar labels are rounded to two decimals and reconcile to the total shown below.")
    selected_for_contributions = st.selectbox("Supplier contributions", [s["supplier_name"] for s in suppliers], key="contribution_supplier")
    contribution_supplier = next(s for s in suppliers if s["supplier_name"] == selected_for_contributions)
    st.metric("Absolute score", f"{float(contribution_supplier['absolute_score']):.2f} / 100")
    st.plotly_chart(score_contribution_chart(contribution_supplier, run["criteria"]), use_container_width=True,
                    key=f"compare_contributions_{run['rfp_run_id']}_{selected_for_contributions}")
    prices = [(s["supplier_name"], s.get("price_normalized")) for s in suppliers if s.get("price_normalized") is not None]
    st.subheader("Price / value")
    if prices:
        st.caption("Each point is a supplier. Hover for the name, normalized price, and absolute score.")
        fig = go.Figure()
        for index, (supplier_name, price) in enumerate(prices):
            absolute = next(s["absolute_score"] for s in suppliers if s["supplier_name"] == supplier_name)
            fig.add_trace(go.Scatter(x=[price], y=[absolute], mode="markers", name=supplier_name,
                marker={"size": 13, "color": PALETTE[index % len(PALETTE)]},
                hovertemplate=f"{supplier_name}<br>Normalized price: %{{x:g}}<br>Absolute score: %{{y:.1f}}/100<extra></extra>"))
        fig.update_layout(height=400, margin={"l": 20, "r": 20, "t": 20, "b": 50},
            xaxis_title="Normalized price", yaxis_title="Absolute score (0–100)",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True, key=f"compare_price_{run['rfp_run_id']}")
    else:
        st.caption("Price data was not extracted for this run. Price/value scatter will be available when pricing extraction is enabled.")
