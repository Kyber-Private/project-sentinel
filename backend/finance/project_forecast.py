"""Project-level forecasts: final cost, budget variance, schedule, supplier impact."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Optional

from domain import ExtractionResult, Fact
from finance.calculations import (
    budget_utilization,
    budget_variance,
    cost_performance_index,
    estimate_at_completion,
    months_between,
    pct_change,
    period_end_date,
    elapsed_schedule_pct,
)
from finance.formatting import money, month_label
from finance.types import BudgetCandidate, EacMethod, ProjectForecast, SeriesPoint

PRIORITY = ["bottom_up", "performance", "management", "run_rate", "commitments"]
CLOSE_PCT = 2.0


def _facts_for(extraction: ExtractionResult, project: str) -> list[Fact]:
    return [f for f in extraction.active_facts() if f.entity == project]


def _one(facts: list[Fact], metric: str) -> Optional[Fact]:
    return next((f for f in facts if f.metric == metric), None)


def supplier_impact_for(extraction: ExtractionResult, project: str) -> Optional[dict]:
    """Known supplier price increases applied to the project's open purchase orders."""
    changes = [f for f in extraction.active_facts() if f.metric == "supplier_price_change_pct" and f.value]
    if not changes:
        return None
    as_of = period_end_date(extraction.as_of_period) if extraction.as_of_period else None
    pos = [
        f for f in extraction.active_facts()
        if f.metric == "open_purchase_order" and (f.attributes.get("project") or "") == project and f.value
    ]
    items, total, fact_ids = [], 0.0, []
    for po in pos:
        change = next((c for c in changes if c.entity.lower() == po.entity.lower()), None)
        if change is None:
            continue
        eff = change.attributes.get("effective_date")
        if eff and as_of and date.fromisoformat(eff) <= as_of:
            continue  # already in effect, so already reflected in recent costs
        amount = po.value * change.value / 100.0
        total += amount
        fact_ids += [po.id, change.id]
        items.append({
            "po": po.dimension, "supplier": po.entity, "open_value": po.value,
            "price_change_pct": change.value, "effective_date": eff, "impact": round(amount, 2),
        })
    if not items:
        return None
    return {"amount": round(total, 2), "items": items, "fact_ids": list(dict.fromkeys(fact_ids))}


def build_project_forecast(extraction: ExtractionResult, project: str, resolutions: dict) -> ProjectForecast:
    cur = extraction.currency or "USD"
    facts = _facts_for(extraction, project)
    pf = ProjectForecast(id=f"project.{project}", project=project, currency=cur)
    as_of_period = extraction.as_of_period
    as_of = period_end_date(as_of_period) if as_of_period else None

    # ---- Budget
    budget_facts = [f for f in facts if f.metric in ("budget_approved", "budget_revised") and f.value is not None]
    distinct: list[Fact] = []
    for f in budget_facts:
        if not any(abs(f.value - d.value) < 1 for d in distinct):
            distinct.append(f)
    pf.budget_candidates = [
        BudgetCandidate(
            value=f.value,
            label=("Approved budget" if f.metric == "budget_approved" else f"Revised figure ({f.qualifier or 'status unclear'})"),
            fact_id=f.id, source_label=f.source.label(),
        )
        for f in distinct
    ]
    res = resolutions.get(f"budget:{project}")
    if res and res.get("value") is not None:
        pf.budget = float(res["value"])
        pf.budget_status = "user_supplied" if res.get("source") == "user" else "confirmed"
        pf.budget_fact_id = res.get("fact_id")
        pf.budget_note = res.get("note", "Confirmed in your answer.")
    elif len(distinct) == 1:
        f = distinct[0]
        pf.budget = f.value
        pf.budget_fact_id = f.id
        if f.metric == "budget_approved" and f.qualifier != "unlabeled":
            pf.budget_status = "confirmed"
        else:
            pf.budget_status = "unresolved"
            pf.budget_note = "The documents do not confirm that this budget figure was approved."
    elif len(distinct) > 1:
        pf.budget_status = "unresolved"
        pf.budget_note = "The documents show different budget figures and the correct one has not been confirmed."
    else:
        pf.budget_status = "missing"
        pf.budget_note = "No budget was found for this project."

    # ---- Actuals and progress
    ac_fact = _one(facts, "actual_cost")
    monthly: dict[str, float] = defaultdict(float)
    monthly_ids: list[str] = []
    for f in facts:
        if f.metric == "project_cost" and f.period and f.value is not None:
            monthly[f.period] += f.value
            monthly_ids.append(f.id)
    pf.monthly_costs = [SeriesPoint(period=p, value=v) for p, v in sorted(monthly.items())]
    if ac_fact:
        pf.actual_cost, pf.actual_fact_id = ac_fact.value, ac_fact.id
        pf.fact_ids.append(ac_fact.id)
    elif monthly:
        pf.actual_cost = sum(monthly.values())
        pf.assumptions.append("Actual cost to date is the sum of the monthly project costs in the documents.")
        pf.fact_ids += monthly_ids
    pct_fact = _one(facts, "percent_complete")
    pf.percent_complete = pct_fact.value if pct_fact else None
    committed_fact = _one(facts, "committed_cost")
    pf.committed = committed_fact.value if committed_fact else None
    mgmt_fact = _one(facts, "forecast_at_completion")
    pf.management_forecast = mgmt_fact.value if mgmt_fact else None
    etc_fact = _one(facts, "estimate_to_complete")
    contract_fact = _one(facts, "contract_value") or _one(facts, "project_revenue")
    for name in ("start_date", "planned_completion", "forecast_completion"):
        f = _one(facts, name)
        if f:
            setattr(pf, name, f.text_value)
            pf.fact_ids.append(f.id)
    if pf.budget_fact_id:
        pf.fact_ids.append(pf.budget_fact_id)

    if pf.actual_cost is not None and pf.budget:
        pf.utilization_pct = budget_utilization(pf.actual_cost, pf.budget)
    if pf.actual_cost and pf.percent_complete and pf.budget:
        pf.cpi = cost_performance_index(pf.actual_cost, pf.percent_complete, pf.budget)
    if pf.start_date and pf.planned_completion and as_of:
        pf.elapsed_pct = elapsed_schedule_pct(pf.start_date, pf.planned_completion, as_of)

    # ---- Supplier impact
    impact = supplier_impact_for(extraction, project)
    pf.supplier_impact = impact
    extra = impact["amount"] if impact else 0.0
    extra_ids = impact["fact_ids"] if impact else []
    extra_text = f" + supplier price increase on open orders ({money(extra, cur)})" if extra else ""

    # ---- Estimate-at-completion methods
    ac = pf.actual_cost
    end_period = (pf.forecast_completion or pf.planned_completion or "")[:7]
    months_left = months_between(as_of_period, end_period) if (end_period and as_of_period) else None
    if ac is not None:
        etc_res = resolutions.get(f"etc:{project}")
        etc_value = float(etc_res["value"]) if etc_res and etc_res.get("value") is not None else (etc_fact.value if etc_fact else None)
        if etc_value is not None:
            pf.methods.append(EacMethod(
                name="bottom_up", label="Estimate to complete",
                eac=estimate_at_completion(ac, etc_value),
                formula="Actual cost + estimate to complete",
                inputs={"actual_cost": ac, "estimate_to_complete": etc_value},
                evidence_type="observed" if etc_fact else "estimated",
                fact_ids=[x for x in [pf.actual_fact_id, etc_fact.id if etc_fact else None] if x],
                note="Uses the remaining-cost estimate " + ("from your answer." if etc_res else "in the documents."),
            ))
        if pf.percent_complete and pf.percent_complete > 0:
            perf = ac / (pf.percent_complete / 100.0)
            pf.methods.append(EacMethod(
                name="performance", label="Performance-based (earned value)",
                eac=perf + extra,
                formula="Actual cost / percent complete" + extra_text,
                inputs={"actual_cost": ac, "percent_complete": pf.percent_complete, "supplier_impact": extra},
                evidence_type="calculated",
                fact_ids=[x for x in [pf.actual_fact_id, pct_fact.id] if x] + extra_ids,
                note="Assumes the remaining work costs the same per unit of progress as the work done so far.",
            ))
        if pf.management_forecast is not None:
            pf.methods.append(EacMethod(
                name="management", label="Management forecast",
                eac=pf.management_forecast, formula="As stated in the documents",
                inputs={"forecast_at_completion": pf.management_forecast}, evidence_type="observed",
                fact_ids=[mgmt_fact.id],
                note="Taken directly from the documents. It may not include later supplier price changes.",
            ))
        if len(pf.monthly_costs) >= 3 and months_left is not None and months_left > 0:
            recent = sum(p.value for p in pf.monthly_costs[-3:]) / 3
            pf.recent_monthly_cost = recent
            pf.methods.append(EacMethod(
                name="run_rate", label="Recent spending rate",
                eac=ac + recent * months_left + extra,
                formula=f"Actual cost + average of last 3 months x {months_left} months to completion" + extra_text,
                inputs={"actual_cost": ac, "recent_monthly_cost": recent, "months_left": months_left, "supplier_impact": extra},
                evidence_type="estimated", fact_ids=monthly_ids[-9:] + extra_ids,
                note="Assumes spending continues at the recent monthly rate until the forecast completion date.",
            ))
        elif len(pf.monthly_costs) >= 3:
            pf.recent_monthly_cost = sum(p.value for p in pf.monthly_costs[-3:]) / 3
        if pf.committed is not None:
            pf.methods.append(EacMethod(
                name="commitments", label="Committed costs only (lower bound)",
                eac=ac + pf.committed + extra, formula="Actual cost + remaining commitments" + extra_text,
                inputs={"actual_cost": ac, "committed": pf.committed, "supplier_impact": extra},
                evidence_type="calculated", fact_ids=[x for x in [pf.actual_fact_id, committed_fact.id] if x] + extra_ids,
                note="Counts only work already ordered. Any uncommitted work would add to this.",
            ))

    if pf.methods:
        primary = sorted(pf.methods, key=lambda m: PRIORITY.index(m.name))[0]
        pf.primary_method = primary.name
        pf.eac = primary.eac
        values = [m.eac for m in pf.methods]
        pf.eac_low, pf.eac_high = min(values), max(values)
        pf.estimate_to_complete = pf.eac - ac if ac is not None else None
        pf.fact_ids += primary.fact_ids
        pf.reliable = primary.name in ("bottom_up", "performance", "management")
        if not pf.reliable:
            pf.message = "Rough estimate only: based on recent spending or committed costs, not on reported progress."
    else:
        pf.message = (
            "Not enough information to estimate the final cost. Sentinel needs the actual cost to date plus either "
            "percent complete, a remaining-cost estimate, or a current forecast."
        )

    # ---- Variance and outlook
    def outlook_for(budget: float) -> tuple[str, str, float, float]:
        var = budget_variance(pf.eac, budget)
        var_pct = var / budget * 100.0
        independent = [m.eac for m in pf.methods]
        if all(v > budget * (1 + CLOSE_PCT / 100) for v in independent) and len(independent) > 1:
            return "Likely to exceed budget", "unfavorable", var, var_pct
        if var_pct > CLOSE_PCT:
            return "At risk of exceeding budget", "unfavorable", var, var_pct
        if abs(var_pct) <= CLOSE_PCT:
            return "Close to budget", "uncertain", var, var_pct
        if max(independent) > budget:
            return "Within budget, with some risk", "uncertain", var, var_pct
        return "Within budget", "favorable", var, var_pct

    if pf.eac is not None:
        if pf.budget is not None and pf.budget_status in ("confirmed", "user_supplied"):
            pf.outlook, pf.tone, pf.variance, pf.variance_pct = outlook_for(pf.budget)
        elif pf.budget_candidates:
            results = []
            for c in pf.budget_candidates:
                o, t, v, vp = outlook_for(c.value)
                results.append({"budget": c.value, "label": c.label, "variance": v, "variance_pct": vp, "outlook": o, "tone": t})
            pf.variance_by_budget = results
            if len(results) == 1:
                pf.outlook, pf.tone = results[0]["outlook"], results[0]["tone"]
                pf.variance, pf.variance_pct = results[0]["variance"], results[0]["variance_pct"]
                pf.budget = results[0]["budget"]
                pf.assumptions.append("The budget figure's approval status is unclear.")
            elif len({r["outlook"] for r in results}) == 1:
                pf.outlook, pf.tone = results[0]["outlook"], results[0]["tone"]
                pf.message = "The outlook is the same under every budget figure in the documents."
            else:
                pf.outlook, pf.tone = "Depends on which budget applies", "uncertain"
                pf.message = (
                    "The budget figure is unresolved. " + "; ".join(
                        f"against {money(r['budget'], cur)}: {r['outlook'].lower()} ({money(r['variance'], cur, signed=True)})"
                        for r in results
                    ) + "."
                )
        else:
            pf.outlook, pf.tone = "No budget to compare", "uncertain"

    # ---- Schedule
    if pf.planned_completion and pf.forecast_completion:
        pf.delay_days = (date.fromisoformat(pf.forecast_completion) - date.fromisoformat(pf.planned_completion)).days
    for f in facts:
        if f.metric != "milestone":
            continue
        planned, fc = f.attributes.get("planned"), f.attributes.get("forecast") or f.attributes.get("actual")
        status = (f.attributes.get("status") or "").lower()
        late_days = (date.fromisoformat(fc) - date.fromisoformat(planned)).days if planned and fc else None
        if (late_days and late_days > 0) or "late" in status or "risk" in status:
            pf.late_milestones.append({
                "milestone": f.text_value, "planned": planned, "forecast": fc, "days_late": late_days,
                "status": f.attributes.get("status"), "fact_id": f.id,
            })
            pf.fact_ids.append(f.id)

    # ---- Profitability
    if contract_fact and pf.eac is not None:
        pf.contract_value = contract_fact.value
        pf.expected_margin = contract_fact.value - pf.eac
        pf.fact_ids.append(contract_fact.id)

    # ---- Plain-language insights (all computed from the figures above)
    if pf.utilization_pct is not None:
        if pf.percent_complete is not None:
            pf.insights.append(
                f"Has spent {pf.utilization_pct:.0f}% of its budget and reports {pf.percent_complete:.0f}% of the work complete"
                + (f" (cost performance index {pf.cpi:.2f}; below 1.00 means work is costing more than planned)." if pf.cpi else ".")
            )
        else:
            pf.insights.append(
                f"Has spent {pf.utilization_pct:.0f}% of its budget. Progress is not reported, so spending cannot be "
                "compared with work completed."
            )
    if pf.elapsed_pct is not None:
        pf.insights.append(f"{pf.elapsed_pct:.0f}% of the planned schedule had elapsed by {month_label(as_of_period)}.")
    if pf.delay_days and pf.delay_days > 0:
        pf.insights.append(
            f"Forecast completion is {pf.delay_days} days later than planned ({pf.forecast_completion} vs {pf.planned_completion})."
        )
    if impact:
        pf.insights.append(
            f"A supplier price increase on open purchase orders adds about {money(impact['amount'], cur)} to remaining costs."
        )
    perf = next((m for m in pf.methods if m.name == "performance"), None)
    if perf and pf.management_forecast and perf.eac > pf.management_forecast * 1.03:
        pf.insights.append(
            f"The management forecast ({money(pf.management_forecast, cur)}) is lower than the performance-based "
            f"estimate ({money(perf.eac, cur)}), so it may be optimistic."
        )
    if len(pf.monthly_costs) >= 6:
        last3 = sum(p.value for p in pf.monthly_costs[-3:])
        prev3 = sum(p.value for p in pf.monthly_costs[-6:-3])
        ch = pct_change(last3, prev3)
        if ch is not None and abs(ch) >= 5:
            pf.insights.append(
                f"Monthly spending in the last 3 months was {ch:+.0f}% compared with the 3 months before."
            )
    pf.fact_ids = list(dict.fromkeys(pf.fact_ids))
    return pf


def build_project_forecasts(extraction: ExtractionResult, resolutions: dict) -> list[ProjectForecast]:
    return [build_project_forecast(extraction, p, resolutions) for p in extraction.projects]
