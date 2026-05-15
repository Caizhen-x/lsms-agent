"""Tool definitions for the Claude agent.

Each function corresponds to one Claude tool.  Tools return JSON-serializable
dicts that are passed back to Claude as `tool_result` content.
"""
from __future__ import annotations

import base64
import json
import re
from functools import lru_cache
from typing import Any

import pandas as pd
from rank_bm25 import BM25Okapi

from server.config import DOCS_PARQUET, PARQUET_DIR, VARIABLES_PARQUET
from server.crosswalks import list_concepts, load_crosswalk
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
    {
        "name": "search_docs",
        "description": (
            "BM25 keyword search over the survey questionnaires, manuals, and codebook PDFs. "
            "Use this to look up what a variable means, how a question was worded, value-code "
            "definitions, or any other documentation context for a country / round. "
            "Returns top-k passages with country, round, PDF, page, and a snippet."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms (e.g. 'fertilizer kg per hectare')"},
                "country": {"type": "string"},
                "round": {"type": "string"},
                "limit": {"type": "integer", "default": 6, "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_crosswalks",
        "description": (
            "List the available crosswalk concepts for a country — these are curated YAML files "
            "mapping a concept (e.g. 'years_of_schooling', 'household_id') to the actual variable "
            "names + modules in each round of that country.  Use BEFORE inventing a merge or "
            "harmonization from scratch; an existing crosswalk saves a lot of guesswork."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "country": {"type": "string"},
            },
            "required": ["country"],
            "additionalProperties": False,
        },
    },
    {
        "name": "lookup_crosswalk",
        "description": (
            "Read a curated crosswalk YAML for one (country, concept).  Returns the per-round "
            "variable/module mapping plus any notes from the author.  Returns an error if the "
            "concept hasn't been crosswalked yet — in that case you can proceed by inferring "
            "from search_variables, but flag the uncertainty to the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "country": {"type": "string"},
                "concept": {"type": "string"},
            },
            "required": ["country", "concept"],
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


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


@lru_cache(maxsize=1)
def _docs() -> pd.DataFrame | None:
    if not DOCS_PARQUET.exists():
        return None
    df = pd.read_parquet(DOCS_PARQUET)
    df["_tokens"] = df["text"].map(_tokenize)
    return df


@lru_cache(maxsize=8)
def _bm25(country: str | None, round_: str | None) -> tuple[Any, pd.DataFrame] | None:
    """Build a BM25 index over the (filtered) docs catalog.  Cached per filter."""
    df = _docs()
    if df is None or df.empty:
        return None
    sub = df
    if country:
        sub = sub[sub["country"] == country]
    if round_:
        sub = sub[sub["round"] == round_]
    if sub.empty:
        return None
    sub = sub.reset_index(drop=True)
    return BM25Okapi(sub["_tokens"].tolist()), sub


def search_docs(query: str, country: str | None = None, round: str | None = None, limit: int = 6) -> dict:
    _round_fn = __builtins__["round"] if isinstance(__builtins__, dict) else __builtins__.round  # we shadow `round` arg below
    built = _bm25(country, round)
    if built is None:
        if not DOCS_PARQUET.exists():
            return {
                "hits": [],
                "n_hits": 0,
                "query": query,
                "error": "no docs index built — run `make docs-index`",
            }
        return {"hits": [], "n_hits": 0, "query": query, "note": "no PDFs match this country/round filter"}
    bm25, sub = built
    tokens = _tokenize(query)
    if not tokens:
        return {"hits": [], "n_hits": 0, "query": query}
    scores = bm25.get_scores(tokens)
    # argsort descending, take top `limit`
    import numpy as np

    top = np.argsort(-scores)[:limit]
    hits = []
    for idx in top:
        score = float(scores[idx])
        if score <= 0:
            continue
        row = sub.iloc[int(idx)]
        text = str(row["text"])
        # Build a focused snippet: trim to ~600 chars around the first query-term match.
        snippet = text
        if len(snippet) > 600:
            lowered = text.lower()
            first = min((lowered.find(t) for t in tokens if t in lowered), default=0)
            start = max(0, first - 100)
            snippet = ("…" if start > 0 else "") + text[start:start + 600] + ("…" if start + 600 < len(text) else "")
        hits.append({
            "country": str(row["country"]),
            "round": str(row["round"]),
            "pdf": str(row["pdf_name"]),
            "pdf_path": str(row["pdf_path"]),
            "page": int(row["page"]),
            "score": _round_fn(score, 2),
            "snippet": snippet,
        })
    return {"hits": hits, "n_hits": len(hits), "query": query}


def list_crosswalks_tool(country: str) -> dict:
    concepts = list_concepts(country)
    return {"country": country, "concepts": concepts, "n_concepts": len(concepts)}


def lookup_crosswalk_tool(country: str, concept: str) -> dict:
    data = load_crosswalk(country, concept)
    if data is None:
        available = list_concepts(country)
        return {
            "country": country,
            "concept": concept,
            "error": (
                f"no crosswalk for ({country}, {concept}).  "
                f"Available concepts for {country}: {available or 'none yet'}"
            ),
        }
    return {"country": country, "concept": concept, "crosswalk": data}


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
    if name == "search_docs":
        return search_docs(**args)
    if name == "list_crosswalks":
        return list_crosswalks_tool(**args)
    if name == "lookup_crosswalk":
        return lookup_crosswalk_tool(**args)
    if name == "run_python":
        return run_python(args["code"], sandbox)
    return {"error": f"unknown tool: {name}"}
