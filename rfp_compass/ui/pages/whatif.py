"""Weight sensitivity and Monte Carlo robustness controls."""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from ...tools.what_if_tool import WhatIfEngine
from .common import current_run


def render() -> None:
    st.title("What-if scenarios")
    run = current_run()
    if not run:
        st.info("Evaluate a run before exploring scenarios.")
        return
    criteria = run["criteria"]
    if "whatif_weights" not in st.session_state or st.session_state.get("whatif_run_id") != run["rfp_run_id"]:
        st.session_state["whatif_weights"] = {str(c.get("criterion_id", c["name"])): float(c["weight"]) for c in criteria}
        st.session_state["whatif_run_id"] = run["rfp_run_id"]
    st.caption("Explore how changing criterion importance could change the ranking. Scenario results do not change the official run.")
    if st.button("Reset weights to baseline"):
        st.session_state["whatif_weights"] = {str(c.get("criterion_id", c["name"])): float(c["weight"]) for c in criteria}
        st.rerun()
    st.subheader("1 · Adjust criterion weights")
    st.caption("Weights are normalized to 100% for each scenario, so you can focus on relative importance.")
    cols = st.columns(2)
    for index, criterion in enumerate(criteria):
        key = str(criterion.get("criterion_id", criterion["name"]))
        with cols[index % 2]:
            st.session_state["whatif_weights"][key] = st.slider(f"{criterion['name']} · weight %", 0.0, 100.0,
                float(st.session_state["whatif_weights"][key]), step=1.0, key=f"whatif_{key}")
    weights = st.session_state["whatif_weights"]
    st.caption(f"Current slider total: {sum(weights.values()):.1f}%. The scenario normalizes the requested weights to 100% before calculation.")
    engine = WhatIfEngine()
    scenario = engine.evaluate(run["suppliers"], criteria, weights)
    a, b, c = st.columns(3)
    a.metric("Scenario winner", scenario["winner"] or "—")
    b.metric("Scenario top score", f"{scenario['ranked_suppliers'][0]['absolute_score']:.2f}" if scenario["ranked_suppliers"] else "—")
    c.metric("Official run", "Unchanged")
    for supplier in scenario["ranked_suppliers"]:
        delta = supplier["rank_movement"]
        st.markdown(f"**#{supplier['rank']} · {supplier['supplier_name']}** · PPI {supplier['ppi']:.2f}% · movement {delta:+d}")
    st.subheader("2 · Test ranking stability")
    st.caption("Monte Carlo varies each criterion weight within the range below, renormalizes to 100%, and counts which supplier ranks first.")
    simulations = st.slider("Number of simulated weight sets", 50, 1000, 300, step=50)
    perturbation = st.slider("Maximum change per criterion (percentage points)", 1.0, 30.0, 10.0, step=1.0)
    robustness = engine.sensitivity(run["suppliers"], criteria, perturbation, simulations, seed=42)
    st.metric("Baseline winner remains first", f"{robustness['winner_stability_pct']:.1f}%", f"Across {robustness['simulations']} simulated weight sets")
    counts = robustness["winner_counts"]
    figure = go.Figure(go.Bar(x=list(counts.values()), y=list(counts.keys()), orientation="h",
        marker_color="#39836f", text=list(counts.values()), textposition="outside",
        hovertemplate="%{y}<br>Ranked first in %{x} simulations<extra></extra>"))
    figure.update_layout(height=max(220, len(counts) * 52), margin={"l": 12, "r": 36, "t": 12, "b": 40},
        xaxis={"title": "Number of simulations", "rangemode": "tozero"},
        yaxis={"title": "Supplier", "automargin": True, "autorange": "reversed"}, showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    figure.update_xaxes(gridcolor="#e6ece9", zeroline=False)
    st.plotly_chart(figure, use_container_width=True, key=f"whatif_winners_{run['rfp_run_id']}")
    name = st.text_input("Save scenario name", value="Weight sensitivity scenario")
    if st.button("Save as non-official scenario", disabled=st.session_state.get("role") == "Viewer"):
        scenario_id = engine.save_scenario(__import__("rfp_compass.config", fromlist=["DB_PATH"]).DB_PATH, run["rfp_run_id"], name, scenario)
        st.success(f"Saved non-official scenario `{scenario_id}`.")
