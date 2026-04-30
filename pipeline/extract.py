"""
01_extract.py — Input-agnostic requirement extractor.

Supports:
  - Excel (.xlsx, .xls): auto-detects header row and ID column
  - PDF (.pdf): extracts tables via pdfplumber; falls back to text parsing

Output: list of dicts saved to output/reqs_raw.json
  [{"id": "REQ_001", "description": "...", "area": "Compras"}, ...]
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pdfplumber

logger = logging.getLogger(__name__)

# ── Column name heuristics ────────────────────────────────────────────────────
_ID_PATTERNS   = re.compile(r"\b(id|req|requ|n[oº°]|num|code|ref)\b", re.I)
_DESC_PATTERNS = re.compile(r"\b(desc|requirement|requerimiento|title|titulo|nombre|detail)\b", re.I)
_AREA_PATTERNS = re.compile(r"\b(area|module|modulo|bloque|block|domain|dominio)\b", re.I)


def _best_col(df: pd.DataFrame, pattern: re.Pattern) -> str | None:
    """Return the column name that best matches pattern, or None."""
    for col in df.columns:
        if pattern.search(str(col)):
            return col
    return None


def _detect_header_row(path: Path) -> int:
    """
    Scan first 15 rows to find the row that looks like a header
    (i.e. mostly non-null string values, not all numbers).
    """
    raw = pd.read_excel(path, header=None, nrows=15)
    for i, row in raw.iterrows():
        non_null = row.dropna()
        if len(non_null) >= 2 and all(isinstance(v, str) for v in non_null):
            return int(i)
    return 0


# ── Excel extraction ──────────────────────────────────────────────────────────

def extract_excel(path: Path) -> list[dict[str, Any]]:
    header_row = _detect_header_row(path)
    df = pd.read_excel(path, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    id_col   = _best_col(df, _ID_PATTERNS)
    desc_col = _best_col(df, _DESC_PATTERNS)
    area_col = _best_col(df, _AREA_PATTERNS)

    if not desc_col:
        raise ValueError(
            f"Could not detect a description column in {path.name}. "
            f"Columns found: {list(df.columns)}"
        )

    reqs = []
    for idx, row in df.iterrows():
        desc = str(row[desc_col]).strip()
        if not desc or desc.lower() in ("nan", "none", ""):
            continue

        req_id = (
            str(row[id_col]).strip()
            if id_col and pd.notna(row[id_col])
            else f"REQ_{idx + 1:03d}"
        )
        area = (
            str(row[area_col]).strip()
            if area_col and pd.notna(row[area_col])
            else ""
        )

        reqs.append({"id": req_id, "description": desc, "area": area})

    logger.info("Excel: extracted %d requirements from %s", len(reqs), path.name)
    return reqs


# ── PDF extraction ────────────────────────────────────────────────────────────

def _parse_pdf_table(table: list[list]) -> list[dict[str, Any]]:
    """Convert a pdfplumber table (list of lists) to requirement dicts."""
    if not table or len(table) < 2:
        return []

    # First row is assumed to be the header
    headers = [str(h).strip() if h else "" for h in table[0]]
    id_idx   = next((i for i, h in enumerate(headers) if _ID_PATTERNS.search(h)), None)
    desc_idx = next((i for i, h in enumerate(headers) if _DESC_PATTERNS.search(h)), None)
    area_idx = next((i for i, h in enumerate(headers) if _AREA_PATTERNS.search(h)), None)

    if desc_idx is None:
        return []

    reqs = []
    for row_num, row in enumerate(table[1:], start=1):
        desc = str(row[desc_idx]).strip() if desc_idx < len(row) else ""
        if not desc or desc.lower() in ("nan", "none", ""):
            continue

        req_id = (
            str(row[id_idx]).strip()
            if id_idx is not None and id_idx < len(row)
            else f"REQ_{row_num:03d}"
        )
        area = (
            str(row[area_idx]).strip()
            if area_idx is not None and area_idx < len(row)
            else ""
        )
        reqs.append({"id": req_id, "description": desc, "area": area})

    return reqs


def extract_pdf(path: Path) -> list[dict[str, Any]]:
    reqs: list[dict[str, Any]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                reqs.extend(_parse_pdf_table(table))

    if not reqs:
        logger.warning(
            "PDF table extraction yielded 0 requirements. "
            "The PDF may not contain structured tables — consider pre-converting to Excel."
        )

    logger.info("PDF: extracted %d requirements from %s", len(reqs), path.name)
    return reqs


# ── Main ──────────────────────────────────────────────────────────────────────

def extract(input_path: str | Path, output_dir: str | Path = "output") -> Path:
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    suffix = input_path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        reqs = extract_excel(input_path)
    elif suffix == ".pdf":
        reqs = extract_pdf(input_path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}. Expected .xlsx, .xls, or .pdf")

    out_path = output_dir / "reqs_raw.json"
    out_path.write_text(json.dumps(reqs, ensure_ascii=False, indent=2))
    logger.info("Saved %d requirements to %s", len(reqs), out_path)
    return out_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(sys.argv) < 2:
        print("Usage: python 01_extract.py <input_file> [output_dir]")
        sys.exit(1)
    out = extract(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "output")
    print(f"Extracted → {out}")
