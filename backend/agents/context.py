"""Token-conscious context builders. Each agent receives only what it needs."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from domain import METRIC_LABELS, ExtractionResult, ParsedDocument
from finance.types import CompanyForecast, Driver, ProjectForecast

FIN_WORDS = re.compile(
    r"revenue|sales|cost|expense|budget|forecast|profit|cash|invoice|supplier|price|project|hire|hiring|"
    r"contract|approved|revised|delay|complete|commit|margin|payroll|increase|decrease",
    re.I,
)


def select_chunks(documents: list[ParsedDocument], char_budget: int) -> list[dict]:
    """Pick text chunks for the Data Analyst, most finance-dense first, within a budget."""
    chunks = []
    for doc in documents:
        for block in doc.blocks:
            if block.kind != "text" or not block.text:
                continue
            text = block.text.strip()
            score = len(FIN_WORDS.findall(text)) + 2 * len(re.findall(r"[$€£]\s?\d|\d+%", text))
            chunks.append({"source": block.source, "text": text, "score": score})
    chunks.sort(key=lambda c: -c["score"])
    selected, used = [], 0
    for c in chunks:
        if c["score"] == 0:
            continue
        if used + len(c["text"]) > char_budget:
            continue
        selected.append(c)
        used += len(c["text"])
    # Stable ids in document order.
    selected.sort(key=lambda c: (c["source"].file_name, c["source"].page or 0, c["source"].record_id or "", c["source"].row or 0))
    for i, c in enumerate(selected, start=1):
        c["chunk_id"] = f"K{i:03d}"
    return selected


def deterministic_summary(ex: ExtractionResult) -> dict[str, Any]:
    """Compact view of what table parsing already found, for the Data Analyst."""
    series: dict[str, list[str]] = defaultdict(list)
    point_facts = []
    for f in ex.active_facts():
        if f.entity_type == "company" and f.period and f.metric != "expense_category":
            series[f.metric].append(f.period)
        elif f.metric in ("expense_category", "project_cost", "supplier_invoice"):
            continue
        else:
            point_facts.append(
                f"{f.id} | {f.entity} | {f.metric} | {f.value if f.value is not None else f.text_value} | {f.qualifier or ''} | {f.source.label()}"
            )
    cats = sorted({f.dimension for f in ex.active_facts() if f.metric == "expense_category" and f.dimension})
    return {
        "company_name": ex.company_name,
        "currency": ex.currency,
        "projects": ex.projects,
        "company_monthly_series": {m: f"{min(p)} to {max(p)} ({len(p)} months)" for m, p in series.items()},
        "expense_categories": cats,
        "project_and_other_facts": point_facts[:120],
        "conflicts": [c.description for c in ex.conflicts],
        "duplicates": [d.description for d in ex.duplicates],
    }


def _series_table(cf: CompanyForecast) -> dict[str, list[str]]:
    out = {}
    for m in cf.metrics:
        out[m.metric] = [f"{p.period}: {p.value:,.0f}" + (f" [{p.fact_id}]" if p.fact_id else "") for p in m.history[-12:]]
    return out


def forecast_summary(m) -> dict[str, Any]:
    return {
        "calculation_id": m.id,
        "label": m.label,
        "method": m.method,
        "model": m.model_label,
        "model_reason": m.model_reason,
        "formula": m.formula,
        "history_months": m.data_points,
        "data_sufficiency": m.sufficiency,
        "validated": m.validated,
        "comparison": m.comparison_text,
        "recent_total_or_last_value": round(m.recent_total, 0) if m.recent_total is not None else None,
        "forecast_total": round(m.forecast_total, 0) if m.forecast_total is not None else None,
        "forecast_total_range": [round(m.forecast_total_low, 0), round(m.forecast_total_high, 0)] if m.forecast_total_low is not None else None,
        "end_value": round(m.end_value, 0) if m.end_value is not None else None,
        "end_range": [round(m.end_low, 0), round(m.end_high, 0)] if m.end_low is not None else None,
        "change_pct": round(m.change_pct, 1) if m.change_pct is not None else None,
        "direction": m.direction,
        "direction_confidence": m.direction_confidence,
        "effect": m.effect,
        "message": m.message,
        "assumptions": m.assumptions,
    }


def driver_summary(d: Driver) -> dict[str, Any]:
    return {
        "calculation_id": d.id, "subject": d.subject, "title": d.title, "what_changed": d.what_changed,
        "magnitude": d.magnitude, "period_compared": d.period_compared, "evidence_type": d.evidence_type,
        "support": d.support, "fact_ids": d.fact_ids[:12],
    }


def notes(ex: ExtractionResult) -> list[str]:
    return [
        f"{f.id}: {f.text_value} ({f.source.label()})"
        for f in ex.active_facts() if f.metric == "business_note"
    ][:25]


def company_context(ex: ExtractionResult, cf: CompanyForecast, drivers: list[Driver], answers: list[dict]) -> dict:
    cats: dict[str, list[str]] = defaultdict(list)
    for f in ex.active_facts():
        if f.metric == "expense_category" and f.period and f.value is not None:
            cats[f.dimension or "Other"].append(f"{f.period}: {f.value:,.0f} [{f.id}]")
    return {
        "company": ex.company_name, "currency": ex.currency, "latest_period": ex.as_of_period,
        "forecast_horizon_months": cf.horizon_months, "forecast_window": f"{cf.forecast_start} to {cf.forecast_end}",
        "monthly_history": _series_table(cf),
        "expense_categories": {k: v[-12:] for k, v in cats.items()},
        "forecasts": [forecast_summary(m) for m in cf.metrics],
        "drivers": [driver_summary(d) for d in drivers],
        "document_notes": notes(ex),
        "supplier_price_changes": [
            f"{f.id}: {f.entity} {f.value:g}% effective {f.attributes.get('effective_date')}"
            for f in ex.active_facts() if f.metric == "supplier_price_change_pct" and f.value is not None
        ],
        "data_quality_issues": [i.message for i in ex.issues][:15],
        "forecast_notes": cf.notes,
        "user_answers": answers,
    }


def project_summary(p: ProjectForecast) -> dict[str, Any]:
    return {
        "calculation_id": p.id, "project": p.project, "currency": p.currency,
        "budget": p.budget, "budget_status": p.budget_status, "budget_note": p.budget_note,
        "budget_candidates": [c.model_dump() for c in p.budget_candidates],
        "actual_cost": p.actual_cost, "utilization_pct": round(p.utilization_pct, 1) if p.utilization_pct else None,
        "percent_complete": p.percent_complete, "cost_performance_index": round(p.cpi, 3) if p.cpi else None,
        "schedule_elapsed_pct": round(p.elapsed_pct, 1) if p.elapsed_pct is not None else None,
        "remaining_commitments": p.committed, "management_forecast": p.management_forecast,
        "eac_methods": [
            {"name": m.name, "label": m.label, "eac": round(m.eac, 0), "formula": m.formula,
             "evidence_type": m.evidence_type, "fact_ids": m.fact_ids, "note": m.note}
            for m in p.methods
        ],
        "primary_method": p.primary_method, "estimate_at_completion": round(p.eac, 0) if p.eac else None,
        "eac_range": [round(p.eac_low, 0), round(p.eac_high, 0)] if p.eac_low is not None else None,
        "variance": round(p.variance, 0) if p.variance is not None else None,
        "variance_pct": round(p.variance_pct, 1) if p.variance_pct is not None else None,
        "variance_by_budget": p.variance_by_budget, "outlook": p.outlook,
        "planned_completion": p.planned_completion, "forecast_completion": p.forecast_completion,
        "delay_days": p.delay_days, "late_milestones": p.late_milestones,
        "supplier_impact": p.supplier_impact,
        "monthly_costs": [f"{x.period}: {x.value:,.0f}" for x in p.monthly_costs],
        "insights": p.insights, "message": p.message, "fact_ids": p.fact_ids,
    }


def project_context(ex: ExtractionResult, projects: list[ProjectForecast], drivers: list[Driver], answers: list[dict]) -> dict:
    return {
        "company": ex.company_name, "currency": ex.currency, "latest_period": ex.as_of_period,
        "projects": [project_summary(p) for p in projects],
        "drivers": [driver_summary(d) for d in drivers],
        "document_notes": [n for n in notes(ex) if any(p.project.lower() in n.lower() for p in projects)],
        "conflicts": [c.description for c in ex.conflicts],
        "user_answers": answers,
    }
