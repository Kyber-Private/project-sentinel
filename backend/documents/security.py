"""File validation and untrusted-content checks."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".txt"}

INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) instructions",
    r"disregard (the |all )?(previous|prior|system)",
    r"\bsystem prompt\b",
    r"you are now",
    r"act as (an? )?(assistant|ai|model)",
    r"\bSYSTEM:\s",
    r"override (your|the) (instructions|rules)",
    r"report (record|higher|inflated) (profits?|revenue)",
]


class FileValidationError(ValueError):
    pass


def validate_file(path: Path, original_name: str) -> str:
    """Check extension and magic bytes. Returns the normalized file type."""
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise FileValidationError(
            f"'{original_name}' is not a supported file type. Use PDF, DOCX, DOC, XLSX, XLS, CSV, or TXT."
        )
    head = path.read_bytes()[:8]
    if ext == ".pdf" and not head.startswith(b"%PDF"):
        raise FileValidationError(f"'{original_name}' does not look like a valid PDF.")
    if ext in (".docx", ".xlsx"):
        if not zipfile.is_zipfile(path):
            raise FileValidationError(f"'{original_name}' is not a valid {ext[1:].upper()} file.")
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if ext == ".docx" and "word/document.xml" not in names:
                raise FileValidationError(f"'{original_name}' is not a valid Word document.")
            if ext == ".xlsx" and "xl/workbook.xml" not in names:
                raise FileValidationError(f"'{original_name}' is not a valid Excel workbook.")
            if any(n.lower().endswith("vbaproject.bin") for n in names):
                raise FileValidationError(f"'{original_name}' contains macros, which are not accepted.")
    if ext in (".doc", ".xls") and not head.startswith(b"\xd0\xcf\x11\xe0"):
        raise FileValidationError(f"'{original_name}' is not a valid legacy Office file.")
    if ext in (".csv", ".txt"):
        sample = path.read_bytes()[:4096]
        if b"\x00" in sample:
            raise FileValidationError(f"'{original_name}' appears to be binary, not text.")
    return ext[1:]


def find_embedded_instructions(text: str) -> list[str]:
    """Return lines that look like instructions aimed at an AI system.

    These are treated as data. Sentinel never follows them; it reports them.
    """
    hits = []
    for line in text.splitlines():
        for pat in INJECTION_PATTERNS:
            if re.search(pat, line, re.I):
                hits.append(line.strip()[:200])
                break
    return hits
