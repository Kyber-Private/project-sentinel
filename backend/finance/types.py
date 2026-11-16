"""Pydantic result types for calculations, forecasts, drivers, and scenarios."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Direction = Literal["increase", "decrease", "stable", "unknown"]
Effect = Literal["favorable", "unfavorable", "neutral", "uncertain"]
EvidenceType = Literal["observed", "calculated", "estimated", "hypothesized"]


class SeriesPoint(BaseModel):
    period: str
    value: float
    fact_id: Optional[str] = None


class ForecastPoint(BaseModel):
    period: str
    value: float
    low: float
    high: float


class ModelScore(BaseModel):
    model: str
    label: str
    mae: float
    mape: Optional[float] = None
    n_origins: int


class MetricForecast(BaseModel):
    id: str  # e.g. "company.revenue"
    metric: str
    label: str
    history: list[SeriesPoint] = Field(default_factory=list)
    forecast: list[ForecastPoint] = Field(default_factory=list)
    horizon_months: int
    method: Literal["statistical", "derived", "bottom_up", "none"] = "statistical"
    model: Optional[str] = None
    model_label: Optional[str] = None
    model_reason: str = ""
    formula: Optional[str] = None
    validation: list[ModelScore] = Field(default_factory=list)
    validated: bool = False
    data_points: int = 0
    sufficiency: str = "insufficient"
    reliable: bool = False
    message: Optional[str] = None
    direction: Direction = "unknown"
    direction_confidence: Literal["clear", "tentative", "none"] = "none"
    change_pct: Optional[float] = None
    change_abs: Optional[float] = None
    recent_total: Optional[float] = None
    forecast_total: Optional[float] = None
    forecast_total_low: Optional[float] = None
    forecast_total_high: Optional[float] = None
    end_value: Optional[float] = None
    end_low: Optional[float] = None
    end_high: Optional[float] = None
    comparison_text: str = ""
    effect: Effect = "uncertain"
    effect_reason: str = ""
    outliers: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)
    is_balance: bool = False  # balances compare end value, flows compare totals


class CompanyForecast(BaseModel):
    horizon_months: int
    first_period: Optional[str] = None
    last_period: Optional[str] = None
    forecast_start: Optional[str] = None
    forecast_end: Optional[str] = None
    metrics: list[MetricForecast] = Field(default_factory=list)
    profit_formula: Optional[str] = None
    notes: list[str] = Field(default_factory=list)

    def get(self, metric: str) -> Optional[MetricForecast]:
        return next((m for m in self.metrics if m.metric == metric), None)


class EacMethod(BaseModel):
    name: str
    label: str
    eac: float
    formula: str
    inputs: dict = Field(default_factory=dict)
    evidence_type: EvidenceType
    fact_ids: list[str] = Field(default_factory=list)
    note: str = ""


class BudgetCandidate(BaseModel):
    value: float
    label: str
    fact_id: str
    source_label: str


class ProjectForecast(BaseModel):
    id: str
    project: str
    currency: Optional[str] = None
    budget: Optional[float] = None
    budget_status: Literal["confirmed", "unresolved", "missing", "user_supplied"] = "missing"
    budget_note: str = ""
    budget_candidates: list[BudgetCandidate] = Field(default_factory=list)
    budget_fact_id: Optional[str] = None
    actual_cost: Optional[float] = None
    actual_fact_id: Optional[str] = None
    utilization_pct: Optional[float] = None
    percent_complete: Optional[float] = None
    cpi: Optional[float] = None
    elapsed_pct: Optional[float] = None
    committed: Optional[float] = None
    management_forecast: Optional[float] = None
    methods: list[EacMethod] = Field(default_factory=list)
    primary_method: Optional[str] = None
    eac: Optional[float] = None
    eac_low: Optional[float] = None
    eac_high: Optional[float] = None
    estimate_to_complete: Optional[float] = None
    variance: Optional[float] = None
    variance_pct: Optional[float] = None
    variance_by_budget: list[dict] = Field(default_factory=list)
    outlook: str = "Not enough information"
    tone: Effect = "uncertain"
    start_date: Optional[str] = None
    planned_completion: Optional[str] = None
    forecast_completion: Optional[str] = None
    delay_days: Optional[int] = None
    late_milestones: list[dict] = Field(default_factory=list)
    supplier_impact: Optional[dict] = None
    recent_monthly_cost: Optional[float] = None
    monthly_costs: list[SeriesPoint] = Field(default_factory=list)
    contract_value: Optional[float] = None
    expected_margin: Optional[float] = None
    reliable: bool = False
    message: Optional[str] = None
    insights: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)


class Driver(BaseModel):
    id: str
    scope: Literal["company", "project"]
    subject: str  # metric id or project name
    title: str
    what_changed: str
    magnitude: Optional[str] = None
    period_compared: Optional[str] = None
    evidence_type: EvidenceType
    effect_on_forecast: str
    support: Literal["supported", "plausible"]
    fact_ids: list[str] = Field(default_factory=list)
    impact: Literal["favorable", "unfavorable", "neutral"] = "neutral"
    weight: float = 0.0  # ranking helper


class ScenarioInput(BaseModel):
    revenue_change_pct: float = 0.0
    opex_change_pct: float = 0.0
    supplier_cost_change_pct: float = 0.0
    extra_monthly_hiring_cost: float = 0.0
    project_delay_weeks: float = 0.0
    delayed_project: Optional[str] = None


class ScenarioLine(BaseModel):
    key: str
    label: str
    original: Optional[float]
    new: Optional[float]
    difference: Optional[float]
    unit: Literal["currency", "percent"] = "currency"
    favorable: Optional[bool] = None


class ScenarioResult(BaseModel):
    input: ScenarioInput
    horizon_months: int
    lines: list[ScenarioLine] = Field(default_factory=list)
    explanations: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)
