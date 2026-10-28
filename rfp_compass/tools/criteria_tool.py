"""Load, validate, normalize, and snapshot active criteria."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import yaml

from ..db import connect, migrate
from ..models import CriterionDefinition


class CriteriaTool:
    """Resolve criteria from SQLite and persist immutable criteria-set snapshots."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path
        migrate(db_path) if db_path else migrate()

    def active_criteria(self) -> list[dict[str, Any]]:
        with connect(self.db_path) if self.db_path else connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM evaluation_criteria WHERE is_active=1 ORDER BY sort_order, criterion_id")]

    @staticmethod
    def validate_weights(criteria: list[dict[str, Any]], tolerance: float = 1e-6) -> bool:
        return abs(sum(float(c["weight"]) for c in criteria if c.get("is_active", True)) - 100.0) <= tolerance

    @staticmethod
    def normalize_weights(criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
        active = [c for c in criteria if c.get("is_active", True)]
        total = sum(max(0.0, float(c["weight"])) for c in active)
        if not active or total <= 0:
            raise ValueError("Cannot normalize empty criteria or zero total weight")
        result = [dict(c) for c in criteria]
        eligible = [i for i, c in enumerate(result) if c.get("is_active", True)]
        allocated = 0.0
        for i in eligible[:-1]:
            result[i]["weight"] = round(max(0.0, float(result[i]["weight"])) * 100 / total, 6)
            allocated += result[i]["weight"]
        result[eligible[-1]]["weight"] = round(100.0 - allocated, 6)
        return result

    def resolve_domain(self, domain_id: str, mode: str = "Generic + Domain pack") -> dict[str, Any]:
        packs = Path(__file__).resolve().parents[2] / "domain_packs"
        data = yaml.safe_load((packs / f"{domain_id}.yaml").read_text(encoding="utf-8"))
        if mode == "Template only":
            return {**data, "resolved_criteria": []}
        generic = [dict(c, group="generic") for c in data.get("generic_criteria", [])]
        domain = [dict(c, group="domain") for c in data.get("domain_criteria", [])]
        if mode == "Generic + Domain pack":
            split = data.get("weight_split", {})
            generic_target = float(split.get("generic", 60))
            domain_target = float(split.get("domain", 40))
            for group, target in ((generic, generic_target), (domain, domain_target)):
                group_total = sum(float(c.get("weight", 0)) for c in group)
                if group and group_total > 0:
                    allocated = 0.0
                    for index, criterion in enumerate(group):
                        if index == len(group) - 1:
                            criterion["weight"] = round(target - allocated, 6)
                        else:
                            criterion["weight"] = round(float(criterion["weight"]) * target / group_total, 6)
                            allocated += criterion["weight"]
            resolved = generic + domain
        elif mode in ("Generic + Uploaded template", "Template only", "Fully custom"):
            resolved = generic if mode == "Generic + Uploaded template" else []
        else:
            raise ValueError(f"Unknown merge mode: {mode}")
        return {**data, "resolved_criteria": resolved}

    def snapshot(self, name: str, domain_id: str, criteria: list[dict[str, Any]], merge_mode: str = "Fully custom") -> str:
        if not self.validate_weights(criteria):
            raise ValueError("Active criteria weights must total 100%")
        fields = set(CriterionDefinition.model_fields)
        validated = [CriterionDefinition.model_validate({key: value for key, value in item.items() if key in fields}) for item in criteria]
        normalized_names = [item.name.casefold().strip() for item in validated if item.is_active]
        if len(normalized_names) != len(set(normalized_names)):
            raise ValueError("Active criterion names must be unique.")
        sid = str(uuid.uuid4())
        with connect(self.db_path) if self.db_path else connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM criteria_sets WHERE name=?", (name,)).fetchone()
            version = int(row[0])
            snapshot = json.dumps([item.model_dump() for item in validated], ensure_ascii=False, sort_keys=True)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO criteria_sets(criteria_set_id,name,version,domain_id,merge_mode,total_weight,snapshot_json) VALUES (?,?,?,?,?,?,?)",
                         (sid, name, version, domain_id, merge_mode, sum(float(c["weight"]) for c in criteria if c.get("is_active", True)), snapshot))
            for idx, item in enumerate([definition.model_dump() for definition in validated]):
                key = str(item.get("criterion_id") or item.get("name", idx))
                conn.execute("INSERT INTO criteria_set_items(criteria_set_id,criterion_key,name,description,weight,max_score,what_to_inspect,red_flags_json,evidence_hints_json,is_mandatory_gate,is_active) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (sid, key, item["name"], item.get("description", ""), float(item["weight"]), float(item.get("max_score", 10)), item.get("what_to_inspect", ""), json.dumps(item.get("red_flags", [])), json.dumps(item.get("evidence_hints", [])), int(bool(item.get("is_mandatory_gate", False))), int(bool(item.get("is_active", True)))))
            conn.commit()
        return sid
