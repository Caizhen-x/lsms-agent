"""Shared config — env-driven."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
COUNTRY_DATA_DIR = Path(os.getenv("COUNTRY_DATA_DIR", REPO_ROOT / "Country Data")).resolve()
CATALOG_DIR = Path(os.getenv("CATALOG_DIR", REPO_ROOT / "catalog")).resolve()
PARQUET_DIR = CATALOG_DIR / "parquet"
VARIABLES_PARQUET = CATALOG_DIR / "variables.parquet"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
GROUP_PASSWORD = os.getenv("GROUP_PASSWORD", "")

SANDBOX_TIMEOUT_SEC = int(os.getenv("SANDBOX_TIMEOUT_SEC", "60"))
MAX_TOOL_TURNS = int(os.getenv("MAX_TOOL_TURNS", "20"))
