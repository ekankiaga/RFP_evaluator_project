"""Plotly chart helpers for scores and comparisons."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from ..tools.scoring_tool import criterion_weighted_contribution

PALETTE = ["#1f6b64", "#d08d38", "#6b82a8", "#b55a56", "#71966f", "#8d6da8"]


def radar_chart(supplier: dict[str, Any], peers: list[dict[str, Any]], criteria: list[dict[str, Any]]) -> go.Figure:
    names = [c["name"] for c in criteria]
    key_by_name = {c["name"]: str(c.get("criterion_id", c["name"])) for c in criteria}
    def values(row):
        scores = {str(x["criterion_id"]): float(x.get("final_score", x["score"])) for x in row["scores"]}
        return [scores.get(key_by_name[n], 0) for n in names]
    fig = go.Figure()
    for i, row in enumerate([supplier]):
        fig.add_trace(go.Scatterpolar(r=values(row), theta=names, fill="toself", name=row["supplier_name"], line_color=PALETTE[i]))
    benchmark = supplier.get("benchmark_metrics", {})
    if benchmark:
        fig.add_trace(go.Scatterpolar(r=[benchmark.get(key_by_name[name], {}).get("benchmark", 0) for name in names],
            theta=names, name="Peer benchmark", line={"color": "#d08d38", "dash": "dash"}))
    if peers:
        peer_mean = [sum(values(p)[i] for p in peers) / len(peers) for i in range(len(names))]
        fig.add_trace(go.Scatterpolar(r=peer_mean, theta=names, name="Peer average", line={"color": "#83938e", "dash": "dot"}))
    fig.update_layout(polar={"radialaxis": {"visible": True, "range": [0, max(float(c.get("max_score", 10)) for c in criteria)]}},
                      showlegend=True, height=390, margin={"l": 30, "r": 30, "t": 25, "b": 20},
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


def scorecard_comparison(supplier: dict[str, Any], peers: list[dict[str, Any]], criteria: list[dict[str, Any]]) -> go.Figure:
    """Compare the selected supplier with peer averages on a readable 0–100% scale."""
    names = [str(c["name"]) for c in criteria]
    keys = [str(c.get("criterion_id", c["name"])) for c in criteria]
    max_scores = [float(c.get("max_score", 10)) for c in criteria]

    def normalized(row: dict[str, Any]) -> list[float]:
        scores = {str(item["criterion_id"]): float(item.get("final_score", item["score"])) for item in row.get("scores", [])}
        return [100 * scores.get(key, 0) / max(max_score, .01) for key, max_score in zip(keys, max_scores)]

    selected = normalized(supplier)
    peer_values = [normalized(row) for row in peers]
    peer_average = [sum(row[i] for row in peer_values) / len(peer_values) for i in range(len(names))] if peer_values else [0] * len(names)
    fig = go.Figure()
    for label, values, color in ((supplier.get("supplier_name", "Selected supplier"), selected, PALETTE[0]),
                                 ("Peer average", peer_average, PALETTE[1])):
        fig.add_trace(go.Bar(name=label, x=values, y=names, orientation="h", marker_color=color,
            text=[f"{value:.0f}%" for value in values], textposition="auto",
            hovertemplate=f"{label}<br>%{{y}}<br>%{{x:.1f}}% of criterion maximum<extra></extra>"))
    fig.update_layout(barmode="group", height=max(320, len(names) * 44),
        margin={"l": 12, "r": 25, "t": 12, "b": 35},
        xaxis={"range": [0, 110], "title": "Score as a percentage of each criterion maximum"},
        yaxis={"title": "", "automargin": True, "autorange": "reversed"},
        legend={"orientation": "h", "y": 1.08, "x": 0},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", bargap=.28)
    fig.update_xaxes(gridcolor="#e6ece9", zeroline=False)
    fig.update_yaxes(showgrid=False)
    return fig


def compare_radar(suppliers: list[dict[str, Any]], criteria: list[dict[str, Any]]) -> go.Figure:
    names = [c["name"] for c in criteria]
    keys = [str(c.get("criterion_id", c["name"])) for c in criteria]
    fig = go.Figure()
    for i, row in enumerate(suppliers):
        scores = {str(x["criterion_id"]): float(x.get("final_score", x["score"])) for x in row["scores"]}
        fig.add_trace(go.Scatterpolar(r=[scores.get(k, 0) for k in keys], theta=names, name=row["supplier_name"], line_color=PALETTE[i % len(PALETTE)]))
    fig.update_layout(polar={"radialaxis": {"visible": True, "range": [0, max(float(c.get("max_score", 10)) for c in criteria)]}}, height=430,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


def score_contribution_chart(supplier: dict[str, Any], criteria: list[dict[str, Any]]) -> go.Figure:
    """Show the weighted points each criterion contributes to the total score."""
    rows = []
    for criterion in criteria:
        key = str(criterion.get("criterion_id", criterion["name"]))
        item = next((s for s in supplier["scores"] if str(s["criterion_id"]) == key), None)
        score = float(item.get("final_score", item["score"])) if item else 0.0
        maximum = float(criterion.get("max_score", 10))
        weight = float(criterion.get("weight", 0))
        contribution = criterion_weighted_contribution(item, criterion)
        rows.append({"name": str(criterion["name"]), "score": score, "maximum": maximum,
                     "weight": weight, "contribution": contribution})
    rows.sort(key=lambda row: (-row["contribution"], row["name"].casefold()))
    names = [row["name"] for row in rows]
    exact_values = [row["contribution"] for row in rows]
    values = [round(value, 2) for value in exact_values]
    # Allocate any cent-level rounding remainder so the displayed bars sum to
    # the same two-decimal total shown above the chart.
    remainder = round(round(sum(exact_values), 2) - sum(values), 2)
    if values and remainder:
        step = 0.01 if remainder > 0 else -0.01
        cents = int(round(abs(remainder) * 100))
        order = sorted(range(len(values)), key=lambda i: exact_values[i] - values[i], reverse=remainder > 0)
        for index in order[:cents]:
            values[index] = round(values[index] + step, 2)
    fig = go.Figure(go.Bar(x=values, y=names, orientation="h", marker_color="#39836f",
        text=[f"+{value:.2f} pts" for value in values], textposition="outside", cliponaxis=False,
        customdata=[[row["score"], row["maximum"], row["weight"]] for row in rows],
        hovertemplate="%{y}<br>Weighted contribution: %{x:.2f} points<br>Criterion score: %{customdata[0]:g} / %{customdata[1]:g}<br>Weight: %{customdata[2]:g}%<extra></extra>"))
    fig.update_layout(height=max(300, len(names) * 42), showlegend=False,
        margin={"l": 12, "r": 62, "t": 12, "b": 40},
        xaxis={"range": [0, max(5, max(values, default=0) * 1.25)], "title": "Points added to the total score (out of 100)"},
        yaxis={"title": "", "automargin": True, "autorange": "reversed"},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    fig.update_xaxes(gridcolor="#e6ece9", zeroline=False)
    fig.update_yaxes(showgrid=False)
    return fig


def radial_gauge(score: float) -> go.Figure:
    fig = go.Figure(go.Indicator(mode="gauge+number", value=max(0, min(100, score)), number={"suffix": "/100"},
        gauge={"axis": {"range": [0, 100]}, "bar": {"color": "#1f6b64"}, "bgcolor": "#e9efec", "steps": [{"range": [0, 55], "color": "#f5e2de"}, {"range": [55, 75], "color": "#faedcf"}, {"range": [75, 100], "color": "#d9eee5"}] }))
    fig.update_layout(height=160, margin={"l": 12, "r": 12, "t": 10, "b": 0}, paper_bgcolor="rgba(0,0,0,0)")
    return fig


def peer_heatmap(suppliers: list[dict[str, Any]], criteria: list[dict[str, Any]]) -> go.Figure:
    names = [c["name"] for c in criteria]
    keys = [str(c.get("criterion_id", c["name"])) for c in criteria]
    values = []
    for index, key in enumerate(keys):
        row = []
        for supplier in suppliers:
            scores = {str(item["criterion_id"]): float(item.get("final_score", item["score"])) for item in supplier["scores"]}
            row.append(scores.get(key, 0) / max(float(criteria[index].get("max_score", 10)), .01) * 100)
        values.append(row)
    fig = go.Figure(go.Heatmap(z=values, x=[s["supplier_name"] for s in suppliers], y=names,
        colorscale=[[0, "#f4d9d5"], [.55, "#f2e6bf"], [1, "#8fc1a9"]], zmin=0, zmax=100,
        colorbar={"title": "% of max", "ticksuffix": "%"},
        hovertemplate="%{y}<br>%{x}<br>%{z:.0f}% of criterion max<extra></extra>"))
    fig.update_layout(height=max(300, len(criteria) * 35), margin={"l": 12, "r": 15, "t": 12, "b": 60}, paper_bgcolor="rgba(0,0,0,0)",
        xaxis={"title": "Supplier", "automargin": True}, yaxis={"title": "Criterion", "automargin": True, "autorange": "reversed"})
    return fig


def strength_bar(score: float, benchmark: float, max_score: float, gap: float) -> go.Figure:
    fig = go.Figure(go.Bar(x=[score], y=["Final score"], orientation="h", marker_color="#4c9d82", text=[f"{score:g} / {max_score:g}"], textposition="inside"))
    fig.add_shape(type="line", x0=benchmark, x1=benchmark, y0=-.45, y1=.45, line={"color": "#c07823", "width": 3, "dash": "dash"})
    fig.update_layout(xaxis={"range": [0, max_score], "title": f"Criterion score (max {max_score:g})"}, yaxis={"visible": False}, height=110,
        margin={"l": 5, "r": 12, "t": 8, "b": 32}, showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig
