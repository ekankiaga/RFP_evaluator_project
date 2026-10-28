"""Append-only SHA-256 hash-chained audit log."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..db import connect, migrate

GENESIS = "0" * 64


def _canonical(entry: dict[str, Any]) -> str:
    return json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


class AuditLog:
    """Write append-only events and verify the chain from its genesis hash."""
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path
        migrate(db_path) if db_path else migrate()
        self._lock = threading.Lock()

    def append(self, *, actor: str, role: str, event_type: str, entity_type: str,
               entity_id: str, rfp_run_id: str | None = None, before: Any = None,
               after: Any = None, reason: str | None = None,
               timestamp_utc: str | None = None) -> dict[str, Any]:
        timestamp = timestamp_utc or datetime.now(timezone.utc).isoformat()
        with self._lock, (connect(self.db_path) if self.db_path else connect()) as conn:
            row = conn.execute("SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
            previous = row[0] if row else GENESIS
            fields = {"timestamp_utc": timestamp, "rfp_run_id": rfp_run_id, "actor": actor,
                      "role": role, "event_type": event_type, "entity_type": entity_type,
                      "entity_id": entity_id, "before_json": _canonical(before) if before is not None else None,
                      "after_json": _canonical(after) if after is not None else None, "reason": reason,
                      "prev_hash": previous}
            digest = hashlib.sha256((previous + _canonical(fields)).encode("utf-8")).hexdigest()
            conn.execute("INSERT INTO audit_log(timestamp_utc,rfp_run_id,actor,role,event_type,entity_type,entity_id,before_json,after_json,reason,prev_hash,entry_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (timestamp, rfp_run_id, actor, role, event_type, entity_type, entity_id,
                          fields["before_json"], fields["after_json"], reason, previous, digest))
            return {**fields, "entry_hash": digest}

    def entries(self, rfp_run_id: str | None = None) -> list[dict[str, Any]]:
        with connect(self.db_path) if self.db_path else connect() as conn:
            if rfp_run_id:
                rows = conn.execute("SELECT * FROM audit_log WHERE rfp_run_id=? ORDER BY id", (rfp_run_id,))
            else:
                rows = conn.execute("SELECT * FROM audit_log ORDER BY id")
            return [dict(row) for row in rows]

    def verify(self) -> tuple[bool, int | None]:
        previous = GENESIS
        for index, row in enumerate(self.entries(), start=1):
            if row["prev_hash"] != previous:
                return False, index
            fields = {key: row[key] for key in ("timestamp_utc", "rfp_run_id", "actor", "role", "event_type", "entity_type", "entity_id", "before_json", "after_json", "reason", "prev_hash")}
            actual = hashlib.sha256((previous + _canonical(fields)).encode("utf-8")).hexdigest()
            if actual != row["entry_hash"]:
                return False, index
            previous = actual
        return True, None
