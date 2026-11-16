"""Word document extraction (DOCX, and DOC through LibreOffice when installed)."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from domain import DocumentBlock, ParsedDocument, SourceRef
from documents.provenance import chunk_text


def parse_docx(path: Path, file_id: str, file_name: str) -> ParsedDocument:
    from docx import Document

    doc = ParsedDocument(file_id=file_id, file_name=file_name, file_type="docx")
    word = Document(str(path))

    # Paragraph text, chunked, keeping paragraph index ranges as record ids.
    paragraphs = [(i, p.text.strip()) for i, p in enumerate(word.paragraphs, start=1) if p.text.strip()]
    buffer: list[tuple[int, str]] = []
    size = 0

    def flush() -> None:
        nonlocal buffer, size
        if not buffer:
            return
        start, end = buffer[0][0], buffer[-1][0]
        text = "\n\n".join(t for _, t in buffer)
        for chunk in chunk_text(text):
            doc.blocks.append(
                DocumentBlock(
                    kind="text",
                    source=SourceRef(
                        file_id=file_id,
                        file_name=file_name,
                        record_id=f"paragraphs {start}-{end}",
                    ),
                    text=chunk,
                )
            )
        buffer, size = [], 0

    for idx, text in paragraphs:
        if size + len(text) > 3000:
            flush()
        buffer.append((idx, text))
        size += len(text)
    flush()

    for t_index, table in enumerate(word.tables, start=1):
        grid = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        if len(grid) < 2:
            continue
        doc.blocks.append(
            DocumentBlock(
                kind="table",
                source=SourceRef(file_id=file_id, file_name=file_name, record_id=f"table {t_index}"),
                title=f"Table {t_index}",
                columns=grid[0],
                rows=grid[1:],
                row_numbers=list(range(2, len(grid) + 1)),
            )
        )
    return doc


def parse_doc(path: Path, file_id: str, file_name: str) -> ParsedDocument:
    """Legacy .doc support. Only reliable when LibreOffice is installed."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        doc = ParsedDocument(file_id=file_id, file_name=file_name, file_type="doc")
        doc.warnings.append(
            "Legacy .doc files need LibreOffice for reliable conversion, which is not installed. "
            "Please save the file as .docx and upload it again."
        )
        return doc
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "docx", "--outdir", tmp, str(path)],
            check=True,
            timeout=120,
            capture_output=True,
        )
        converted = next(Path(tmp).glob("*.docx"), None)
        if converted is None:
            doc = ParsedDocument(file_id=file_id, file_name=file_name, file_type="doc")
            doc.warnings.append("Conversion of .doc to .docx failed.")
            return doc
        parsed = parse_docx(converted, file_id, file_name)
        parsed.file_type = "doc"
        return parsed
