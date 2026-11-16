"""Core domain types shared by document processing, finance, agents, and services."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

EntityType = Literal["company", "project", "supplier", "other"]
ExtractionMethod = Literal["table", "text_pattern", "agent", "user_answer"]

# Normalized metric vocabulary. Anything outside this list is stored as a note.
COMPANY_SERIES_METRICS = [
    "revenue",
    "cogs",
    "gross_profit",
    "operating_expenses",
    "operating_profit",
    "net_profit",
    "cash_balance",
    "cash_flow",
    "accounts_receivable",
    "accounts_payable",
    "debt",
]
PROJECT_METRICS = [
    "budget_approved",
    "budget_revised",
    "actual_cost",
    "committed_cost",
    "forecast_at_completion",
    "estimate_to_complete",
    "percent_complete",
    "start_date",
    "planned_completion",
    "forecast_completion",
    "actual_completion",
    "contract_value",
    "project_revenue",
    "project_cost",  # monthly cost, has a period
    "change_request",
    "milestone",
]
OTHER_METRICS = [
    "expense_category",  # monthly opex category, dimension = category name
    "supplier_invoice",
    "supplier_price_change_pct",
    "open_purchase_order",
    "business_note",
    "currency_statement",
]
ALL_METRICS = COMPANY_SERIES_METRICS + PROJECT_METRICS + OTHER_METRICS

METRIC_LABELS = {
    "revenue": "Revenue",
    "cogs": "Cost of goods sold",
    "gross_profit": "Gross profit",
    "operating_expenses": "Operating expenses",
    "operating_profit": "Operating profit",
    "net_profit": "Net profit",
    "cash_balance": "Cash balance",
    "cash_flow": "Net cash flow",
    "accounts_receivable": "Accounts receivable",
    "accounts_payable": "Accounts payable",
    "debt": "Debt",
    "budget_approved": "Approved budget",
    "budget_revised": "Revised budget (mentioned)",
    "actual_cost": "Actual cost to date",
    "committed_cost": "Remaining commitments",
    "forecast_at_completion": "Forecast at completion",
    "estimate_to_complete": "Estimate to complete",
    "percent_complete": "Percent complete",
    "start_date": "Start date",
    "planned_completion": "Planned completion",
    "forecast_completion": "Forecast completion",
    "actual_completion": "Actual completion",
    "contract_value": "Contract value",
    "project_revenue": "Project revenue",
    "project_cost": "Monthly project cost",
    "change_request": "Change request",
    "milestone": "Milestone",
    "expense_category": "Expense category",
    "supplier_invoice": "Supplier invoice",
    "supplier_price_change_pct": "Supplier price change",
    "open_purchase_order": "Open purchase order",
    "business_note": "Business note",
    "currency_statement": "Currency statement",
}


class SourceRef(BaseModel):
    file_id: str
    file_name: str
    page: Optional[int] = None
    sheet: Optional[str] = None
    row: Optional[int] = None
    record_id: Optional[str] = None
    excerpt: Optional[str] = None

    def label(self) -> str:
        parts = [self.file_name]
        if self.page is not None:
            parts.append(f"page {self.page}")
        if self.sheet:
            parts.append(f"sheet '{self.sheet}'")
        if self.row is not None:
            parts.append(f"row {self.row}")
        if self.record_id:
            parts.append(f"record {self.record_id}")
        return ", ".join(parts)


class Fact(BaseModel):
    id: str = ""
    entity_type: EntityType
    entity: str
    metric: str
    period: Optional[str] = None  # YYYY-MM for monthly values
    dimension: Optional[str] = None  # e.g. expense category, supplier, PO number
    value: Optional[float] = None
    text_value: Optional[str] = None
    currency: Optional[str] = None
    unit: Literal["currency", "percent", "date", "text", "number"] = "currency"
    qualifier: Optional[str] = None  # approved, revised, actual, forecast, pending
    source: SourceRef
    extraction_method: ExtractionMethod = "table"
    confidence: Literal["high", "medium", "low"] = "high"
    corroborating_sources: list[SourceRef] = Field(default_factory=list)
    attributes: dict = Field(default_factory=dict)
    superseded: bool = False  # true when a clarification answer ruled it out


class Conflict(BaseModel):
    id: str
    entity: str
    metric: str
    period: Optional[str] = None
    description: str
    fact_ids: list[str]
    values: list[float]
    explained_by_period: bool = False
    material: bool = True
    resolved_fact_id: Optional[str] = None


class DuplicateGroup(BaseModel):
    id: str
    kind: Literal["exact", "uncertain"]
    description: str
    fact_ids: list[str]
    kept_fact_id: str


class DocumentBlock(BaseModel):
    """A unit of parsed content with provenance: a table or a chunk of text."""

    kind: Literal["table", "text"]
    source: SourceRef
    title: Optional[str] = None
    text: Optional[str] = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list] = Field(default_factory=list)
    row_numbers: list[int] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    file_id: str
    file_name: str
    file_type: str
    blocks: list[DocumentBlock] = Field(default_factory=list)
    page_count: Optional[int] = None
    warnings: list[str] = Field(default_factory=list)
    needs_visual_extraction: bool = False


class DataQualityIssue(BaseModel):
    severity: Literal["info", "warning", "critical"]
    message: str
    fact_ids: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    company_name: Optional[str] = None
    currency: Optional[str] = None
    currency_evidence: list[str] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    duplicates: list[DuplicateGroup] = Field(default_factory=list)
    issues: list[DataQualityIssue] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    as_of_period: Optional[str] = None

    def fact_by_id(self, fact_id: str) -> Optional[Fact]:
        for f in self.facts:
            if f.id == fact_id:
                return f
        return None

    def active_facts(self) -> list[Fact]:
        return [f for f in self.facts if not f.superseded]
