"""Document extraction, provenance, conflicts, duplicates, and untrusted content."""
from pathlib import Path

import pytest

from documents.document_normalizer import extract_facts
from documents.pipeline import extract_all, parse_file
from documents.provenance import parse_number, parse_period
from documents.reconciliation import reconcile
from documents.security import FileValidationError, validate_file


def by_file(docs, suffix):
    return next(d for d in docs if d.file_name.endswith(suffix))


def test_pdf_extraction_text_and_tables(parsed_docs):
    pdf = by_file(parsed_docs, ".pdf")
    assert pdf.page_count == 2
    texts = [b for b in pdf.blocks if b.kind == "text"]
    tables = [b for b in pdf.blocks if b.kind == "table"]
    assert any("Project Beacon now stands at $325,000" in b.text.replace("\n", " ") for b in texts)
    assert all(b.source.page in (1, 2) for b in pdf.blocks)
    assert len(tables) == 2 and tables[0].columns == ["Month", "Revenue", "Operating Expenses"]


def test_docx_extraction(parsed_docs):
    docx = by_file(parsed_docs, ".docx")
    table = next(b for b in docx.blocks if b.kind == "table")
    assert table.columns[0] == "PO Number"
    assert table.rows[0][0] == "PO-4471"
    assert any("12%" in (b.text or "") for b in docx.blocks if b.kind == "text")


def test_xlsx_extraction_keeps_sheet_and_row(parsed_docs):
    xlsx = by_file(parsed_docs, "Financials_FY2026.xlsx")
    sheets = {b.source.sheet for b in xlsx.blocks}
    assert {"Monthly P&L", "Opex Breakdown", "Cash"} <= sheets
    pl = next(b for b in xlsx.blocks if b.kind == "table" and b.source.sheet == "Monthly P&L")
    assert pl.row_numbers[0] == 5  # header on row 4, data starts on row 5


def test_csv_extraction(parsed_docs):
    csv_doc = by_file(parsed_docs, ".csv")
    t = csv_doc.blocks[0]
    assert t.columns[0] == "Invoice No" and len(t.rows) == 11 and t.row_numbers[0] == 2


def test_source_reference_preservation(extraction):
    rev = [f for f in extraction.active_facts() if f.metric == "revenue" and f.period == "2026-10"]
    assert len(rev) == 1
    src = rev[0].source
    assert src.file_name == "Nova_Industries_Financials_FY2026.xlsx" and src.sheet == "Monthly P&L" and src.row == 16
    assert rev[0].value == 1284000
    # The board report PDF carries the same figure and is kept as corroboration.
    assert any(c.file_name.endswith(".pdf") and c.page == 1 for c in rev[0].corroborating_sources)
    revised = next(f for f in extraction.facts if f.metric == "budget_revised")
    assert revised.source.page == 2 and "$325,000" in revised.source.excerpt


def test_conflicting_records_detected(extraction):
    budget = [c for c in extraction.conflicts if c.metric == "budget"]
    assert len(budget) == 1
    assert sorted(budget[0].values) == [300000, 325000]
    assert budget[0].entity == "Project Beacon"
    # No false conflicts from figures that agree.
    assert len(extraction.conflicts) == 1


def test_duplicates_not_double_counted(extraction):
    exact_inv = [d for d in extraction.duplicates if "INV-K-2291" in d.description]
    assert exact_inv and exact_inv[0].kind == "exact"
    uncertain = [d for d in extraction.duplicates if d.kind == "uncertain"]
    assert len(uncertain) == 1 and "Apex Conveyors" in uncertain[0].description
    active_invoices = [f for f in extraction.active_facts() if f.metric == "supplier_invoice"]
    assert len(active_invoices) == 11  # 11 in the ledger; the 3 in the PDF are duplicates
    oct_revenue = [f for f in extraction.active_facts() if f.metric == "revenue" and f.period == "2026-10"]
    assert len(oct_revenue) == 1


def test_missing_fields_reported(parsed_docs, tmp_path):
    p = tmp_path / "gappy.csv"
    p.write_text("Month,Revenue\nJan 2026,100\nFeb 2026,110\nApr 2026,120\nMay 2026,130\n")
    doc = parse_file(p, "g1", p.name, "csv")
    ex = extract_all([doc])
    assert any("1 month(s) missing" in i.message for i in ex.issues)


def test_embedded_instructions_are_flagged_not_followed(extraction):
    hits = [i for i in extraction.issues if "instruction to an AI system" in i.message]
    assert hits and "ignore previous instructions" in hits[0].message


def test_projects_linked_by_id_and_name(extraction):
    assert extraction.projects == ["Project Alpha", "Project Beacon"]
    po = [f for f in extraction.active_facts() if f.metric == "open_purchase_order"]
    assert {f.attributes["project"] for f in po} == {"Project Alpha", "Project Beacon"}
    assert all(f.entity == "Kessler Steel Supply" for f in po)


def test_currency_detected(extraction):
    assert extraction.currency == "USD"
    assert extraction.currency_evidence


@pytest.mark.parametrize("raw,expected", [
    ("$1,234", 1234.0), ("(1,500)", -1500.0), ("12%", 12.0), ("1.2M", 1_200_000.0), ("abc", None), ("=SUM(A1:A3)", None),
])
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize("raw,expected", [("Nov 2025", "2025-11"), ("2026-03-01", "2026-03"), ("03/2026", "2026-03"), ("Q3 2026", None)])
def test_parse_period(raw, expected):
    assert parse_period(raw) == expected


def test_file_validation_rejects_bad_files(tmp_path):
    fake = tmp_path / "report.pdf"
    fake.write_bytes(b"not a pdf")
    with pytest.raises(FileValidationError):
        validate_file(fake, "report.pdf")
    exe = tmp_path / "x.exe"
    exe.write_bytes(b"MZ")
    with pytest.raises(FileValidationError):
        validate_file(exe, "x.exe")


def test_csv_formula_cells_are_not_executed(tmp_path):
    p = tmp_path / "f.csv"
    p.write_text("Month,Revenue\nJan 2026,=1+1\nFeb 2026,200\n")
    doc = parse_file(p, "f1", p.name, "csv")
    facts, _, _ = extract_facts([doc])
    values = [f.value for f in facts if f.metric == "revenue"]
    assert 2 not in values and 200 in values


def test_reconcile_corroborates_matching_values(parsed_docs):
    facts, issues, meta = extract_facts(parsed_docs)
    ex = reconcile(facts, issues, meta)
    opex_oct = next(f for f in ex.active_facts() if f.metric == "operating_expenses" and f.period == "2026-10")
    assert len(opex_oct.corroborating_sources) == 2  # PDF table and PDF text
