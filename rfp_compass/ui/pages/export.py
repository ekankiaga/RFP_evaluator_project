"""Run details, JSON export, workspace backup/restore, and finalization."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from ...audit.audit_log import AuditLog
from ...config import DB_PATH
from ...db import connect
from ...tools.persistence_tool import PersistenceTool
from .common import current_run


def render() -> None:
    st.title("Run details and export")
    run = current_run()
    if not run:
        st.info("No evaluation run yet. Complete Setup, add supplier proposals, and run an evaluation first.")
    else:
        st.markdown(f"### `{run['rfp_run_id']}`")
        st.caption(f"Status: **{run.get('status', 'Draft')}** · model `{run.get('model', 'unknown')}` · prompt `{run.get('reproducibility', {}).get('prompt_version', 'unknown')}`")
        estimate = run.get("estimated_cost_usd")
        cost_label = f"${float(estimate):.4f}" if estimate is not None else "Unavailable"
        st.write(f"Suppliers: {len(run['suppliers'])} · Criteria: {len(run['criteria'])} · Estimated provider cost: {cost_label}")
        st.caption("Export the complete structured evaluation as JSON. The workspace backup includes local run and audit data; proposal PDFs are not embedded in JSON exports.")
        with st.expander("Criteria snapshot"):
            st.json(run["criteria"])
        with st.expander("Warnings and tie-break explanations"):
            for warning in run.get("warnings", []):
                st.warning(warning)
            for supplier in run["suppliers"]:
                if supplier.get("tie_break_explanation"):
                    st.write(f"**{supplier['supplier_name']}** · {supplier['tie_break_explanation']}")
        safe_run = _exportable_run(run)
        st.download_button("Download complete run JSON", json.dumps(safe_run, indent=2, ensure_ascii=False, default=str).encode("utf-8"),
            f"{run['rfp_run_id']}.json", "application/json", type="primary",
            on_click=_log_export, args=(run["rfp_run_id"], "json"))
        _workflow_controls(run)
    st.divider()
    st.subheader("Workspace backup and restore")
    if os.getenv("RFP_COMPASS_DB_ADAPTER", "sqlite").casefold() != "sqlite":
        st.info("Workspace file backup and restore are available with the local SQLite adapter. Use the configured database service's backup controls for remote storage.")
    else:
        if st.button("Prepare workspace backup"):
            with connect() as conn:
                conn.execute("PRAGMA wal_checkpoint(FULL)")
            st.session_state["workspace_backup"] = DB_PATH.read_bytes() if DB_PATH.exists() else b""
        backup = st.session_state.get("workspace_backup")
        if backup:
            st.download_button("Download SQLite workspace and audit log", backup, "rfp_compass_workspace.sqlite3", "application/vnd.sqlite3")
        uploaded = st.file_uploader("Restore SQLite workspace", type=["sqlite3", "db"], key="restore_db")
        if uploaded:
            st.warning("Restoring replaces this workspace database. Export a backup first if you need the current runs.")
            confirm = st.checkbox("I understand this replaces the current workspace database.", key="confirm_restore")
            if st.button("Validate and restore workspace", disabled=not confirm or st.session_state.get("role") == "Viewer"):
                data = uploaded.getvalue()
                try:
                    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False, dir=Path.cwd()) as temporary:
                        temporary.write(data)
                        temp_path = Path(temporary.name)
                    # Inspect restore candidates with SQLite directly, even if the app
                    # later supports an alternate live database adapter.
                    import sqlite3
                    validation_conn = sqlite3.connect(temp_path)
                    try:
                        integrity = validation_conn.execute("PRAGMA integrity_check").fetchone()[0]
                        tables = {r[0] for r in validation_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    finally:
                        validation_conn.close()
                    required = {"rfp_runs", "supplier_results", "audit_log", "schema_migrations"}
                    if integrity != "ok" or not required.issubset(tables):
                        raise ValueError("File is not a valid RFP Compass workspace database.")
                    chain_ok, broken = AuditLog(temp_path).verify()
                    if not chain_ok:
                        raise ValueError(f"Backup audit chain is broken at entry {broken}.")
                    if DB_PATH.exists():
                        with connect() as conn:
                            conn.execute("PRAGMA wal_checkpoint(FULL)")
                        shutil.copy2(DB_PATH, DB_PATH.with_suffix(".sqlite3.bak"))
                    DB_PATH.write_bytes(data)
                    _clear_connection_secrets()
                    AuditLog().append(actor=st.session_state.get("actor", "analyst"), role=st.session_state.get("role", "Analyst"),
                        event_type="workspace_restored", entity_type="workspace", entity_id="database", reason="User restored a validated SQLite backup")
                    st.success("Workspace restored. A backup of the prior database was saved alongside it.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Restore failed: {exc}")


def _workflow_controls(run):
    role = st.session_state.get("role", "Analyst")
    if run.get("status") != "Finalized":
        choice = st.selectbox("Run status", ["Draft", "In Review"], index=0 if run.get("status") == "Draft" else 1, disabled=role == "Viewer")
        if choice != run.get("status") and st.button("Update run status", disabled=role == "Viewer"):
            with connect() as conn:
                conn.execute("UPDATE rfp_runs SET status=?, updated_at=? WHERE rfp_run_id=?", (choice, datetime.now(timezone.utc).isoformat(), run["rfp_run_id"]))
            AuditLog().append(actor=st.session_state.get("actor", "analyst"), role=role, event_type="run_status_changed", entity_type="run", entity_id=run["rfp_run_id"], rfp_run_id=run["rfp_run_id"], before={"status": run.get("status")}, after={"status": choice}, reason="Run status updated")
            run["status"] = choice
            st.rerun()
        confirm = st.checkbox("I confirm this run is ready to finalize.", key="finalize_confirm")
        if st.button("Finalize and lock run", type="primary", disabled=role != "Approver" or not confirm):
            content_hash = hashlib.sha256(json.dumps(_exportable_run(run), sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
            now = datetime.now(timezone.utc).isoformat()
            with connect() as conn:
                conn.execute("UPDATE rfp_runs SET status='Finalized', updated_at=?, content_hash=?, finalized_at=?, finalized_by=? WHERE rfp_run_id=?",
                    (now, content_hash, now, st.session_state.get("actor", "approver"), run["rfp_run_id"]))
            AuditLog().append(actor=st.session_state.get("actor", "approver"), role=role, event_type="run_finalized", entity_type="run", entity_id=run["rfp_run_id"], rfp_run_id=run["rfp_run_id"], after={"content_hash": content_hash}, reason="Approver finalized run")
            run.update({"status": "Finalized", "content_hash": content_hash, "finalized_at": now})
            st.success(f"Run finalized and locked. Content hash: `{content_hash}`")
            st.rerun()
        if role != "Approver":
            st.caption("Only the Approver role can finalize a run.")
    else:
        st.success(f"Finalized · locked · SHA-256 `{run.get('content_hash', '')}`")
        reason = st.text_input("Reason for reopening", key="reopen_reason")
        if st.button("Reopen as a new draft version", disabled=role != "Approver" or not reason.strip()):
            with connect() as conn:
                row = conn.execute("SELECT run_version FROM rfp_runs WHERE rfp_run_id=?", (run["rfp_run_id"],)).fetchone()
                version = int(row[0]) + 1 if row else 2
                conn.execute("UPDATE rfp_runs SET status='Draft', run_version=?, updated_at=?, content_hash=NULL, finalized_at=NULL, finalized_by=NULL WHERE rfp_run_id=?",
                    (version, datetime.now(timezone.utc).isoformat(), run["rfp_run_id"]))
            AuditLog().append(actor=st.session_state.get("actor", "approver"), role=role, event_type="run_reopened", entity_type="run", entity_id=run["rfp_run_id"], rfp_run_id=run["rfp_run_id"], after={"run_version": version}, reason=reason)
            run.update({"status": "Draft", "run_version": version, "content_hash": None})
            st.rerun()


def _exportable_run(run):
    result = {key: value for key, value in run.items() if key not in {"steps"}}
    result["suppliers"] = [{key: value for key, value in supplier.items() if key != "document_pages"} for supplier in run["suppliers"]]
    return result


def _clear_connection_secrets():
    from ...llm.key_vault import forget_secret
    for connection in st.session_state.get("saved_connections", {}).values():
        if connection.api_key:
            forget_secret(connection.api_key.get_secret_value())
    st.session_state["saved_connections"] = {}
    st.session_state.pop("evaluation_connection", None)
    st.session_state["connection_health"] = {}
    st.session_state["demo_mode"] = True


def _log_export(run_id: str, format_name: str) -> None:
    AuditLog().append(actor=st.session_state.get("actor", "analyst"), role=st.session_state.get("role", "Analyst"),
        event_type="run_exported", entity_type="run", entity_id=run_id, rfp_run_id=run_id,
        after={"format": format_name})
