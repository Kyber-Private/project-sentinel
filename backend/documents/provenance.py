"""Helpers for building source references, value parsing, and text chunking."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

from domain import DocumentBlock, SourceRef

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_NUM_RE = re.compile(r"^\(?-?\s*[$€£]?\s*-?[\d,]*\.?\d+\s*(k|m|mm|bn|b)?\)?%?$", re.I)


def parse_number(value: Any) -> Optional[float]:
    """Parse a cell or text token into a float. Returns None when not numeric.

    Handles currency symbols, thousands separators, parentheses negatives,
    percent signs, and k/m suffixes. Never evaluates formulas.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value != value:  # NaN
            return None
        return float(value)
    s = str(value).strip()
    if not s or s.startswith("="):
        return None
    s = s.replace("USD", "").replace("US$", "$").replace("EUR", "").replace("GBP", "").strip()
    if not _NUM_RE.match(s.replace(" ", "")):
        return None
    neg = s.startswith("(") and s.endswith(")") or "-" in s
    pct = s.endswith("%")
    mult = 1.0
    m = re.search(r"(k|m|mm|bn|b)\)?%?$", s, re.I)
    if m:
        suffix = m.group(1).lower()
        mult = {"k": 1e3, "m": 1e6, "mm": 1e6, "bn": 1e9, "b": 1e9}[suffix]
    digits = re.sub(r"[^\d.]", "", s)
    if not digits or digits == ".":
        return None
    try:
        num = float(digits) * mult
    except ValueError:
        return None
    if neg:
        num = -num
    return num


def is_percent_text(value: Any) -> bool:
    return isinstance(value, str) and value.strip().endswith("%")


def parse_period(value: Any) -> Optional[str]:
    """Normalize a month reference to YYYY-MM. Returns None when not a month."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return f"{value.year:04d}-{value.month:02d}"
    if isinstance(value, date):
        return f"{value.year:04d}-{value.month:02d}"
    s = str(value).strip()
    if not s:
        return None
    m = re.match(r"^(\d{4})[-/](\d{1,2})(?:[-/]\d{1,2})?(?:[ T].*)?$", s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return f"{y:04d}-{mo:02d}"
    m = re.match(r"^(\d{1,2})[-/](\d{4})$", s)
    if m:
        mo, y = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return f"{y:04d}-{mo:02d}"
    m = re.match(r"^([A-Za-z]{3,9})\.?[\s\-']*(\d{2,4})$", s)
    if m and m.group(1).lower() in MONTHS:
        y = int(m.group(2))
        if y < 100:
            y += 2000
        return f"{y:04d}-{MONTHS[m.group(1).lower()]:02d}"
    return None


def parse_date(value: Any) -> Optional[str]:
    """Normalize a date to ISO YYYY-MM-DD where possible."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value).strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
        except ValueError:
            return None
    m = re.match(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})$", s)
    if m and m.group(1).lower() in MONTHS:
        try:
            return date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
        except ValueError:
            return None
    return None


def chunk_text(text: str, max_chars: int = 3000) -> list[str]:
    """Split text on paragraph boundaries into chunks of at most max_chars."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for p in paragraphs:
        if len(p) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(p), max_chars):
                chunks.append(p[i : i + max_chars])
            continue
        if len(current) + len(p) + 2 > max_chars and current:
            chunks.append(current)
            current = p
        else:
            current = f"{current}\n\n{p}" if current else p
    if current:
        chunks.append(current)
    return chunks


def split_grid_into_tables(
    grid: list[list[Any]],
    row_offset: int = 1,
) -> tuple[list[tuple[list[str], list[list[Any]], list[int]]], list[tuple[int, str]]]:
    """Split a 2D grid (e.g. a worksheet) into tables separated by blank rows.

    Returns (tables, loose_text_rows). Each table is (columns, rows, row_numbers)
    where row_numbers are the original 1-based spreadsheet row numbers.
    A header row is the first row of a block that has at least two text cells
    and is followed by at least one row containing a number.
    """
    tables: list[tuple[list[str], list[list[Any]], list[int]]] = []
    loose: list[tuple[int, str]] = []

    def nonempty(row: list[Any]) -> list[Any]:
        return [c for c in row if c is not None and str(c).strip() != ""]

    blocks: list[list[tuple[int, list[Any]]]] = []
    current: list[tuple[int, list[Any]]] = []
    for idx, row in enumerate(grid):
        if not nonempty(row):
            if current:
                blocks.append(current)
                current = []
            continue
        current.append((idx + row_offset, list(row)))
    if current:
        blocks.append(current)

    for block in blocks:
        header_idx = None
        for i, (_, row) in enumerate(block):
            cells = nonempty(row)
            text_cells = [c for c in cells if isinstance(c, str) and parse_number(c) is None]
            if len(text_cells) >= 2 and len(cells) >= 2:
                following = block[i + 1 : i + 4]
                if any(
                    any(parse_number(c) is not None or isinstance(c, (datetime, date)) for c in r)
                    for _, r in following
                ):
                    header_idx = i
                    break
        if header_idx is None:
            for rn, row in block:
                loose.append((rn, " ".join(str(c) for c in nonempty(row))))
            continue
        for rn, row in block[:header_idx]:
            loose.append((rn, " ".join(str(c) for c in nonempty(row))))
        header_row = block[header_idx][1]
        # Determine used column span.
        used = [j for j, c in enumerate(header_row) if c is not None and str(c).strip() != ""]
        first, last = min(used), max(used)
        columns = [str(header_row[j]).strip() if header_row[j] is not None else f"Column {j+1}" for j in range(first, last + 1)]
        rows, numbers = [], []
        for rn, row in block[header_idx + 1 :]:
            padded = list(row) + [None] * (last + 1 - len(row))
            rows.append(padded[first : last + 1])
            numbers.append(rn)
        tables.append((columns, rows, numbers))
    return tables, loose


def make_text_blocks(text: str, source: SourceRef, max_chars: int = 3000) -> list[DocumentBlock]:
    return [
        DocumentBlock(kind="text", source=source, text=chunk)
        for chunk in chunk_text(text, max_chars=max_chars)
    ]
