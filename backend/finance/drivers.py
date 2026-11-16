"""Identify what is driving each predicted movement.

Drivers are computed from the records. Each one states whether it is observed,
calculated, estimated, or hypothesized, and whether the link to the forecast is
supported by the arithmetic or only plausible.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from domain import ExtractionResult
from finance.calculations import gross_margin_pct, pct_change
from finance.formatting import money, month_label
from finance.types import CompanyForecast, Driver, ProjectForecast


def _window(periods: list[str]) -> tuple[list[str], list[str]]:
    n = len(periods)
    w = min(6, n // 2)
    return periods[-2 * w : -w], periods[-w:]


def _range_text(periods: list[str]) -> str:
    return f"{month_label(periods[0])} to {month_label(periods[-1])}" if periods else ""


def company_drivers(extraction: ExtractionResult, cf: CompanyForecast) -> list[Driver]:
    cur = extraction.currency or "USD"
    drivers: list[Driver] = []
    facts = extraction.active_facts()

    def add(**kw) -> None:
        drivers.append(Driver(id=f"DRV{len(drivers)+1:02d}", scope="company", **kw))

    # Expense categories: decompose the change in operating expenses.
    cats: dict[str, dict[str, float]] = defaultdict(dict)
    cat_ids: dict[str, list[str]] = defaultdict(list)
    for f in facts:
        if f.metric == "expense_category" and f.period and f.value is not None:
            cats[f.dimension or "Other"][f.period] = f.value
            cat_ids[f.dimension or "Other"].append(f.id)
    periods = sorted({p for c in cats.values() for p in c})
    if len(periods) >= 4:
        before, after = _window(periods)
        w = len(after)
        changes = []
        for cat, vals in cats.items():
            if not all(p in vals for p in before + after):
                continue
            avg_b = sum(vals[p] for p in before) / w
            avg_a = sum(vals[p] for p in after) / w
            changes.append((cat, avg_b, avg_a, avg_a - avg_b))
        total_increase = sum(c[3] for c in changes if c[3] > 0)
        compared = f"{_range_text(after)} vs {_range_text(before)} (monthly averages)"
        for cat, avg_b, avg_a, delta in sorted(changes, key=lambda c: -abs(c[3]))[:3]:
            if abs(delta) < 1 or (avg_b and abs(delta / avg_b) < 0.02):
                continue
            share = delta / total_increase * 100 if total_increase > 0 and delta > 0 else None
            add(
                subject="company.operating_expenses",
                title=f"{cat} costs {'rose' if delta > 0 else 'fell'}",
                what_changed=f"{cat} averaged {money(avg_a, cur)} per month, up from {money(avg_b, cur)}."
                if delta > 0 else f"{cat} averaged {money(avg_a, cur)} per month, down from {money(avg_b, cur)}.",
                magnitude=f"{pct_change(avg_a, avg_b):+.1f}% ({money(delta, cur, signed=True)} per month)",
                period_compared=compared,
                evidence_type="calculated",
                effect_on_forecast=(
                    f"Accounts for {share:.0f}% of the increase in monthly operating expenses, which carries into the "
                    "expense forecast." if share is not None else "Offsets part of the change in operating expenses."
                ),
                support="supported",
                impact="unfavorable" if delta > 0 else "favorable",
                fact_ids=cat_ids[cat][-2 * w :],
                weight=abs(delta) * 6,
            )

    # Revenue movement.
    rev = cf.get("revenue")
    if rev and len(rev.history) >= 4:
        hp = [p.period for p in rev.history]
        before, after = _window(hp)
        vals = {p.period: p.value for p in rev.history}
        b = sum(vals[p] for p in before) / len(before)
        a = sum(vals[p] for p in after) / len(after)
        ch = pct_change(a, b)
        add(
            subject="company.revenue",
            title="Revenue trend",
            what_changed=f"Revenue averaged {money(a, cur)} per month, compared with {money(b, cur)}.",
            magnitude=f"{ch:+.1f}%" if ch is not None else None,
            period_compared=f"{_range_text(after)} vs {_range_text(before)}",
            evidence_type="calculated",
            effect_on_forecast="The forecast model extends this trend forward.",
            support="supported",
            impact="favorable" if a > b else "unfavorable",
            fact_ids=[p.fact_id for p in rev.history if p.fact_id][-12:],
            weight=abs(a - b) * 6,
        )

    # Cost growth relative to revenue growth.
    opx = cf.get("operating_expenses")
    cogs = cf.get("cogs")
    for cost in (opx, cogs):
        if cost and rev and cost.change_pct is not None and rev.change_pct is not None and cost.change_pct > rev.change_pct + 1:
            add(
                subject="company.operating_profit",
                title=f"{cost.label} growing faster than revenue",
                what_changed=f"{cost.label} {'are' if cost.metric == 'operating_expenses' else 'is'} forecast to change "
                f"{cost.change_pct:+.1f}%, while revenue changes {rev.change_pct:+.1f}%.",
                magnitude=f"{cost.change_pct - rev.change_pct:.1f} percentage points faster",
                period_compared=cost.comparison_text,
                evidence_type="estimated",
                effect_on_forecast="Squeezes profit: costs absorb a growing share of each dollar of revenue.",
                support="supported",
                impact="unfavorable",
                fact_ids=cost.fact_ids[-6:] + rev.fact_ids[-6:],
                weight=abs((cost.forecast_total or 0) - (cost.recent_total or 0)),
            )

    # Gross margin.
    rev_hist = {p.period: p.value for p in rev.history} if rev else {}
    cogs_hist = {p.period: p.value for p in cogs.history} if cogs else {}
    common = sorted(set(rev_hist) & set(cogs_hist))
    if len(common) >= 4:
        before, after = _window(common)
        m_b = gross_margin_pct(sum(rev_hist[p] for p in before), sum(cogs_hist[p] for p in before))
        m_a = gross_margin_pct(sum(rev_hist[p] for p in after), sum(cogs_hist[p] for p in after))
        if m_b is not None and m_a is not None and abs(m_a - m_b) >= 0.5:
            add(
                subject="company.gross_profit",
                title="Gross margin " + ("narrowed" if m_a < m_b else "widened"),
                what_changed=f"Cost of goods sold took {100 - m_a:.1f}% of revenue, compared with {100 - m_b:.1f}%.",
                magnitude=f"Gross margin {m_a:.1f}% vs {m_b:.1f}%",
                period_compared=f"{_range_text(after)} vs {_range_text(before)}",
                evidence_type="calculated",
                effect_on_forecast="Less of each dollar of revenue is left to cover operating expenses."
                if m_a < m_b else "More of each dollar of revenue is left to cover operating expenses.",
                support="supported",
                impact="unfavorable" if m_a < m_b else "favorable",
                fact_ids=(rev.fact_ids[-6:] if rev else []) + (cogs.fact_ids[-6:] if cogs else []),
                weight=abs(m_a - m_b) / 100 * sum(rev_hist[p] for p in after),
            )

    # Supplier price changes (observed in documents, effect not yet in the history).
    seen = set()
    for f in facts:
        if f.metric == "supplier_price_change_pct" and f.value and f.entity not in seen:
            seen.add(f.entity)
            eff = f.attributes.get("effective_date")
            add(
                subject="company.cogs",
                title=f"{f.entity} price {'increase' if f.value > 0 else 'decrease'}",
                what_changed=f"{f.entity} announced a {f.value:g}% price {'increase' if f.value > 0 else 'decrease'}"
                + (f" effective {eff}." if eff else "."),
                magnitude=f"{f.value:+g}%",
                period_compared=None,
                evidence_type="observed",
                effect_on_forecast=(
                    "Likely to raise material costs. It is not yet visible in the monthly history, so the statistical "
                    "forecast does not include it. Project estimates include it where open orders are listed."
                ),
                support="plausible",
                impact="unfavorable" if f.value > 0 else "favorable",
                fact_ids=[f.id],
                weight=0,
            )

    # Hiring and contract notes from the documents: plausible context, never treated as proof.
    for f in facts:
        if f.metric != "business_note" or not f.text_value:
            continue
        text = f.text_value
        if re.search(r"\bhir(e|es|ed|ing)\b|headcount", text, re.I):
            add(
                subject="company.operating_expenses",
                title="Hiring mentioned in the documents",
                what_changed=text,
                evidence_type="observed",
                effect_on_forecast="May explain part of the payroll increase and may keep it rising. Not separately "
                "quantified in the forecast.",
                support="plausible",
                fact_ids=[f.id],
                weight=0,
            )
        elif re.search(r"contract|customer", text, re.I) and re.search(r"revenue|sales", text, re.I):
            add(
                subject="company.revenue",
                title="Revenue context in the documents",
                what_changed=text,
                evidence_type="observed",
                effect_on_forecast="Possible reason for the revenue trend. The records show an association, not proof.",
                support="plausible",
                fact_ids=[f.id],
                weight=0,
            )
    return drivers


def project_drivers(projects: list[ProjectForecast]) -> list[Driver]:
    drivers: list[Driver] = []

    def add(**kw) -> None:
        drivers.append(Driver(id=f"PDRV{len(drivers)+1:02d}", scope="project", **kw))

    for p in projects:
        cur = p.currency or "USD"
        if p.cpi is not None and p.utilization_pct is not None and p.percent_complete is not None:
            add(
                subject=p.project,
                title="Spending ahead of progress" if p.cpi < 0.98 else "Spending in line with progress",
                what_changed=f"{p.utilization_pct:.0f}% of the budget spent for {p.percent_complete:.0f}% of the work.",
                magnitude=f"Cost performance index {p.cpi:.2f}",
                period_compared=f"Project start to {p.monthly_costs[-1].period if p.monthly_costs else 'latest report'}",
                evidence_type="calculated",
                effect_on_forecast="If this efficiency continues, the final cost will be "
                + ("higher than budget." if p.cpi < 0.98 else "close to budget."),
                support="supported",
                impact="unfavorable" if p.cpi < 0.98 else "favorable",
                fact_ids=[x for x in [p.actual_fact_id, p.budget_fact_id] if x],
                weight=abs((p.eac or 0) - (p.budget or p.eac or 0)),
            )
        if p.supplier_impact:
            add(
                subject=p.project,
                title="Supplier price increase on open orders",
                what_changed="; ".join(
                    f"{i['supplier']} {i['price_change_pct']:g}% on {i['po']} ({money(i['open_value'], cur)} open)"
                    for i in p.supplier_impact["items"]
                ),
                magnitude=money(p.supplier_impact["amount"], cur, signed=True),
                evidence_type="calculated",
                effect_on_forecast="Added to the estimated final cost.",
                support="supported",
                impact="unfavorable",
                fact_ids=p.supplier_impact["fact_ids"],
                weight=p.supplier_impact["amount"],
            )
        if p.delay_days and p.delay_days > 0:
            add(
                subject=p.project,
                title="Schedule slip",
                what_changed=f"Forecast completion moved from {p.planned_completion} to {p.forecast_completion}.",
                magnitude=f"{p.delay_days} days",
                evidence_type="observed",
                effect_on_forecast="More months of spending before completion. The recent-spending estimate "
                "reflects this; the earned-value estimate does not depend on dates.",
                support="plausible",
                impact="unfavorable",
                fact_ids=[m["fact_id"] for m in p.late_milestones],
                weight=(p.recent_monthly_cost or 0) * p.delay_days / 30,
            )
        if len(p.monthly_costs) >= 6:
            last3 = sum(x.value for x in p.monthly_costs[-3:]) / 3
            prev3 = sum(x.value for x in p.monthly_costs[-6:-3]) / 3
            ch = pct_change(last3, prev3)
            if ch is not None and abs(ch) >= 5:
                add(
                    subject=p.project,
                    title="Monthly spending " + ("rising" if ch > 0 else "falling"),
                    what_changed=f"Average monthly cost {money(last3, cur)} in the last 3 months vs {money(prev3, cur)} before.",
                    magnitude=f"{ch:+.0f}%",
                    period_compared=f"{month_label(p.monthly_costs[-3].period)} to {month_label(p.monthly_costs[-1].period)} "
                    f"vs {month_label(p.monthly_costs[-6].period)} to {month_label(p.monthly_costs[-4].period)}",
                    evidence_type="calculated",
                    effect_on_forecast="Raises the recent-spending estimate of final cost." if ch > 0
                    else "Lowers the recent-spending estimate of final cost.",
                    support="supported",
                    impact="unfavorable" if ch > 0 else "favorable",
                    fact_ids=[],
                    weight=abs(last3 - prev3) * 3,
                )
    return drivers


def top_reasons(company: list[Driver], projects: list[Driver], limit: int = 3, tone: str = "uncertain") -> list[Driver]:
    """Pick the most influential, best-supported drivers that explain the overall direction.

    When the outlook is unfavorable (or favorable), drivers pushing the same way come first.
    One slot is kept for a project driver when one points the same way.
    """
    wanted = {"unfavorable": "unfavorable", "favorable": "favorable"}.get(tone)
    supported = [d for d in company + projects if d.support == "supported"]
    aligned = [d for d in supported if wanted is None or d.impact == wanted]
    out: list[Driver] = []
    proj = sorted([d for d in aligned if d.scope == "project"], key=lambda d: -d.weight)
    comp = sorted([d for d in aligned if d.scope == "company"], key=lambda d: -d.weight)
    reserve = proj[:1]
    for d in comp:
        if len(out) >= limit - len(reserve):
            break
        out.append(d)
    out += reserve
    for d in sorted(proj[1:] + [x for x in supported if x not in aligned], key=lambda d: -d.weight):
        if len(out) >= limit:
            break
        if d not in out:
            out.append(d)
    return out[:limit]
