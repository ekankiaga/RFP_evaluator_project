"""Idempotently initialize SQLite and seed criteria and built-in domain packs."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rfp_compass.config import DEFAULT_GENERIC_WEIGHTS, DOMAIN_PACK_DIR  # noqa: E402
from rfp_compass.db import connect, migrate  # noqa: E402


def seed(db_path: str | Path | None = None) -> None:
    """Apply schema and insert default criteria/domain packs without duplicates."""
    migrate(db_path) if db_path else migrate()
    with connect(db_path) if db_path else connect() as conn:
        for order, (name, weight) in enumerate(DEFAULT_GENERIC_WEIGHTS.items()):
            conn.execute(
                "INSERT INTO evaluation_criteria(name, description, weight, max_score, is_active, sort_order) "
                "SELECT ?, ?, ?, 10, 1, ? WHERE NOT EXISTS "
                "(SELECT 1 FROM evaluation_criteria WHERE name = ?)",
                (name, f"Default evaluation criterion: {name}.", weight, order, name),
            )
        for path in sorted(DOMAIN_PACK_DIR.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            packed = json.dumps(data, ensure_ascii=False, sort_keys=True)
            checksum = hashlib.sha256(packed.encode("utf-8")).hexdigest()
            conn.execute(
                "INSERT INTO domain_packs(domain_id, name, version, description, pack_json, checksum) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(domain_id) DO UPDATE SET "
                "name=excluded.name, version=excluded.version, description=excluded.description, "
                "pack_json=excluded.pack_json, checksum=excluded.checksum, updated_at=CURRENT_TIMESTAMP",
                (data["domain_id"], data["name"], data["version"], data["description"], packed, checksum),
            )


if __name__ == "__main__":
    seed()
    print("RFP Compass database initialized and seeded.")
