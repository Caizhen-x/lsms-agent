"""Tool definitions for the Claude agent.

Each function corresponds to one Claude tool.  Tools return JSON-serializable
dicts that are passed back to Claude as `tool_result` content.
"""
from __future__ import annotations

import base64
import json
from functools import lru_cache
from typing import Any

import pandas as pd

from .config import PARQUET_DIR, VARIABLES_PARQUET
from .sandbox import PythonSandbox


# ---- Schemas -----------------------------------------------------------------

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "list_countries_and_rounds",
        "description": (
            "Return the full inventory of countries and survey rounds available. "
            "Call this first when the user asks general questions about scope."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_modules",
        "description": (
            "List the data modules (files) available for one country+round. "
            "Returns module filenames and row counts.  Use to discover what data exists "
            "before loading it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "country": {"type": "string", "description": "Country name, e.g. 'Tanzania'"},
                "round": {"type": "string", "description": "Round key, e.g. '2010_NPS_W2'"},
            },
            "required": ["country", "round"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_variables",
        "description": (
            "Substring/keyword search over the variable catalog. Matches against variable "
            "names AND labels (case-insensitive).  Filter by country and/or round to narrow. "
            "Use this to find which module contains a concept like 'education', 'consumption', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms (e.g. 'education years schooling')"},
                "country": {"type": "string"},
                "round": {"type": "string"},
                "limit": {"type": "integer", "default": 30, "minimum": 1, "maximum": 200},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_python",
        "description": (
            "Execute Python code in the session sandbox.  State persists across calls. "
            "Pre-imported: pandas (pd), numpy (np), matplotlib.pyplot (plt), seaborn (sns). "
            "Helpers: load_module(country, round, module_file) returns a DataFrame. "
            "Use print() to surface results.  Plots created with plt are captured automatically. "
            "Timeout: 60s per call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "Python source to execute"}},
            "required": ["code"],
            "additionalProperties": False,
        },
    },
]


# ---- Data loaders (cached) ---------------------------------------------------

@lru_cache(maxsize=1)
def _catalog() -> pd.DataFrame:
    if not VARIABLES_PARQUET.exists():
        raise FileNotFoundError(
            f"variables catalog missing at {VARIABLES_PARQUET}. Run `make catalog`."
        )
    return pd.read_parquet(VARIABLES_PARQUET)


@lru_cache(maxsize=1)
def _inventory() -> dict[str, dict[str, list[str]]]:
    """{country: {round: [module_file, ...]}}"""
    df = _catalog()
    out: dict[str, dict[str, list[str]]] = {}
    for (country, rnd), grp in df.groupby(["country", "round"]):
        out.setdefault(country, {})[rnd] = sorted(grp["module_file"].unique().tolist())
    return out


# ---- Tool implementations ----------------------------------------------------

def list_countries_and_rounds() -> dict:
    inv = _inventory()
    summary = {
        c: {"rounds": sorted(rounds.keys()), "n_modules": sum(len(m) for m in rounds.values())}
        for c, rounds in inv.items()
    }
    return {"countries": summary, "total_countries": len(summary)}


def list_modules(country: str, round: str) -> dict:
    inv = _inventory()
    if country not in inv:
        return {"error": f"unknown country '{country}'. Known: {sorted(inv.keys())}"}
    if round not in inv[country]:
        return {"error": f"unknown round '{round}' for {country}. Known: {sorted(inv[country].keys())}"}
    df = _catalog()
    sub = df[(df["country"] == country) & (df["round"] == round)]
    modules = (
        sub.groupby("module_file")
        .agg(n_variables=("var_name", "count"))
        .reset_index()
        .sort_values("module_file")
        .to_dict(orient="records")
    )
    return {"country": country, "round": round, "modules": modules}


def search_variables(query: str, country: str | None = None, round: str | None = None, limit: int = 30) -> dict:
    df = _catalog()
    if country:
        df = df[df["country"] == country]
    if round:
        df = df[df["round"] == round]

    terms = [t.strip().lower() for t in query.split() if t.strip()]
    if not terms:
        return {"hits": [], "n_hits": 0, "query": query}

    blob = df["search_blob"].fillna("")
    mask = pd.Series(True, index=df.index)
    for t in terms:
        mask &= blob.str.contains(t, regex=False, na=False)
    hits = df[mask].head(limit)

    rows = hits[["country", "round", "module_file", "var_name", "label", "dtype"]].to_dict(orient="records")
    # Attach value labels for the top hits only (saves tokens).
    for i, r in enumerate(rows):
        if i < 5:
            vl = hits.iloc[i].get("value_labels_json", "{}")
            try:
                r["value_labels"] = json.loads(vl) if vl else {}
            except Exception:
                r["value_labels"] = {}
    return {"hits": rows, "n_hits": int(mask.sum()), "showing": len(rows), "query": query}


def run_python(code: str, sandbox: PythonSandbox) -> dict[str, Any]:
    res = sandbox.run(code)
    payload: dict[str, Any] = {
        "stdout": res.stdout[-8000:] if res.stdout else "",
        "stderr": res.stderr[-4000:] if res.stderr else "",
        "n_figures": len(res.figures),
    }
    if res.error:
        payload["error"] = res.error
    if res.timed_out:
        payload["timed_out"] = True
    # Figures are returned separately to the caller (so the UI can render them),
    # not embedded in the tool_result JSON (saves tokens).
    payload["_figures_b64"] = [base64.b64encode(f).decode() for f in res.figures]
    return payload


# Dispatch by name ------------------------------------------------------------

def dispatch(name: str, args: dict, sandbox: PythonSandbox) -> dict:
    if name == "list_countries_and_rounds":
        return list_countries_and_rounds()
    if name == "list_modules":
        return list_modules(**args)
    if name == "search_variables":
        return search_variables(**args)
    if name == "run_python":
        return run_python(args["code"], sandbox)
    return {"error": f"unknown tool: {name}"}
