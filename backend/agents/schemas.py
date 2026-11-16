"""Structured output schemas for each agent.

Fields have no defaults so the JSON schema sent to the API is strict: every
field is required, nullable fields are Optional.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

from domain import ALL_METRICS

MetricName = Literal[tuple(ALL_METRICS)]  # type: ignore[valid-type]
Importance = Literal["essential", "helpful", "optional"]
EvidenceType = Literal["observed", "calculated", "estimated", "hypothesized"]


# ---------------------------------------------------------------- Data Analyst
class AgentExtractedFact(BaseModel):
    entity_type: Literal["company", "project", "supplier", "other"]
    entity: str
    metric: MetricName
    period: Optional[str]
    value: Optional[float]
    text_value: Optional[str]
    currency: Optional[str]
    qualifier: Optional[str]
    chunk_id: str
    quote: str


class MissingItem(BaseModel):
    item: str
    importance: Importance
    reason: str


class SuggestedQuestion(BaseModel):
    question: str
    reason: str
    importance: Importance
    related_fields: list[str]
    options: list[str]


class DataAnalystOutput(BaseModel):
    summary: str
    facts: list[AgentExtractedFact]
    data_quality_issues: list[str]
    missing_information: list[MissingItem]
    conflicts_noticed: list[str]
    relationships: list[str]
    suggested_questions: list[SuggestedQuestion]


# ------------------------------------------------------------ Emily and Sebas
class Finding(BaseModel):
    title: str
    statement: str
    metric: str
    direction: Literal["increase", "decrease", "stable", "unclear"]
    business_effect: Literal["favorable", "unfavorable", "neutral", "uncertain"]
    evidence_type: EvidenceType
    support: Literal["supported", "plausible"]
    cited_fact_ids: list[str]
    cited_calculation_ids: list[str]


class CompanyAnalysis(BaseModel):
    summary: str
    outlook: Literal["improving", "stable", "deteriorating", "mixed", "insufficient_data"]
    findings: list[Finding]
    uncertainties: list[str]
    watch_items: list[str]


class ProjectAnalysis(BaseModel):
    project: str
    summary: str
    status: Literal["on_track", "at_risk", "over_budget", "insufficient_data"]
    findings: list[Finding]
    risks: list[str]
    uncertainties: list[str]


class ProjectAnalysisSet(BaseModel):
    projects: list[ProjectAnalysis]
    cross_project_notes: list[str]


# ------------------------------------------------------------------- Alex
class ClaimReview(BaseModel):
    claim_id: str
    assessment: Literal["supported", "unsupported", "contradicted", "overstated", "hypothesis"]
    comment: str


class Challenge(BaseModel):
    target: str
    issue: str
    severity: Literal["low", "medium", "high"]


class ProjectVerdict(BaseModel):
    project: str
    verdict: Literal["trust", "qualify", "withhold"]
    reason: str


class ReviewOutput(BaseModel):
    overall_verdict: Literal["trust", "qualify", "withhold"]
    verdict_reason: str
    recommended_confidence: Literal["high", "medium", "low"]
    company_verdict: Literal["trust", "qualify", "withhold", "not_applicable"]
    project_verdicts: list[ProjectVerdict]
    claim_reviews: list[ClaimReview]
    challenges: list[Challenge]
    false_precision: list[str]
    insufficient_data: list[str]
    what_could_change_outlook: list[str]
    recommended_next_step: str


# ----------------------------------------------------- Answer interpretation
class AnswerInterpretation(BaseModel):
    understood: bool
    option_id: Optional[str]
    numeric_value: Optional[float]
    summary: str
