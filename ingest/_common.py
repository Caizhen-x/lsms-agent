"""Shared helpers for ingest scripts."""
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


def iter_rounds():
    """Yield (country, round_key, round_dir) for every round folder."""
    if not COUNTRY_DATA_DIR.is_dir():
        raise SystemExit(f"COUNTRY_DATA_DIR not found: {COUNTRY_DATA_DIR}")
    for country_dir in sorted(p for p in COUNTRY_DATA_DIR.iterdir() if p.is_dir()):
        for round_dir in sorted(p for p in country_dir.iterdir() if p.is_dir()):
            data_dir = round_dir / "data"
            if data_dir.is_dir():
                yield country_dir.name, round_dir.name, round_dir


def iter_data_files(data_dir: Path):
    """Yield every .dta / .csv under data_dir, recursive.  Skip junk."""
    for p in data_dir.rglob("*"):
        if not p.is_file():
            continue
        suf = p.suffix.lower()
        if suf in {".dta", ".csv"}:
            yield p
