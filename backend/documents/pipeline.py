"""Parse uploaded files and run deterministic extraction and reconciliation."""
from __future__ import annotations

from pathlib import Path

from domain import ExtractionResult, ParsedDocument
from documents.document_normalizer import extract_facts
from documents.excel_parser import parse_csv, parse_xls, parse_xlsx
from documents.pdf_parser import parse_pdf
from documents.reconciliation import reconcile
from documents.text_parser import parse_txt
from documents.word_parser import parse_doc, parse_docx

PARSERS = {
    "pdf": parse_pdf,
    "docx": parse_docx,
    "doc": parse_doc,
    "xlsx": parse_xlsx,
    "xls": parse_xls,
    "csv": parse_csv,
    "txt": parse_txt,
}


def parse_file(path: Path, file_id: str, file_name: str, file_type: str) -> ParsedDocument:
    parser = PARSERS.get(file_type)
    if parser is None:
        doc = ParsedDocument(file_id=file_id, file_name=file_name, file_type=file_type)
        doc.warnings.append(f"Unsupported file type: {file_type}")
        return doc
    try:
        return parser(path, file_id, file_name)
    except Exception as exc:  # A broken file must not stop the investigation.
        doc = ParsedDocument(file_id=file_id, file_name=file_name, file_type=file_type)
        doc.warnings.append(f"Could not read this file: {type(exc).__name__}: {exc}")
        return doc


def extract_all(documents: list[ParsedDocument]) -> ExtractionResult:
    facts, issues, meta = extract_facts(documents)
    return reconcile(facts, issues, meta)
