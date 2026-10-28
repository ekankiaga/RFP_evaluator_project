"""SQLite connection management and versioned schema migrations."""

from __future__ import annotations

import sqlite3
import importlib
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import DB_PATH, SQLITE_BUSY_TIMEOUT_MS

SCHEMA_VERSION = 1

MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE IF NOT EXISTS evaluation_criteria (
      criterion_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '', weight REAL NOT NULL CHECK(weight >= 0 AND weight <= 100),
      max_score REAL NOT NULL CHECK(max_score > 0), is_active INTEGER NOT NULL DEFAULT 1,
      sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS domain_packs (
      domain_id TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL,
      description TEXT NOT NULL, pack_json TEXT NOT NULL, checksum TEXT NOT NULL,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS criteria_sets (
      criteria_set_id TEXT PRIMARY KEY, name TEXT NOT NULL, version INTEGER NOT NULL,
      domain_id TEXT NOT NULL, merge_mode TEXT NOT NULL, total_weight REAL NOT NULL,
      snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(name, version)
    );
    CREATE TABLE IF NOT EXISTS criteria_set_items (
      item_id INTEGER PRIMARY KEY AUTOINCREMENT, criteria_set_id TEXT NOT NULL REFERENCES criteria_sets(criteria_set_id),
      criterion_key TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
      weight REAL NOT NULL, max_score REAL NOT NULL, what_to_inspect TEXT NOT NULL DEFAULT '',
      red_flags_json TEXT NOT NULL DEFAULT '[]', evidence_hints_json TEXT NOT NULL DEFAULT '[]',
      is_mandatory_gate INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1,
      UNIQUE(criteria_set_id, criterion_key)
    );
    CREATE TABLE IF NOT EXISTS rfp_runs (
      rfp_run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      status TEXT NOT NULL, run_version INTEGER NOT NULL DEFAULT 1, domain_id TEXT,
      criteria_set_id TEXT REFERENCES criteria_sets(criteria_set_id), model TEXT,
      prompt_version TEXT, criteria_snapshot_json TEXT NOT NULL DEFAULT '{}',
      reproducibility_json TEXT NOT NULL DEFAULT '{}', warnings_json TEXT NOT NULL DEFAULT '[]',
      content_hash TEXT, finalized_at TEXT, finalized_by TEXT
    );
    CREATE TABLE IF NOT EXISTS suppliers_in_run (
      supplier_id TEXT PRIMARY KEY, rfp_run_id TEXT NOT NULL REFERENCES rfp_runs(rfp_run_id) ON DELETE CASCADE,
      supplier_name TEXT NOT NULL, submission_date TEXT NOT NULL, experience_rating REAL NOT NULL,
      document_hash TEXT NOT NULL, document_name TEXT NOT NULL DEFAULT '', page_count INTEGER,
      text_quality REAL, status TEXT NOT NULL DEFAULT 'AI Evaluated', compliant INTEGER,
      rank INTEGER, warnings_json TEXT NOT NULL DEFAULT '[]', UNIQUE(rfp_run_id, supplier_name)
    );
    CREATE TABLE IF NOT EXISTS supplier_results (
      result_id INTEGER PRIMARY KEY AUTOINCREMENT, rfp_run_id TEXT NOT NULL REFERENCES rfp_runs(rfp_run_id) ON DELETE CASCADE,
      supplier_id TEXT NOT NULL REFERENCES suppliers_in_run(supplier_id) ON DELETE CASCADE,
      supplier_name TEXT NOT NULL, submission_date TEXT NOT NULL, experience_rating REAL NOT NULL,
      absolute_score REAL NOT NULL DEFAULT 0, ppi REAL NOT NULL DEFAULT 0,
      final_rank INTEGER, result_json TEXT NOT NULL, tie_break_explanation TEXT NOT NULL DEFAULT '',
      UNIQUE(rfp_run_id, supplier_id)
    );
    CREATE TABLE IF NOT EXISTS criterion_scores (
      score_id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_id TEXT NOT NULL REFERENCES suppliers_in_run(supplier_id) ON DELETE CASCADE,
      criterion_key TEXT NOT NULL, criterion_name TEXT NOT NULL, weight REAL NOT NULL, max_score REAL NOT NULL,
      ai_score REAL NOT NULL, final_score REAL NOT NULL, justification TEXT NOT NULL DEFAULT '',
      evidence_quote TEXT NOT NULL DEFAULT '', page INTEGER, evidence_verified INTEGER NOT NULL DEFAULT 0,
      confidence TEXT NOT NULL DEFAULT 'medium', override_reason TEXT, overridden_by TEXT,
      overridden_at TEXT, prior_versions_json TEXT NOT NULL DEFAULT '[]', UNIQUE(supplier_id, criterion_key)
    );
    CREATE TABLE IF NOT EXISTS gate_results (
      gate_result_id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_id TEXT NOT NULL REFERENCES suppliers_in_run(supplier_id) ON DELETE CASCADE,
      gate_id TEXT NOT NULL, gate_name TEXT NOT NULL, outcome TEXT NOT NULL,
      evidence_quote TEXT NOT NULL DEFAULT '', page INTEGER, mandatory INTEGER NOT NULL DEFAULT 1,
      UNIQUE(supplier_id, gate_id)
    );
    CREATE TABLE IF NOT EXISTS comments (
      comment_id INTEGER PRIMARY KEY AUTOINCREMENT, rfp_run_id TEXT NOT NULL REFERENCES rfp_runs(rfp_run_id) ON DELETE CASCADE,
      supplier_id TEXT, criterion_key TEXT, actor TEXT NOT NULL, body TEXT NOT NULL,
      created_at TEXT NOT NULL, parent_comment_id INTEGER REFERENCES comments(comment_id)
    );
    CREATE TABLE IF NOT EXISTS review_status (
      supplier_id TEXT PRIMARY KEY REFERENCES suppliers_in_run(supplier_id) ON DELETE CASCADE,
      status TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL, reason TEXT
    );
    CREATE TABLE IF NOT EXISTS scenarios (
      scenario_id TEXT PRIMARY KEY, rfp_run_id TEXT NOT NULL REFERENCES rfp_runs(rfp_run_id) ON DELETE CASCADE,
      name TEXT NOT NULL, weights_json TEXT NOT NULL, results_json TEXT NOT NULL,
      is_official INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS audit_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp_utc TEXT NOT NULL, rfp_run_id TEXT,
      actor TEXT NOT NULL, role TEXT NOT NULL, event_type TEXT NOT NULL, entity_type TEXT NOT NULL,
      entity_id TEXT NOT NULL, before_json TEXT, after_json TEXT, reason TEXT,
      prev_hash TEXT NOT NULL, entry_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS llm_calls (
      llm_call_id TEXT PRIMARY KEY, rfp_run_id TEXT REFERENCES rfp_runs(rfp_run_id),
      supplier_id TEXT REFERENCES suppliers_in_run(supplier_id), provider_id TEXT NOT NULL,
      model TEXT NOT NULL, base_url_host TEXT, key_fingerprint TEXT, prompt_version TEXT NOT NULL,
      prompt_hash TEXT NOT NULL, document_hash TEXT, criteria_set_hash TEXT,
      input_tokens INTEGER, output_tokens INTEGER, latency_ms REAL, status TEXT NOT NULL,
      error_category TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS app_settings (
      setting_key TEXT PRIMARY KEY, setting_json TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_runs_created ON rfp_runs(created_at);
    CREATE INDEX IF NOT EXISTS idx_suppliers_run ON suppliers_in_run(rfp_run_id);
    CREATE INDEX IF NOT EXISTS idx_scores_supplier ON criterion_scores(supplier_id);
    CREATE INDEX IF NOT EXISTS idx_audit_run_time ON audit_log(rfp_run_id, timestamp_utc);
    CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_log(event_type);
    CREATE INDEX IF NOT EXISTS idx_llm_run ON llm_calls(rfp_run_id);
    """,
}


@contextmanager
def connect(db_path: str | Path | None = DB_PATH) -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection or a configured SQLite-compatible adapter.

    Custom adapters are loaded lazily with ``RFP_COMPASS_DB_ADAPTER=custom`` and
    ``RFP_COMPASS_DB_ADAPTER_FACTORY=module:callable``. The factory receives the
    configured path/URI and must return a connection with ``execute``, ``commit``,
    ``rollback``, ``close`` and sqlite3.Row-compatible mapping rows.
    """
    effective_path = DB_PATH if db_path is None else db_path
    adapter = os.getenv("RFP_COMPASS_DB_ADAPTER", "sqlite").casefold()
    if adapter == "custom":
        target = os.getenv("RFP_COMPASS_DB_ADAPTER_FACTORY", "")
        if ":" not in target:
            raise RuntimeError("Custom DB adapter requires RFP_COMPASS_DB_ADAPTER_FACTORY=module:callable")
        module_name, factory_name = target.split(":", 1)
        factory = getattr(importlib.import_module(module_name), factory_name)
        conn = factory(str(effective_path))
        try:
            yield conn
        finally:
            conn.close()
        return
    if adapter != "sqlite":
        raise RuntimeError(f"Unsupported RFP_COMPASS_DB_ADAPTER: {adapter}")
    path = Path(effective_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    try:
        yield conn
    finally:
        conn.close()


def migrate(db_path: str | Path | None = DB_PATH) -> None:
    """Apply each unapplied schema migration atomically."""
    with connect(db_path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for version, script in sorted(MIGRATIONS.items()):
            if version in applied:
                continue
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.executescript(script)
                conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
