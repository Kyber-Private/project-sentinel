"""Plain text extraction. Each paragraph keeps its starting line number."""
from __future__ import annotations

from pathlib import Path

from domain import DocumentBlock, ParsedDocument, SourceRef


def parse_txt(path: Path, file_id: str, file_name: str) -> ParsedDocument:
    doc = ParsedDocument(file_id=file_id, file_name=file_name, file_type="txt")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    lines = text.splitlines()
    para: list[str] = []
    start = 1
    for i, line in enumerate(lines + [""], start=1):
        if line.strip():
            if not para:
                start = i
            para.append(line)
            continue
        if para:
            doc.blocks.append(
                DocumentBlock(
                    kind="text",
                    source=SourceRef(file_id=file_id, file_name=file_name, row=start),
                    text="\n".join(para),
                )
            )
            para = []
    return doc
