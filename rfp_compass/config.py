"""Application configuration and deterministic defaults."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "RFP Compass"
APP_VERSION = "0.1.0"
PROMPT_VERSION = "rfp-evaluation-v1"
BASE_DIR = Path(__file__).resolve().parents[1]
DOMAIN_PACK_DIR = BASE_DIR / "domain_packs"
DB_PATH = Path(os.getenv("RFP_COMPASS_DB", str(BASE_DIR / "rfp_compass.sqlite3")))
DEFAULT_MAX_SCORE = 10.0
DEFAULT_GENERIC_WEIGHTS = {
    "Technical Capability": 30.0,
    "Implementation Plan": 20.0,
    "Commercial Value": 20.0,
    "Security & Compliance": 20.0,
    "Support & Experience": 10.0,
}
SQLITE_BUSY_TIMEOUT_MS = 10000
