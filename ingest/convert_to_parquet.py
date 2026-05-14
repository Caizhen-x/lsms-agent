"""Convert every .dta / .csv file under Country Data/<country>/<round>/data/
to a parquet file mirrored under catalog/parquet/<country>/<round>/.

Idempotent: skips files whose parquet already exists and is newer than the source.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

import pandas as pd
import pyreadstat

from ._common import (
    COUNTRY_DATA_DIR,
    PARQUET_DIR,
    iter_data_files,
    iter_rounds,
)


def parquet_target(country: str, round_key: str, src: Path, data_root: Path) -> Path:
    rel = src.relative_to(data_root)
    return (PARQUET_DIR / country / round_key / rel).with_suffix(".parquet")


def read_dta(src: Path) -> pd.DataFrame:
    # encoding='latin1' avoids the most common decode error in old WB .dta files;
    # pyreadstat's default ('utf-8') breaks on Niger / Mali French stata files.
    df, _ = pyreadstat.read_dta(str(src), encoding="latin1")
    return df


def read_csv(src: Path) -> pd.DataFrame:
    # Try utf-8, then latin1 — covers everything we have without slowing down.
    for enc in ("utf-8", "latin1"):
        try:
            return pd.read_csv(src, encoding=enc, low_memory=False)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(src, encoding="latin1", low_memory=False, on_bad_lines="skip")


def convert_one(src: Path, dst: Path) -> tuple[bool, str]:
    """Return (ok, message)."""
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return True, "skipped (up to date)"
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        if src.suffix.lower() == ".dta":
            df = read_dta(src)
        else:
            df = read_csv(src)
        # parquet doesn't like duplicate column names — dedupe by suffixing.
        if df.columns.has_duplicates:
            seen: dict[str, int] = {}
            new_cols = []
            for c in df.columns:
                if c in seen:
                    seen[c] += 1
                    new_cols.append(f"{c}__{seen[c]}")
                else:
                    seen[c] = 0
                    new_cols.append(c)
            df.columns = new_cols
        df.to_parquet(dst, index=False)
        return True, f"{len(df):,} rows"
    except Exception as e:
        return False, f"ERROR: {e.__class__.__name__}: {e}"


def main() -> int:
    print(f"source: {COUNTRY_DATA_DIR}")
    print(f"target: {PARQUET_DIR}\n")

    total = ok = skipped = failed = 0
    for country, round_key, round_dir in iter_rounds():
        data_dir = round_dir / "data"
        print(f"==== {country} / {round_key} ====")
        for src in iter_data_files(data_dir):
            total += 1
            dst = parquet_target(country, round_key, src, data_dir)
            success, msg = convert_one(src, dst)
            if not success:
                failed += 1
                print(f"  FAIL  {src.relative_to(COUNTRY_DATA_DIR)}: {msg}")
            elif "skipped" in msg:
                skipped += 1
            else:
                ok += 1
                print(f"  ok    {src.relative_to(COUNTRY_DATA_DIR)}  ({msg})")
        print()

    print(f"converted: {ok}  skipped: {skipped}  failed: {failed}  total: {total}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
