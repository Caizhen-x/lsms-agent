"""Build catalog/variables.parquet — one row per variable per module per round per country.

For .dta files: pulls variable labels and value labels from Stata metadata via pyreadstat
(fast metadata-only read; no full data load).
For .csv files: emits a row per column with empty label (no embedded metadata).
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pyreadstat

from ._common import (
    COUNTRY_DATA_DIR,
    VARIABLES_PARQUET,
    iter_data_files,
    iter_rounds,
)


def variables_from_dta(src: Path) -> list[dict]:
    try:
        # metadataonly=True is fast — doesn't read the full data matrix.
        _, meta = pyreadstat.read_dta(
            str(src), metadataonly=True, encoding="latin1"
        )
    except Exception as e:
        print(f"  WARN  {src.name}: dta metadata read failed ({e}); falling back to columns-only")
        return _variables_from_columns(src, is_csv=False)

    labels = meta.column_labels or [""] * len(meta.column_names)
    value_label_map = meta.variable_value_labels or {}
    out = []
    for name, label in zip(meta.column_names, labels):
        out.append({
            "var_name": name,
            "label": label or "",
            "dtype": "stata",
            "value_labels_json": json.dumps(value_label_map.get(name, {}), ensure_ascii=False),
        })
    return out


def variables_from_csv(src: Path) -> list[dict]:
    # Read only the header to avoid loading the whole file.
    for enc in ("utf-8", "latin1"):
        try:
            head = pd.read_csv(src, nrows=0, encoding=enc, low_memory=False)
            break
        except UnicodeDecodeError:
            continue
    else:
        head = pd.read_csv(src, nrows=0, encoding="latin1", low_memory=False)
    return [
        {"var_name": c, "label": "", "dtype": "csv", "value_labels_json": "{}"}
        for c in head.columns
    ]


def _variables_from_columns(src: Path, is_csv: bool) -> list[dict]:
    """Last-resort fallback: read columns only."""
    try:
        if is_csv:
            head = pd.read_csv(src, nrows=0, low_memory=False)
        else:
            head = pd.read_stata(src, iterator=True).variable_labels()
            return [{"var_name": k, "label": v or "", "dtype": "stata", "value_labels_json": "{}"} for k, v in head.items()]
    except Exception:
        return []
    return [
        {"var_name": c, "label": "", "dtype": "csv" if is_csv else "stata", "value_labels_json": "{}"}
        for c in head.columns
    ]


def main() -> int:
    print(f"source: {COUNTRY_DATA_DIR}")
    print(f"target: {VARIABLES_PARQUET}\n")

    rows: list[dict] = []
    files_seen = 0
    files_failed = 0

    for country, round_key, round_dir in iter_rounds():
        data_dir = round_dir / "data"
        print(f"==== {country} / {round_key} ====")
        for src in iter_data_files(data_dir):
            files_seen += 1
            rel = src.relative_to(data_dir)
            try:
                if src.suffix.lower() == ".dta":
                    vars_ = variables_from_dta(src)
                else:
                    vars_ = variables_from_csv(src)
            except Exception as e:
                files_failed += 1
                print(f"  FAIL  {rel}: {e}")
                continue
            for v in vars_:
                rows.append({
                    "country": country,
                    "round": round_key,
                    "module_path": str(rel),
                    "module_file": src.name,
                    **v,
                })
            print(f"  ok    {rel}  ({len(vars_)} vars)")
        print()

    if not rows:
        print("ERROR: no variables collected — did you run `make ingest` first? (We don't need parquet for this step but we do need the raw data.)")
        return 1

    df = pd.DataFrame(rows)
    df["search_blob"] = (
        df["var_name"].fillna("") + " | " + df["label"].fillna("")
    ).str.lower()

    VARIABLES_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), VARIABLES_PARQUET)

    print(f"files: {files_seen} ({files_failed} failed)")
    print(f"variables: {len(df):,}")
    print(f"unique (country, round, module, var): {df[['country','round','module_file','var_name']].drop_duplicates().shape[0]:,}")
    print(f"written: {VARIABLES_PARQUET}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
