"""PDF extraction with page-level provenance.

Text comes from PyMuPDF. Tables come from pdfplumber. Pages with almost no
extractable text are flagged so the Data Analyst agent can send the original
PDF to the model's file input (useful for scanned documents).
"""
from __future__ import annotations

from pathlib import Path

from domain import DocumentBlock, ParsedDocument, SourceRef
from documents.provenance import make_text_blocks

MIN_TEXT_CHARS_PER_PAGE = 40


def parse_pdf(path: Path, file_id: str, file_name: str) -> ParsedDocument:
    doc = ParsedDocument(file_id=file_id, file_name=file_name, file_type="pdf")
    try:
        import pymupdf as fitz  # PyMuPDF
    except ImportError:  # pragma: no cover
        fitz = None

    page_texts: list[str] = []
    if fitz is not None:
        with fitz.open(str(path)) as pdf:
            doc.page_count = pdf.page_count
            for page in pdf:
                page_texts.append(page.get_text("text") or "")
    else:  # pragma: no cover - fallback path
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        doc.page_count = len(reader.pages)
        page_texts = [(p.extract_text() or "") for p in reader.pages]

    sparse_pages = 0
    for i, text in enumerate(page_texts, start=1):
        src = SourceRef(file_id=file_id, file_name=file_name, page=i)
        if len(text.strip()) < MIN_TEXT_CHARS_PER_PAGE:
            sparse_pages += 1
            continue
        doc.blocks.extend(make_text_blocks(text, src))

    # Tables via pdfplumber.
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                for t_index, table in enumerate(page.extract_tables() or [], start=1):
                    if not table or len(table) < 2:
                        continue
                    header = [str(c).strip() if c is not None else "" for c in table[0]]
                    if sum(1 for h in header if h) < 2:
                        continue
                    rows = [list(r) for r in table[1:]]
                    doc.blocks.append(
                        DocumentBlock(
                            kind="table",
                            source=SourceRef(
                                file_id=file_id,
                                file_name=file_name,
                                page=i,
                                record_id=f"table {t_index}",
                            ),
                            title=f"Page {i} table {t_index}",
                            columns=header,
                            rows=rows,
                            # Row numbers within the table (header is row 1).
                            row_numbers=list(range(2, len(rows) + 2)),
                        )
                    )
    except Exception as exc:  # pragma: no cover - defensive
        doc.warnings.append(f"Table extraction failed: {exc}")

    if doc.page_count and sparse_pages == doc.page_count:
        doc.needs_visual_extraction = True
        doc.warnings.append(
            "No extractable text found. This PDF may be scanned. "
            "Visual extraction requires the AI agents to be configured."
        )
    elif sparse_pages:
        doc.warnings.append(f"{sparse_pages} page(s) had little or no extractable text.")
    return doc
