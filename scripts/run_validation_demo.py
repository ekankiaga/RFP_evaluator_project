"""Show how malformed model output is normalized, without a live provider."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rfp_compass.tools.validation_tool import ValidationTool  # noqa: E402


def main() -> None:
    criteria = [
        {"criterion_id": "security", "name": "Security", "max_score": 10, "is_active": True},
        {"criterion_id": "delivery", "name": "Delivery plan", "max_score": 10, "is_active": True},
    ]
    malformed_but_repairable = '''```json
    {"supplier_name":"Example Supplier","criteria":[
      {"criterion_id":"security","score":14,"max_score":10,"justification":"Above range","evidence":"AES-256 encryption is enabled.","confidence":"high"},
      {"criterion_id":"unknown","score":9,"max_score":10,"justification":"Unknown key","evidence":"Made up","confidence":"high"}
    ],"risks":[],"overall_summary":"Demonstration","gates":[]}
    ```'''
    pages = [{"page": 1, "text": "AES-256 encryption is enabled for stored records."}]
    payload, warnings = ValidationTool().validate(malformed_but_repairable, criteria, pages)
    print(json.dumps({"normalized": payload.model_dump(), "warnings": warnings}, indent=2))


if __name__ == "__main__":
    main()
