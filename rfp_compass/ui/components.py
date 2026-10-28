"""Reusable Streamlit UI components."""

from __future__ import annotations

from typing import Any
from html import escape

import streamlit as st


def card(title: str, body: str = "", kicker: str = "") -> None:
    st.markdown(f'<div class="rc-card"><div class="rc-kicker">{escape(str(kicker))}</div><div class="rc-title">{escape(str(title))}</div><div class="rc-muted">{escape(str(body))}</div></div>', unsafe_allow_html=True)


def chip(text: str, kind: str = "") -> str:
    css = f"rc-chip {kind}".strip()
    return f'<span class="{css}">{escape(str(text))}</span>'


def header_status() -> None:
    connection = st.session_state.get("evaluation_connection")
    health = st.session_state.get("connection_health", {})
    if st.session_state.get("demo_mode", True):
        label, status = "Demo · MockLLM", "ok"
    elif connection:
        label = f"{connection.provider_id.value} · {connection.model}"
        connection_health = health.get(connection.connection_id)
        status = "ok" if connection_health and connection_health.status == "passed" else "warn"
        if connection_health:
            from datetime import datetime, timezone
            minutes = max(0, int((datetime.now(timezone.utc) - connection_health.tested_at).total_seconds() // 60))
            label += f" · tested {minutes} min ago"
        else:
            label += " · untested"
    else:
        label, status = "No evaluation connection", "bad"
    badge = chip(label, "" if status == "ok" else "warn" if status == "warn" else "bad")
    st.markdown(f'<div class="rc-header"><div><span class="rc-kicker">RFP COMPASS</span></div><div>{badge}</div></div>', unsafe_allow_html=True)


def supplier_select(run: dict[str, Any] | None = None, key: str = "supplier_select") -> dict[str, Any] | None:
    run = run or st.session_state.get("current_run")
    if not run or not run.get("suppliers"):
        st.info("Evaluate suppliers to open scorecards and comparisons.")
        return None
    names = [s["supplier_name"] for s in run["suppliers"]]
    selected = st.selectbox("Supplier", names, key=key)
    return next(s for s in run["suppliers"] if s["supplier_name"] == selected)
