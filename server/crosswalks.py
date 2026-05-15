"""Crosswalk recipes — curated YAML files mapping a concept to per-round variables.

Layout on disk:
    crosswalks/<country>/<concept>.yaml

A crosswalk file is a small YAML document.  Example shape:

    concept: years_of_schooling
    country: Tanzania
    notes: |
      Best available proxy is hh_c07 in NPS waves 1-4; W5 renames it to ed_07.
    rounds:
      "2008_NPS_W1":
        module_path: HH_SEC_C.dta
        variable: hh_c07
        label: "Highest grade attained"
      "2010_NPS_W2":
        module_path: HH_SEC_C.dta
        variable: hh_c07

The catalog tools deliberately do NOT auto-generate these — they're a human-
curated artifact that accumulates over time as researchers find and record
equivalences across rounds.  The agent can read them via lookup_crosswalk;
writes are out of scope for v0 (would need editorial control).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from server.config import CROSSWALKS_DIR


def _country_dir(country: str) -> Path:
    return CROSSWALKS_DIR / country


def list_concepts(country: str) -> list[str]:
    """Return the sorted list of concept names available for `country`."""
    d = _country_dir(country)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.yaml") if not p.name.startswith("_"))


def load_crosswalk(country: str, concept: str) -> dict[str, Any] | None:
    """Return the parsed YAML for (country, concept), or None if missing."""
    p = _country_dir(country) / f"{concept}.yaml"
    if not p.is_file():
        return None
    try:
        with p.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as e:
        return {"error": f"failed to parse {p.name}: {e}"}
