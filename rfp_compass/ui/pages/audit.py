"""Filterable audit timeline and integrity verification."""

from __future__ import annotations

import csv
import io
from datetime import date
import streamlit as st

from ...audit.audit_log import AuditLog
from .common import current_run


def render() -> None:
    st.title("Audit trail")
    st.caption("Filter recorded workflow events, inspect before/after details, and verify the append-only hash chain.")
    run = current_run()
    entries = AuditLog().entries(run["rfp_run_id"] if run else None)
    if not entries:
        st.info("No audit events are recorded yet.")
        return
    event_types = sorted({row["event_type"] for row in entries})
    actors = sorted({row["actor"] for row in entries})
    with st.expander("Filter audit events", expanded=False):
        c1, c2 = st.columns(2)
        selected_type = c1.multiselect("Event types", event_types, help="Leave empty to include all event types.")
        selected_actor = c2.multiselect("Actors", actors, help="Leave empty to include all actors.")
        c3, c4 = st.columns(2)
        supplier = c3.text_input("Supplier or record contains")
        date_filter = c4.date_input("On or after date", value=None)
    filtered = [row for row in entries if (not selected_type or row["event_type"] in selected_type)
        and (not selected_actor or row["actor"] in selected_actor)
        and (not supplier or supplier.casefold() in row["entity_id"].casefold())
        and (not date_filter or row["timestamp_utc"][:10] >= date_filter.isoformat())]
    st.caption(f"Showing {len(filtered)} of {len(entries)} records.")
    for row in reversed(filtered):
        with st.expander(f"{row['timestamp_utc']} · {row['event_type']} · {row['entity_type']} {row['entity_id']}"):
            st.write(f"Actor: **{row['actor']}** · Role: **{row['role']}**")
            if row.get("reason"):
                st.write(f"Reason: {row['reason']}")
            st.json({"before": row.get("before_json"), "after": row.get("after_json")}, expanded=False)
            st.caption(f"prev_hash `{row['prev_hash']}` · entry_hash `{row['entry_hash']}`")
    if st.button("Verify audit integrity", type="primary"):
        ok, broken = AuditLog().verify()
        st.success("Audit chain verified: no broken entries.") if ok else st.error(f"Audit chain integrity failed at entry {broken}.")
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(entries[0]))
    writer.writeheader()
    writer.writerows(entries)
    st.download_button("Download audit CSV", out.getvalue().encode("utf-8"), "rfp_compass_audit.csv", "text/csv",
        on_click=_log_audit_export)


def _log_audit_export() -> None:
    AuditLog().append(actor=st.session_state.get("actor", "analyst"), role=st.session_state.get("role", "Analyst"),
        event_type="audit_exported", entity_type="audit_log", entity_id="all", after={"format": "csv"})
