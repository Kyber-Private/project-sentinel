"""Spreadsheet and CSV extraction with sheet and row provenance.

Formulas are never evaluated. For XLSX we read cached values only
(openpyxl data_only=True). A formula cell without a cached value is reported.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from domain import DocumentBlock, ParsedDocument, SourceRef
from documents.provenance import split_grid_into_tables


def _blocks_from_grid(
    grid: list[list[Any]], file_id: str, file_name: str, sheet: str | None
) -> list[DocumentBlock]:
    blocks: list[DocumentBlock] = []
    tables, loose = split_grid_into_tables(grid)
    for t_index, (columns, rows, numbers) in enumerate(tables, start=1):
        blocks.append(
            DocumentBlock(
                kind="table",
                source=SourceRef(
                    file_id=file_id,
                    file_name=file_name,
                    sheet=sheet,
                    record_id=f"table {t_index}" if len(tables) > 1 else None,
                ),
                title=sheet,
                columns=columns,
                rows=rows,
                row_numbers=numbers,
            )
        )
    if loose:
        text = "\n".join(t for _, t in loose)
        blocks.append(
            DocumentBlock(
                kind="text",
                source=SourceRef(file_id=file_id, file_name=file_name, sheet=sheet, row=loose[0][0]),
                text=text,
            )
        )
    return blocks


def parse_xlsx(path: Path, file_id: str, file_name: str) -> ParsedDocument:
    import openpyxl

    doc = ParsedDocument(file_id=file_id, file_name=file_name, file_type="xlsx")
    wb_values = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    wb_formulas = openpyxl.load_workbook(str(path), data_only=False, read_only=True)
    for ws in wb_values.worksheets:
        grid = [list(row) for row in ws.iter_rows(values_only=True)]
        # Detect formulas with no cached value (never evaluated by Sentinel).
        try:
            fws = wb_formulas[ws.title]
            missing = 0
            for r_idx, row in enumerate(fws.iter_rows(values_only=True)):
                for c_idx, cell in enumerate(row):
                    if isinstance(cell, str) and cell.startswith("="):
                        if r_idx < len(grid) and c_idx < len(grid[r_idx]) and grid[r_idx][c_idx] is None:
                            missing += 1
            if missing:
                doc.warnings.append(
                    f"Sheet '{ws.title}': {missing} formula cell(s) had no saved value and were ignored. "
                    "Open and re-save the workbook in Excel to store calculated values."
                )
        except Exception:  # pragma: no cover
            pass
        doc.blocks.extend(_blocks_from_grid(grid, file_id, file_name, ws.title))
    wb_values.close()
    wb_formulas.close()
    return doc


def parse_xls(path: Path, file_id: str, file_name: str) -> ParsedDocument:
    import xlrd

    doc = ParsedDocument(file_id=file_id, file_name=file_name, file_type="xls")
    book = xlrd.open_workbook(str(path))
    for sheet in book.sheets():
        grid: list[list[Any]] = []
        for r in range(sheet.nrows):
            row = []
            for c in range(sheet.ncols):
                cell = sheet.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    row.append(xlrd.xldate.xldate_as_datetime(cell.value, book.datemode))
                elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    row.append(None)
                else:
                    row.append(cell.value)
            grid.append(row)
        doc.blocks.extend(_blocks_from_grid(grid, file_id, file_name, sheet.name))
    return doc


def parse_csv(path: Path, file_id: str, file_name: str) -> ParsedDocument:
    doc = ParsedDocument(file_id=file_id, file_name=file_name, file_type="csv")
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    grid = [row for row in csv.reader(io.StringIO(text), dialect)]
    # Treat values as untrusted text: strip leading formula characters.
    clean = [[(c[1:] if c.startswith("=") else c) for c in row] for row in grid]
    doc.blocks.extend(_blocks_from_grid(clean, file_id, file_name, None))
    return doc
