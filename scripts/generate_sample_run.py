"""Build a sanitized, deterministic offline sample evaluation JSON."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rfp_compass.llm.mock_provider import MockLLM  # noqa: E402
from rfp_compass.models import ConnectionConfig, ProviderKind  # noqa: E402
from rfp_compass.orchestrator import Orchestrator  # noqa: E402
from scripts.seed_db import seed  # noqa: E402


def main() -> None:
    temp_root = ROOT / "phase2tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rfp-demo-", dir=temp_root) as temp:
        db_path = Path(temp) / "demo.sqlite3"
        seed(db_path)
        pack = yaml.safe_load((ROOT / "domain_packs" / "it_software_saas.yaml").read_text(encoding="utf-8"))
        criteria = []
        for group in (pack.get("generic_criteria", []), pack.get("domain_criteria", [])):
            goal = 60.0 if group is pack.get("generic_criteria") else 40.0
            total = sum(float(c["weight"]) for c in group)
            for criterion in group:
                item = dict(criterion)
                item["criterion_id"] = item["name"]
                item["weight"] = round(float(item["weight"]) * goal / total, 6)
                item["is_active"] = True
                criteria.append(item)
        # Keep a stable 100% total despite rounding.
        criteria[-1]["weight"] = round(criteria[-1]["weight"] + 100 - sum(c["weight"] for c in criteria), 6)
        suppliers = []
        for name, day, experience in [("Apex Systems", "2026-01-10", 9.0), ("BrightPath Tech", "2026-01-12", 8.0),
                                      ("NexaWorks", "2026-01-14", 7.0), ("Orbit Digital", "2026-01-16", 8.5)]:
            pdf_path = ROOT / "sample_data" / "pdfs" / "it_software_saas" / (name.lower().replace(" ", "_") + ".pdf")
            suppliers.append({"supplier_name": name, "submission_date": day, "experience_rating": experience,
                              "document_name": pdf_path.name, "pdf": pdf_path.read_bytes()})
        config = ConnectionConfig(connection_id="sample-offline", provider_id=ProviderKind.MOCK, model="mock-deterministic")
        run = Orchestrator(MockLLM(config), db_path=db_path).evaluate(
            suppliers, criteria=criteria, domain_id="it_software_saas", run_id="SAMPLE-IT-SAAS-001")
        public_run = {key: value for key, value in run.items() if key not in {"steps"}}
        for supplier in public_run["suppliers"]:
            supplier.pop("document_pages", None)
        public_run["sample_notice"] = "Synthetic suppliers and deterministic MockLLM output; no live provider or secret used."
        output = ROOT / "sample_data" / "sample_run.json"
        output.write_text(json.dumps(public_run, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
