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

from server.config import PARQUET_DIR, VARIABLES_PARQUET
from server.data_policy import ALLOW_SENSITIVE_MODULES, sensitive_module_reason, visible_module
from server.sandbox import PythonSandbox


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
            "Returns the relative `module_path` (use this verbatim with load_module), "
            "a `module_file` basename for readability, and the variable count.  Two "
            "different module_paths can share a basename (e.g. Malawi 2010_IHS3 has "
            "both Panel/Agriculture/ag_mod_n.dta and Full_Sample/Agriculture/ag_mod_n.dta) "
            "— always disambiguate by module_path. Sensitive geo/tracking modules are "
            "hidden unless the deployment explicitly enables them."
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
            "Each hit includes the relative `module_path` — pass that verbatim to load_module. "
            "Sensitive geo/tracking modules are hidden unless the deployment explicitly enables them."
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
            "Helper: load_module(country, round, module_path) returns a pandas DataFrame; "
            "`module_path` MUST be the path returned by list_modules / search_variables, "
            "not just a basename — basenames are ambiguous in some rounds. "
            "Use print() to surface results.  Plots created with plt are captured automatically. "
            "Output is capped; do not print entire DataFrames or export raw rows. "
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
    """{country: {round: [module_path, ...]}}"""
    df = _catalog()
    out: dict[str, dict[str, list[str]]] = {}
    for (country, rnd), grp in df.groupby(["country", "round"]):
        out.setdefault(country, {})[rnd] = sorted(grp["module_path"].unique().tolist())
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
    all_module_paths = set(sub["module_path"].dropna().unique().tolist())
    if not ALLOW_SENSITIVE_MODULES:
        sub = sub[sub["module_path"].map(visible_module).astype(bool)]
    modules = (
        sub.groupby("module_path")
        .agg(
            module_file=("module_file", "first"),
            n_variables=("var_name", "count"),
        )
        .reset_index()
        .sort_values("module_path")
        .to_dict(orient="records")
    )
    visible_paths = {m["module_path"] for m in modules}
    hidden = sorted(all_module_paths - visible_paths)
    return {
        "country": country,
        "round": round,
        "modules": modules,
        "sensitive_modules_hidden": len(hidden),
    }


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
    matched = df[mask]
    sensitive_mask = matched["module_path"].map(lambda p: sensitive_module_reason(str(p)) is not None).astype(bool)
    n_sensitive_hidden = int(sensitive_mask.sum()) if not ALLOW_SENSITIVE_MODULES else 0
    if not ALLOW_SENSITIVE_MODULES:
        matched = matched[~sensitive_mask]
    hits = matched.head(limit)

    rows = hits[["country", "round", "module_path", "module_file", "var_name", "label", "dtype"]].to_dict(orient="records")
    # Attach value labels for the top hits only (saves tokens).
    for i, r in enumerate(rows):
        if i < 5:
            vl = hits.iloc[i].get("value_labels_json", "{}")
            try:
                r["value_labels"] = json.loads(vl) if vl else {}
            except Exception:
                r["value_labels"] = {}
    return {
        "hits": rows,
        "n_hits": int(len(matched)),
        "showing": len(rows),
        "query": query,
        "sensitive_hits_hidden": n_sensitive_hidden,
    }


def run_python(code: str, sandbox: PythonSandbox) -> dict[str, Any]:
    res = sandbox.run(code)
    payload: dict[str, Any] = {
        "stdout": res.stdout if res.stdout else "",
        "stderr": res.stderr if res.stderr else "",
        "n_figures": len(res.figures),
        "stdout_truncated": res.stdout_truncated,
        "stderr_truncated": res.stderr_truncated,
    }
    if res.worker_restarted:
        payload["worker_restarted"] = True
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
