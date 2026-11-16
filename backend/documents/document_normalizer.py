"""Turn parsed document blocks into normalized financial facts with provenance.

This is deterministic application-level extraction. It handles structured
tables (spreadsheets, CSV, Word and PDF tables) and a set of conservative
text patterns. The Data Analyst agent adds facts from free text on top of
this, and those facts are verified against the source text before use.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional

from domain import DataQualityIssue, DocumentBlock, Fact, ParsedDocument, SourceRef
from documents.provenance import MONTHS, parse_date, parse_number, parse_period
from documents.security import find_embedded_instructions

# ---------------------------------------------------------------------------
# Header vocabulary
# ---------------------------------------------------------------------------
COMPANY_HEADERS: dict[str, list[str]] = {
    "revenue": ["revenue", "sales", "total revenue", "net sales", "net revenue", "turnover"],
    "cogs": ["cost of goods sold", "cogs", "cost of sales", "direct costs"],
    "gross_profit": ["gross profit"],
    "operating_expenses": [
        "operating expenses", "opex", "total operating expenses", "total opex", "operating costs",
    ],
    "operating_profit": ["operating profit", "operating income", "ebit"],
    "net_profit": ["net profit", "net income"],
    "cash_balance": ["cash balance", "closing cash", "ending cash", "cash", "closing cash balance"],
    "cash_flow": ["net cash flow", "cash flow"],
    "accounts_receivable": ["accounts receivable", "receivables"],
    "accounts_payable": ["accounts payable", "payables"],
    "debt": ["debt", "borrowings", "loan balance"],
}
PROJECT_HEADERS: dict[str, list[str]] = {
    "budget_approved": ["approved budget", "budget approved", "original budget", "bac"],
    "budget_revised": ["revised budget"],
    "actual_cost": [
        "actual cost", "actual to date", "actual spend", "spent to date", "actual cost to date",
        "costs to date", "actual costs to date", "actual spend to date",
    ],
    "committed_cost": [
        "remaining commitments", "open commitments", "committed", "committed cost",
        "open po value", "committed not invoiced",
    ],
    "forecast_at_completion": [
        "forecast at completion", "fac", "eac", "estimate at completion", "forecast final cost",
        "forecast cost at completion",
    ],
    "estimate_to_complete": ["estimate to complete", "etc", "cost to complete"],
    "percent_complete": ["percent complete", "% complete", "progress", "completion %", "pct complete"],
    "start_date": ["start date", "start"],
    "planned_completion": [
        "planned completion", "planned end", "planned finish", "baseline completion", "planned completion date",
    ],
    "forecast_completion": [
        "forecast completion", "forecast end", "expected completion", "forecast finish", "forecast completion date",
    ],
    "actual_completion": ["actual completion", "completed on"],
    "contract_value": ["contract value"],
    "project_revenue": ["project revenue"],
}
AMBIGUOUS_PROJECT_HEADERS = {"budget": "budget_approved", "forecast": "forecast_at_completion"}
PERIOD_HEADERS = ["month", "period", "reporting period", "month ending", "month end", "date"]
PROJECT_KEY_HEADERS = ["project", "project name"]
PROJECT_ID_HEADERS = ["project id", "project code", "project ref", "id", "code"]
SUPPLIER_HEADERS = ["supplier", "vendor", "supplier name", "vendor name"]
INVOICE_HEADERS = ["invoice", "invoice #", "invoice no", "invoice number", "invoice id"]
PO_HEADERS = ["po", "po number", "po #", "purchase order", "purchase order #"]
AMOUNT_HEADERS = [
    "amount", "value", "total", "cost", "invoice amount", "open value", "open po value",
    "remaining value", "amount usd", "net amount",
]
MILESTONE_HEADERS = ["milestone", "milestone name"]
CHANGE_HEADERS = ["change request", "change request id", "cr", "cr id"]

CURRENCY_WORDS = {
    "usd": "USD", "us dollars": "USD", "u.s. dollars": "USD", "dollars": None,
    "eur": "EUR", "euros": "EUR", "euro": "EUR", "gbp": "GBP", "pounds sterling": "GBP",
    "cad": "CAD", "aud": "AUD",
}
SYMBOL_CURRENCY = {"€": "EUR", "£": "GBP"}


def norm_header(h: Any) -> str:
    s = str(h or "").strip().lower()
    s = re.sub(r"\((usd|\$|eur|gbp|€|£|us\$)\)", "", s)
    s = re.sub(r"\b(usd|in usd|\$)\b", "", s)
    s = s.replace("$", "")
    s = re.sub(r"[^a-z0-9%# ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def match_header(h: str, vocab: dict[str, list[str]]) -> Optional[str]:
    """Exact match first, then the longest synonym contained in the header."""
    for key, syns in vocab.items():
        if h in syns:
            return key
    best: tuple[int, Optional[str]] = (0, None)
    for key, syns in vocab.items():
        for s in syns:
            if len(s) >= 5 and re.search(rf"\b{re.escape(s)}\b", h) and len(s) > best[0]:
                best = (len(s), key)
    return best[1]


def in_list(h: str, options: list[str]) -> bool:
    return h in options


def header_detected_currency(columns: list[str]) -> Optional[str]:
    for c in columns:
        low = str(c).lower()
        if "usd" in low or "us$" in low:
            return "USD"
        if "eur" in low or "€" in low:
            return "EUR"
        if "gbp" in low or "£" in low:
            return "GBP"
    return None


class Extractor:
    def __init__(self) -> None:
        self.facts: list[Fact] = []
        self.issues: list[DataQualityIssue] = []
        self.project_aliases: dict[str, str] = {}
        self.known_projects: set[str] = set()
        self.currency_hits: Counter = Counter()
        self.currency_evidence: list[str] = []
        self.dollar_symbol_seen = False
        self.company_names: Counter = Counter()

    # ------------------------------------------------------------------ utils
    def add(self, **kwargs: Any) -> Fact:
        fact = Fact(**kwargs)
        self.facts.append(fact)
        return fact

    def canon_project(self, raw: Any) -> Optional[str]:
        if raw is None:
            return None
        s = str(raw).strip()
        if not s:
            return None
        key = s.lower()
        if key in self.project_aliases:
            return self.project_aliases[key]
        return s

    def note_currency_from_cells(self, cells: list[Any]) -> None:
        for c in cells:
            if isinstance(c, str):
                if "$" in c:
                    self.dollar_symbol_seen = True
                for sym, cur in SYMBOL_CURRENCY.items():
                    if sym in c:
                        self.currency_hits[cur] += 1

    # --------------------------------------------------------------- tables
    def register_projects(self, block: DocumentBlock) -> None:
        """First pass: learn project names and IDs so later tables can link."""
        cols = [norm_header(c) for c in block.columns]
        name_idx = next((i for i, c in enumerate(cols) if c in PROJECT_KEY_HEADERS), None)
        id_idx = next((i for i, c in enumerate(cols) if c in ("project id", "project code", "project ref")), None)
        if name_idx is None:
            return
        for row in block.rows:
            name = str(row[name_idx]).strip() if name_idx < len(row) and row[name_idx] else ""
            if not name or parse_number(name) is not None:
                continue
            self.known_projects.add(name)
            self.project_aliases[name.lower()] = name
            if id_idx is not None and id_idx < len(row) and row[id_idx]:
                self.project_aliases[str(row[id_idx]).strip().lower()] = name

    def process_table(self, block: DocumentBlock, title_hint: str) -> None:
        cols_raw = block.columns
        cols = [norm_header(c) for c in cols_raw]
        currency = header_detected_currency(cols_raw)
        if currency:
            self.currency_hits[currency] += 1
            self.currency_evidence.append(f"{block.source.label()}: column headers state {currency}")
        for row in block.rows:
            self.note_currency_from_cells(row)

        idx = {c: i for i, c in enumerate(cols)}
        find = lambda options: next((i for i, c in enumerate(cols) if c in options), None)  # noqa: E731
        period_idx = find(PERIOD_HEADERS)
        project_idx = find(PROJECT_KEY_HEADERS)
        project_id_idx = find(["project id", "project code", "project ref"])
        if project_idx is None:
            project_idx = project_id_idx
        supplier_idx = find(SUPPLIER_HEADERS)
        invoice_idx = find(INVOICE_HEADERS)
        po_idx = find(PO_HEADERS)
        milestone_idx = find(MILESTONE_HEADERS)
        change_idx = find(CHANGE_HEADERS)
        amount_idx = find(AMOUNT_HEADERS)

        # Transposed layout: months across the columns, metrics down the rows.
        period_cols = [(i, parse_period(c)) for i, c in enumerate(cols_raw)]
        period_cols = [(i, p) for i, p in period_cols if p]
        if len(period_cols) >= 3 and period_idx is None:
            self._transposed_series(block, period_cols, title_hint, currency)
            return

        # If no period header, check whether the first column holds months.
        if period_idx is None and block.rows:
            first_vals = [r[0] for r in block.rows if r and r[0] is not None]
            if first_vals and sum(1 for v in first_vals if parse_period(v)) >= max(2, int(0.8 * len(first_vals))):
                period_idx = 0
        if period_idx is not None and cols[period_idx] == "date" and (invoice_idx is not None or po_idx is not None):
            period_idx = None  # an invoice date column is not a reporting period

        if milestone_idx is not None:
            self._milestones(block, cols, project_idx, milestone_idx)
        elif change_idx is not None:
            self._change_requests(block, cols, project_idx, change_idx, amount_idx, currency)
        elif invoice_idx is not None:
            self._invoices(block, cols, invoice_idx, supplier_idx, project_idx, amount_idx, currency)
        elif po_idx is not None:
            self._purchase_orders(block, cols, po_idx, supplier_idx, project_idx, amount_idx, currency)
        elif period_idx is not None and project_idx is not None:
            self._project_monthly(block, cols, period_idx, project_idx, amount_idx, currency)
        elif period_idx is not None:
            self._company_series(block, cols, period_idx, title_hint, currency)
        elif project_idx is not None:
            self._project_register(block, cols, project_idx, currency)
        elif supplier_idx is not None:
            self._supplier_table(block, cols, supplier_idx, currency)

    def _src(self, block: DocumentBlock, row_number: Optional[int], record: Optional[str] = None,
             excerpt: Optional[str] = None) -> SourceRef:
        src = block.source.model_copy()
        if block.source.page is not None or block.source.sheet is None and block.source.record_id:
            # PDF/DOCX tables: keep table id, row is the row within the table.
            src.row = row_number
        else:
            src.row = row_number
        if record:
            src.record_id = f"{block.source.record_id}, {record}" if block.source.record_id else record
        if excerpt:
            src.excerpt = excerpt[:300]
        return src

    @staticmethod
    def _row_excerpt(columns: list[str], row: list[Any]) -> str:
        parts = []
        for c, v in zip(columns, row):
            if v is None or str(v).strip() == "":
                continue
            if hasattr(v, "isoformat"):
                v = v.isoformat()[:10]
            parts.append(f"{c}: {v}")
        return " | ".join(parts)

    def _company_series(self, block, cols, period_idx, title_hint, currency) -> None:
        hint = f"{title_hint} {block.title or ''}".lower()
        is_breakdown = any(w in hint for w in ("breakdown", "expense", "opex", "cost"))
        for row, rn in zip(block.rows, block.row_numbers):
            period = parse_period(row[period_idx]) if period_idx < len(row) else None
            if not period:
                continue
            excerpt = self._row_excerpt(block.columns, row)
            for j, h in enumerate(cols):
                if j == period_idx or j >= len(row):
                    continue
                value = parse_number(row[j])
                if value is None:
                    continue
                metric = match_header(h, COMPANY_HEADERS)
                if metric and not (is_breakdown and metric == "cash_balance" and h != "cash balance"):
                    if is_breakdown and metric in ("operating_expenses",):
                        # Total row/column in a breakdown sheet.
                        pass
                    self.add(
                        entity_type="company", entity="__company__", metric=metric, period=period,
                        value=value, currency=currency, unit="currency",
                        qualifier="actual" if "forecast" not in hint and "budget" not in hint else "plan",
                        source=self._src(block, rn, excerpt=excerpt), extraction_method="table",
                    )
                elif h.startswith("project ") and h not in ("project id", "project name"):
                    project = self.canon_project(block.columns[j])
                    self.add(
                        entity_type="project", entity=project, metric="project_cost", period=period,
                        value=value, currency=currency, unit="currency", qualifier="actual",
                        source=self._src(block, rn, excerpt=excerpt), extraction_method="table",
                    )
                elif is_breakdown and h not in ("total",):
                    self.add(
                        entity_type="company", entity="__company__", metric="expense_category",
                        period=period, dimension=str(block.columns[j]).strip(), value=value,
                        currency=currency, unit="currency", qualifier="actual",
                        source=self._src(block, rn, excerpt=excerpt), extraction_method="table",
                    )

    def _transposed_series(self, block, period_cols, title_hint, currency) -> None:
        hint = f"{title_hint} {block.title or ''}".lower()
        is_breakdown = any(w in hint for w in ("breakdown", "expense", "opex"))
        for row, rn in zip(block.rows, block.row_numbers):
            label = norm_header(row[0]) if row else ""
            if not label:
                continue
            metric = match_header(label, COMPANY_HEADERS)
            excerpt = f"{row[0]}: " + ", ".join(
                f"{block.columns[i]}={row[i]}" for i, _ in period_cols if i < len(row)
            )
            for i, period in period_cols:
                if i >= len(row):
                    continue
                value = parse_number(row[i])
                if value is None:
                    continue
                if metric:
                    self.add(
                        entity_type="company", entity="__company__", metric=metric, period=period,
                        value=value, currency=currency, unit="currency", qualifier="actual",
                        source=self._src(block, rn, excerpt=excerpt), extraction_method="table",
                    )
                elif is_breakdown:
                    self.add(
                        entity_type="company", entity="__company__", metric="expense_category",
                        period=period, dimension=str(row[0]).strip(), value=value, currency=currency,
                        unit="currency", qualifier="actual",
                        source=self._src(block, rn, excerpt=excerpt), extraction_method="table",
                    )

    def _project_register(self, block, cols, project_idx, currency) -> None:
        for row, rn in zip(block.rows, block.row_numbers):
            project = self.canon_project(row[project_idx]) if project_idx < len(row) else None
            if not project or parse_number(project) is not None:
                continue
            self.known_projects.add(project)
            excerpt = self._row_excerpt(block.columns, row)
            for j, h in enumerate(cols):
                if j == project_idx or j >= len(row) or row[j] is None or str(row[j]).strip() == "":
                    continue
                metric = match_header(h, PROJECT_HEADERS)
                qualifier = None
                if not metric and h in AMBIGUOUS_PROJECT_HEADERS:
                    metric = AMBIGUOUS_PROJECT_HEADERS[h]
                    qualifier = "unlabeled"
                if not metric:
                    continue
                cell = row[j]
                if metric in ("start_date", "planned_completion", "forecast_completion", "actual_completion"):
                    d = parse_date(cell)
                    if d:
                        self.add(
                            entity_type="project", entity=project, metric=metric, text_value=d,
                            unit="date", source=self._src(block, rn, excerpt=excerpt),
                        )
                    continue
                value = parse_number(cell)
                if value is None:
                    continue
                if metric == "percent_complete":
                    if isinstance(cell, (int, float)) and value <= 1.0:
                        value *= 100
                    self.add(
                        entity_type="project", entity=project, metric=metric, value=value, unit="percent",
                        source=self._src(block, rn, excerpt=excerpt),
                    )
                    continue
                self.add(
                    entity_type="project", entity=project, metric=metric, value=value,
                    currency=currency, unit="currency",
                    qualifier=qualifier or ("approved" if metric == "budget_approved" else None),
                    source=self._src(block, rn, excerpt=excerpt),
                )
                if qualifier == "unlabeled":
                    self.issues.append(
                        DataQualityIssue(
                            severity="warning",
                            message=f"{block.source.label()}: the column '{block.columns[j]}' for {project} "
                            "does not say whether it is approved or forecast.",
                        )
                    )

    def _project_monthly(self, block, cols, period_idx, project_idx, amount_idx, currency) -> None:
        cost_idx = amount_idx
        if cost_idx is None:
            cost_idx = next(
                (j for j, h in enumerate(cols) if j not in (period_idx, project_idx) and "cost" in h), None
            )
        if cost_idx is None:
            return
        category_idx = next((j for j, h in enumerate(cols) if h in ("category", "cost type", "type")), None)
        for row, rn in zip(block.rows, block.row_numbers):
            period = parse_period(row[period_idx])
            project = self.canon_project(row[project_idx])
            value = parse_number(row[cost_idx]) if cost_idx < len(row) else None
            if not period or not project or value is None:
                continue
            self.add(
                entity_type="project", entity=project, metric="project_cost", period=period,
                dimension=str(row[category_idx]).strip() if category_idx is not None and row[category_idx] else None,
                value=value, currency=currency, unit="currency", qualifier="actual",
                source=self._src(block, rn, excerpt=self._row_excerpt(block.columns, row)),
            )

    def _invoices(self, block, cols, invoice_idx, supplier_idx, project_idx, amount_idx, currency) -> None:
        date_idx = next((j for j, h in enumerate(cols) if h in ("date", "invoice date")), None)
        if amount_idx is None:
            return
        for row, rn in zip(block.rows, block.row_numbers):
            amount = parse_number(row[amount_idx]) if amount_idx < len(row) else None
            if amount is None:
                continue
            inv = str(row[invoice_idx]).strip() if row[invoice_idx] not in (None, "") else None
            if inv in ("-", "n/a", "—", "None"):
                inv = None
            supplier = str(row[supplier_idx]).strip() if supplier_idx is not None and row[supplier_idx] else None
            project = self.canon_project(row[project_idx]) if project_idx is not None else None
            d = parse_date(row[date_idx]) if date_idx is not None else None
            self.add(
                entity_type="supplier", entity=supplier or "Unknown supplier", metric="supplier_invoice",
                dimension=inv, period=d[:7] if d else None, value=amount, currency=currency,
                unit="currency", qualifier="actual",
                source=self._src(block, rn, record=f"invoice {inv}" if inv else None,
                                 excerpt=self._row_excerpt(block.columns, row)),
                attributes={"project": project, "date": d, "invoice_id": inv},
            )

    def _purchase_orders(self, block, cols, po_idx, supplier_idx, project_idx, amount_idx, currency) -> None:
        if amount_idx is None:
            amount_idx = next((j for j, h in enumerate(cols) if "value" in h or "amount" in h), None)
        if amount_idx is None:
            return
        for row, rn in zip(block.rows, block.row_numbers):
            amount = parse_number(row[amount_idx]) if amount_idx < len(row) else None
            if amount is None:
                continue
            po = str(row[po_idx]).strip()
            supplier = str(row[supplier_idx]).strip() if supplier_idx is not None and row[supplier_idx] else None
            project = self.canon_project(row[project_idx]) if project_idx is not None else None
            self.add(
                entity_type="supplier", entity=supplier or "__document_supplier__",
                metric="open_purchase_order", dimension=po, value=amount, currency=currency,
                unit="currency", qualifier="open",
                source=self._src(block, rn, record=f"PO {po}", excerpt=self._row_excerpt(block.columns, row)),
                attributes={"project": project, "po": po},
            )

    def _milestones(self, block, cols, project_idx, milestone_idx) -> None:
        planned_idx = next((j for j, h in enumerate(cols) if "planned" in h or "baseline" in h), None)
        forecast_idx = next((j for j, h in enumerate(cols) if "forecast" in h or "expected" in h), None)
        actual_idx = next((j for j, h in enumerate(cols) if "actual" in h), None)
        status_idx = next((j for j, h in enumerate(cols) if h == "status"), None)
        for row, rn in zip(block.rows, block.row_numbers):
            project = self.canon_project(row[project_idx]) if project_idx is not None else "__unknown__"
            name = str(row[milestone_idx]).strip() if row[milestone_idx] else None
            if not name:
                continue
            attrs = {
                "planned": parse_date(row[planned_idx]) if planned_idx is not None else None,
                "forecast": parse_date(row[forecast_idx]) if forecast_idx is not None else None,
                "actual": parse_date(row[actual_idx]) if actual_idx is not None else None,
                "status": str(row[status_idx]).strip() if status_idx is not None and row[status_idx] else None,
            }
            self.add(
                entity_type="project", entity=project, metric="milestone", dimension=name,
                text_value=name, unit="text", attributes=attrs,
                source=self._src(block, rn, excerpt=self._row_excerpt(block.columns, row)),
            )

    def _change_requests(self, block, cols, project_idx, change_idx, amount_idx, currency) -> None:
        status_idx = next((j for j, h in enumerate(cols) if h == "status"), None)
        for row, rn in zip(block.rows, block.row_numbers):
            cr = str(row[change_idx]).strip() if row[change_idx] else None
            if not cr:
                continue
            project = self.canon_project(row[project_idx]) if project_idx is not None else "__unknown__"
            amount = parse_number(row[amount_idx]) if amount_idx is not None else None
            self.add(
                entity_type="project", entity=project, metric="change_request", dimension=cr,
                value=amount, currency=currency, unit="currency",
                qualifier=(str(row[status_idx]).strip().lower() if status_idx is not None and row[status_idx] else None),
                source=self._src(block, rn, record=cr, excerpt=self._row_excerpt(block.columns, row)),
            )

    def _supplier_table(self, block, cols, supplier_idx, currency) -> None:
        pct_idx = next((j for j, h in enumerate(cols) if "%" in h or "change" in h or "increase" in h), None)
        if pct_idx is None:
            return
        for row, rn in zip(block.rows, block.row_numbers):
            supplier = str(row[supplier_idx]).strip() if row[supplier_idx] else None
            value = parse_number(row[pct_idx])
            if not supplier or value is None:
                continue
            if abs(value) <= 1 and not str(row[pct_idx]).strip().endswith("%"):
                value *= 100
            self.add(
                entity_type="supplier", entity=supplier, metric="supplier_price_change_pct", value=value,
                unit="percent", source=self._src(block, rn, excerpt=self._row_excerpt(block.columns, row)),
            )

    # ------------------------------------------------------------------ text
    AMOUNT_RE = re.compile(
        r"(?P<cur>USD|US\$|\$|€|£|EUR|GBP)\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(?P<mult>million|thousand|m\b|k\b)?",
        re.I,
    )
    MONTH_RE = r"(?:" + "|".join(sorted(MONTHS.keys(), key=len, reverse=True)) + r")\.?\s+\d{4}"
    COMPANY_SENTENCE_RE = re.compile(
        r"(?P<metric>revenue|sales|operating expenses|operating profit|net profit|cash balance|gross profit)"
        r"\s+(?:for|in)\s+(?P<period>" + MONTH_RE + r")\s+(?:was|were|totaled|totalled|came in at|reached|of)\s+",
        re.I,
    )
    SUPPLIER_NAME_RE = re.compile(
        r"\b([A-Z][A-Za-z&]+(?:\s+[A-Z][A-Za-z&]+){0,3}\s+(?:Supply|Supplies|Steel|Ltd|Inc|LLC|Corp|GmbH|Limited|Components))\b"
    )
    COMPANY_NAME_RE = re.compile(
        r"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2})\s+(Industries|Inc\.?|LLC|Ltd\.?|Corporation|Corp\.?|Group|Holdings)\b"
    )
    NOTE_KEYWORDS = re.compile(
        r"\b(hire|hiring|hired|headcount|expansion|expand|cost reduction|layoff|contract|price increase|"
        r"delay|delayed|change request|risk|renegotiat|new customer|lost customer|churn)\w*",
        re.I,
    )

    @classmethod
    def amounts_in(cls, sentence: str) -> list[tuple[float, str]]:
        out = []
        for m in cls.AMOUNT_RE.finditer(sentence):
            num = parse_number(m.group("num"))
            if num is None:
                continue
            mult = (m.group("mult") or "").lower()
            if mult in ("million", "m"):
                num *= 1e6
            elif mult in ("thousand", "k"):
                num *= 1e3
            cur = m.group("cur").upper().replace("US$", "USD")
            out.append((num, cur))
        return out

    def process_text(self, block: DocumentBlock) -> None:
        text = block.text or ""
        for hit in find_embedded_instructions(text):
            self.issues.append(
                DataQualityIssue(
                    severity="warning",
                    message=f"{block.source.label()}: text that looks like an instruction to an AI system was found "
                    f"and ignored: \"{hit[:120]}\"",
                )
            )
        for m in self.COMPANY_NAME_RE.finditer(text):
            name = f"{m.group(1)} {m.group(2)}".strip()
            if not self.SUPPLIER_NAME_RE.search(name):
                self.company_names[name] += 1
        low = text.lower()
        for word, cur in CURRENCY_WORDS.items():
            if cur and re.search(rf"(amounts|figures|values|all numbers)[^.\n]{{0,40}}\b(in|expressed in)\s+{re.escape(word)}\b", low):
                self.currency_hits[cur] += 3
                self.currency_evidence.append(f"{block.source.label()}: states amounts are in {cur}")
        if "$" in text:
            self.dollar_symbol_seen = True
        for sym, cur in SYMBOL_CURRENCY.items():
            if sym in text:
                self.currency_hits[cur] += 1

        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n{2,}", text.replace("\r", "")) if s.strip()]
        notes_added = 0
        doc_suppliers = self.SUPPLIER_NAME_RE.findall(text)
        for sentence in sentences:
            flat = re.sub(r"\s+", " ", sentence)
            self._text_project_facts(block, flat)
            self._text_company_facts(block, flat)
            self._text_supplier_facts(block, flat, doc_suppliers)
            if notes_added < 25 and self.NOTE_KEYWORDS.search(flat) and 20 < len(flat) < 400:
                self.add(
                    entity_type="other", entity="__company__", metric="business_note", text_value=flat,
                    unit="text", source=block.source.model_copy(update={"excerpt": flat[:300]}),
                    extraction_method="text_pattern", confidence="medium",
                )
                notes_added += 1

    def _projects_in(self, sentence: str) -> list[str]:
        found = []
        for name in sorted(self.known_projects, key=len, reverse=True):
            if re.search(rf"\b{re.escape(name)}\b", sentence, re.I):
                found.append(name)
        if not found:
            for m in re.finditer(r"\bProject\s+[A-Z][A-Za-z0-9]+", sentence):
                found.append(m.group(0))
        return found

    def _text_project_facts(self, block: DocumentBlock, sentence: str) -> None:
        projects = self._projects_in(sentence)
        if len(projects) != 1:
            return  # ambiguous or none: leave to the Data Analyst agent
        project = self.canon_project(projects[0])
        amounts = self.amounts_in(sentence)
        if not amounts:
            return
        low = sentence.lower()
        src = block.source.model_copy(update={"excerpt": sentence[:300]})
        pending = bool(re.search(r"pending|awaiting|not yet approved|subject to (board |cfo )?approval|to be approved", low))
        if "budget" in low and len(amounts) == 1:
            value, cur = amounts[0]
            if re.search(r"revis|increas|now stands|updated|raised|new budget|now at", low):
                metric, qualifier = "budget_revised", "pending approval" if pending else "approval status unclear"
            elif "approved" in low and not pending:
                metric, qualifier = "budget_approved", "approved"
            else:
                metric, qualifier = "budget_revised", "mentioned"
            self.add(
                entity_type="project", entity=project, metric=metric, value=value,
                currency=None if cur == "$" else cur, unit="currency", qualifier=qualifier, source=src,
                extraction_method="text_pattern", confidence="medium",
            )
        elif re.search(r"forecast (final|total) cost|expected to cost|estimate at completion|forecast at completion", low) and len(amounts) == 1:
            value, cur = amounts[0]
            self.add(
                entity_type="project", entity=project, metric="forecast_at_completion", value=value,
                currency=None if cur == "$" else cur, unit="currency", qualifier="management forecast",
                source=src, extraction_method="text_pattern", confidence="medium",
            )

    def _text_company_facts(self, block: DocumentBlock, sentence: str) -> None:
        for m in self.COMPANY_SENTENCE_RE.finditer(sentence):
            tail = sentence[m.end():]
            amounts = self.amounts_in(tail[:40])
            if not amounts:
                continue
            metric_word = m.group("metric").lower()
            metric = {"sales": "revenue"}.get(metric_word, metric_word.replace(" ", "_"))
            period = parse_period(m.group("period"))
            value, cur = amounts[0]
            self.add(
                entity_type="company", entity="__company__", metric=metric, period=period, value=value,
                currency=None if cur == "$" else cur, unit="currency", qualifier="actual",
                source=block.source.model_copy(update={"excerpt": sentence[:300]}),
                extraction_method="text_pattern", confidence="medium",
            )

    def _text_supplier_facts(self, block: DocumentBlock, sentence: str, doc_suppliers: list[str]) -> None:
        low = sentence.lower()
        m = re.search(r"(\d+(?:\.\d+)?)\s?%\s+(?:price\s+)?increase", low) or re.search(
            r"increase[^.]{0,60}?\bby\s+(\d+(?:\.\d+)?)\s?%", low
        )
        if not m or "price" not in low and "cost" not in low:
            return
        names = self.SUPPLIER_NAME_RE.findall(sentence) or doc_suppliers
        supplier = names[0] if names else "__document_supplier__"
        eff = re.search(r"effective\s+(?:from\s+)?([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})", sentence)
        self.add(
            entity_type="supplier", entity=supplier, metric="supplier_price_change_pct",
            value=float(m.group(1)), unit="percent",
            attributes={"effective_date": parse_date(eff.group(1)) if eff else None},
            source=block.source.model_copy(update={"excerpt": sentence[:300]}),
            extraction_method="text_pattern", confidence="medium",
        )


def extract_facts(documents: list[ParsedDocument]) -> tuple[list[Fact], list[DataQualityIssue], dict]:
    """Run deterministic extraction across all parsed documents."""
    ex = Extractor()
    for doc in documents:
        for w in doc.warnings:
            ex.issues.append(DataQualityIssue(severity="warning", message=f"{doc.file_name}: {w}"))
    # First pass: learn projects (names and IDs) from register-like tables.
    for doc in documents:
        for block in doc.blocks:
            if block.kind == "table":
                ex.register_projects(block)
    for doc in documents:
        for block in doc.blocks:
            if block.kind == "table":
                ex.process_table(block, block.title or doc.file_name)
    for doc in documents:
        for block in doc.blocks:
            if block.kind == "text":
                ex.process_text(block)

    # Resolve supplier placeholders for documents that name a single supplier.
    doc_supplier: dict[str, str] = {}
    for f in ex.facts:
        if f.entity_type == "supplier" and not f.entity.startswith("__"):
            doc_supplier.setdefault(f.source.file_id, f.entity)
    for f in ex.facts:
        if f.entity == "__document_supplier__":
            f.entity = doc_supplier.get(f.source.file_id, "Unnamed supplier")

    # Currency decision.
    currency = None
    evidence = list(dict.fromkeys(ex.currency_evidence))
    if ex.currency_hits:
        currency = ex.currency_hits.most_common(1)[0][0]
        if len(ex.currency_hits) > 1:
            ex.issues.append(
                DataQualityIssue(
                    severity="critical",
                    message="More than one currency appears in the documents: "
                    + ", ".join(sorted(ex.currency_hits)),
                )
            )
    meta = {
        "currency": currency,
        "currency_evidence": evidence,
        "dollar_symbol_seen": ex.dollar_symbol_seen,
        "multiple_currencies": len(ex.currency_hits) > 1,
        "company_name": ex.company_names.most_common(1)[0][0] if ex.company_names else None,
        "projects": sorted(ex.known_projects),
    }
    for f in ex.facts:
        if f.unit == "currency" and not f.currency:
            f.currency = currency
    return ex.facts, ex.issues, meta
