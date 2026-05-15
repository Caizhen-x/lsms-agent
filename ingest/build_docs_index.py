"""Build catalog/docs.parquet — one row per text chunk of each reference PDF.

Walks Country Data/<country>/<round>/refs/ for *.pdf files (skips .crdownload
partials), extracts text page-by-page with pypdf, chunks by paragraph with a
soft target of ~600 words / chunk and ~80 words of overlap, and writes a
single parquet file the agent's search_docs tool queries via BM25 at runtime.

Idempotent: re-runs the extraction.  Cheap-ish — 269 PDFs takes ~2 min on a
modern laptop.
"""
from __future__ import annotations

import re
import sys
import traceback
from pathlib import Path
from typing import Iterator

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pypdf import PdfReader

from ingest._common import COUNTRY_DATA_DIR, CATALOG_DIR


DOCS_PARQUET = CATALOG_DIR / "docs.parquet"
TARGET_WORDS = 600
OVERLAP_WORDS = 80


def _refs_dirs() -> Iterator[tuple[str, str, Path]]:
    """Yield (country, round_key, refs_dir) for every round with a refs/ folder."""
    if not COUNTRY_DATA_DIR.is_dir():
        raise SystemExit(f"COUNTRY_DATA_DIR not found: {COUNTRY_DATA_DIR}")
    for country_dir in sorted(p for p in COUNTRY_DATA_DIR.iterdir() if p.is_dir()):
        for round_dir in sorted(p for p in country_dir.iterdir() if p.is_dir()):
            refs = round_dir / "refs"
            if refs.is_dir():
                yield country_dir.name, round_dir.name, refs


def _extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    """Return [(page_num, text)] for every page in pdf_path.  page_num is 1-based."""
    try:
        reader = PdfReader(str(pdf_path), strict=False)
    except Exception as e:
        print(f"  WARN  could not open {pdf_path.name}: {e}", file=sys.stderr)
        return []
    out: list[tuple[int, str]] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text.strip():
            out.append((i, text))
    return out


_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _chunk_text(text: str, target: int = TARGET_WORDS, overlap: int = OVERLAP_WORDS) -> list[str]:
    """Soft word-level chunker.  Sliding window with overlap."""
    text = _normalize(text)
    words = text.split(" ")
    if not words:
        return []
    if len(words) <= target:
        return [text]
    chunks: list[str] = []
    step = max(1, target - overlap)
    for start in range(0, len(words), step):
        piece = " ".join(words[start:start + target])
        if piece:
            chunks.append(piece)
        if start + target >= len(words):
            break
    return chunks


def _iter_pdf_chunks(pdf_path: Path) -> Iterator[tuple[int, int, str]]:
    """Yield (page, chunk_idx_within_page, text) for one PDF."""
    for page_num, raw in _extract_pages(pdf_path):
        chunks = _chunk_text(raw)
        for i, c in enumerate(chunks):
            yield page_num, i, c


def main() -> int:
    print(f"source: {COUNTRY_DATA_DIR}")
    print(f"target: {DOCS_PARQUET}\n")

    rows: list[dict] = []
    n_pdfs_indexed = n_pdfs_skipped = n_pdfs_failed = 0

    for country, round_key, refs_dir in _refs_dirs():
        # Skip .crdownload partials.  Index everything else.
        pdfs = sorted(p for p in refs_dir.rglob("*.pdf") if not p.name.endswith(".crdownload"))
        if not pdfs:
            continue
        print(f"==== {country} / {round_key}  ({len(pdfs)} PDFs) ====")
        for pdf in pdfs:
            try:
                pre = len(rows)
                rel = pdf.relative_to(refs_dir)
                for page, chunk_idx, text in _iter_pdf_chunks(pdf):
                    rows.append({
                        "country": country,
                        "round": round_key,
                        "pdf_path": str(rel),
                        "pdf_name": pdf.name,
                        "page": page,
                        "chunk_idx": chunk_idx,
                        "text": text,
                    })
                added = len(rows) - pre
                if added:
                    n_pdfs_indexed += 1
                    print(f"  ok    {rel}  ({added} chunks)")
                else:
                    n_pdfs_skipped += 1
                    print(f"  skip  {rel}  (no extractable text — image-only PDF?)")
            except Exception as e:
                n_pdfs_failed += 1
                print(f"  FAIL  {pdf.name}: {e}", file=sys.stderr)

    if not rows:
        print("ERROR: no PDF chunks collected — refs/ folders missing or all PDFs unreadable.")
        return 1

    df = pd.DataFrame(rows)
    DOCS_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), DOCS_PARQUET)

    print(f"\nPDFs indexed:    {n_pdfs_indexed}")
    print(f"PDFs skipped:    {n_pdfs_skipped} (no extractable text)")
    print(f"PDFs failed:     {n_pdfs_failed}")
    print(f"chunks total:    {len(df):,}")
    print(f"unique (country,round): {df[['country','round']].drop_duplicates().shape[0]}")
    print(f"written:         {DOCS_PARQUET}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
