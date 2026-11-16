"""Compose the simple financial outlook from forecasts, drivers, and agent results.

The headline, labels, and numbers are produced deterministically from the
calculation layer. Agent output adds interpretation and review; Alex's verdict
can qualify or withhold the overall conclusion.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from domain import ExtractionResult
from finance.drivers import top_reasons
from finance.formatting import money, month_label, pct
from finance.scenarios import run_scenario
from finance.types import CompanyForecast, Driver, MetricForecast, ProjectForecast, ScenarioInput

HEADLINE_METRICS = ["revenue", "operating_expenses", "operating_profit", "cash_balance", "cash_flow"]
ARROWS = {"increase": "↑", "decrease": "↓", "stable": "→", "unknown": "?"}


def tone_for(m: MetricForecast) -> str:
    if m.method == "none" or not m.forecast:
        return "uncertain"
    if m.direction_confidence == "tentative" and m.effect in ("favorable", "unfavorable"):
        return "uncertain"
    return {"favorable": "favorable", "unfavorable": "unfavorable", "neutral": "neutral"}.get(m.effect, "uncertain")


def metric_line(m: MetricForecast, cur: str) -> dict:
    if m.method == "none" or not m.forecast:
        display = "Insufficient data for a reliable forecast"
    elif m.is_balance:
        display = f"{ARROWS[m.direction]} {money(m.end_value, cur)} by {month_label(m.forecast[-1].period)}"
        if m.change_pct is not None:
            display += f" ({pct(m.change_pct)})"
    elif m.metric == "cash_flow":
        w = min(len(m.forecast), len(m.history)) or 1
        display = (f"{ARROWS[m.direction]} {money(m.forecast_total / w, cur)} per month estimated "
                   f"(recently {money(m.recent_total / w, cur)})")
    else:
        display = f"{ARROWS[m.direction]} {pct(m.change_pct)} estimated" if m.change_pct is not None else ARROWS[m.direction]
    if m.forecast and m.direction_confidence == "tentative":
        display += ", tentative"
    detail = None
    if m.forecast and not m.is_balance and m.forecast_total is not None and m.metric != "cash_flow":
        detail = (f"{m.comparison_text}: {money(m.forecast_total, cur)} forecast (range {money(m.forecast_total_low, cur)} "
                  f"to {money(m.forecast_total_high, cur)}) vs {money(m.recent_total, cur)} actual.")
    elif m.forecast and m.is_balance:
        detail = (f"Range {money(m.end_low, cur)} to {money(m.end_high, cur)} at {month_label(m.forecast[-1].period)}; "
                  f"latest actual {money(m.recent_total, cur)}.")
    return {
        "id": m.id, "metric": m.metric, "label": m.label, "direction": m.direction,
        "direction_confidence": m.direction_confidence, "change_pct": m.change_pct, "change_abs": m.change_abs,
        "effect": m.effect, "effect_reason": m.effect_reason, "tone": tone_for(m), "display": display, "detail": detail,
        "reliable": m.reliable, "message": m.message, "sufficiency": m.sufficiency, "fact_ids": m.fact_ids[-12:],
        "history": [p.model_dump() for p in m.history], "forecast": [p.model_dump() for p in m.forecast],
    }


def project_line(p: ProjectForecast) -> dict:
    cur = p.currency or "USD"
    primary = next((m for m in p.methods if m.name == p.primary_method), None)
    budget_text = money(p.budget, cur) if p.budget is not None and p.budget_status in ("confirmed", "user_supplied") else (
        " or ".join(money(c.value, cur) for c in p.budget_candidates) + " (unresolved)" if p.budget_candidates else "Not found"
    )
    if p.variance is not None and p.budget_status in ("confirmed", "user_supplied"):
        variance_text = f"{money(p.variance, cur, signed=True)} ({pct(p.variance_pct)})"
    elif p.variance_by_budget:
        variance_text = "; ".join(f"{money(v['variance'], cur, signed=True)} vs {money(v['budget'], cur)}" for v in p.variance_by_budget)
    else:
        variance_text = "n/a"
    return {
        "id": p.id, "project": p.project, "eac": p.eac, "eac_text": money(p.eac, cur) if p.eac is not None else "Not enough information",
        "eac_range_text": f"{money(p.eac_low, cur)} to {money(p.eac_high, cur)}" if p.eac_low is not None and len(p.methods) > 1 else None,
        "budget_text": budget_text, "budget_status": p.budget_status, "variance_text": variance_text,
        "outlook": p.outlook, "tone": p.tone, "method_label": primary.label if primary else None,
        "method_formula": primary.formula if primary else None, "reliable": p.reliable, "message": p.message,
        "delay_days": p.delay_days, "fact_ids": p.fact_ids[:15], "insights": p.insights,
        "utilization_pct": p.utilization_pct, "percent_complete": p.percent_complete,
        "monthly_costs": [x.model_dump() for x in p.monthly_costs],
    }


def overall_label(cf: CompanyForecast, projects: list[ProjectForecast]) -> tuple[str, str]:
    # Operating profitability is the central business-health signal. A sharp,
    # unfavorable profit decline should not be labeled "MIXED" just because
    # revenue also increased; that would contradict the financial headline.
    profit = cf.get("operating_profit") or cf.get("net_profit")
    if (profit and profit.forecast and profit.effect == "unfavorable"
            and profit.direction == "decrease" and profit.change_pct is not None
            and profit.change_pct <= -10):
        return "LIKELY DETERIORATING", "unfavorable"
    score = 0.0
    signals = 0
    pos = neg = 0
    profit = cf.get("operating_profit") or cf.get("net_profit") or cf.get("gross_profit")
    weights = [(profit, 2.0), (cf.get("revenue"), 1.0), (cf.get("cash_balance"), 1.0)]
    for m, w in weights:
        if m is None or m.method == "none" or not m.forecast:
            continue
        signals += 1
        if m.effect == "favorable":
            score += w
            pos += 1
        elif m.effect == "unfavorable":
            score -= w
            neg += 1
    for p in projects:
        if p.eac is None:
            continue
        signals += 1
        if p.tone == "unfavorable":
            score -= 1
            neg += 1
        elif p.tone == "favorable":
            score += 0.5
            pos += 1
    if signals == 0:
        return "NOT ENOUGH INFORMATION", "uncertain"
    if score <= -2:
        return "LIKELY DETERIORATING", "unfavorable"
    if score >= 2:
        return "LIKELY IMPROVING", "favorable"
    if pos and neg:
        return "MIXED", "uncertain"
    return "LIKELY STABLE", "neutral"


def headline(cf: CompanyForecast, projects: list[ProjectForecast], cur: str) -> str:
    H = cf.horizon_months
    rev, opx, cogs = cf.get("revenue"), cf.get("operating_expenses"), cf.get("cogs")
    op = cf.get("operating_profit") or cf.get("net_profit")
    parts = []
    if op and op.forecast:
        faster = [c for c in (opx, cogs) if c and rev and c.change_pct is not None and rev.change_pct is not None
                  and c.change_pct > rev.change_pct + 1]
        if op.direction == "decrease" and faster:
            parts.append(f"costs are rising faster than revenue, which is likely to reduce {op.label.lower()} over the next {H} months")
        elif op.direction == "decrease":
            parts.append(f"{op.label.lower()} is likely to decline over the next {H} months")
        elif op.direction == "increase":
            parts.append(f"{op.label.lower()} is likely to grow over the next {H} months")
        elif op.direction == "stable":
            parts.append(f"{op.label.lower()} is expected to stay close to recent levels over the next {H} months")
    elif rev and rev.forecast:
        parts.append(f"revenue is likely to {'grow' if rev.direction == 'increase' else 'fall' if rev.direction == 'decrease' else 'hold steady'} "
                     f"over the next {H} months, but profit cannot be forecast from the documents")
    over = [p.project for p in projects if p.tone == "unfavorable" and p.eac is not None]
    depends = [p.project for p in projects if p.outlook == "Depends on which budget applies"]
    project_part = ""
    if over:
        names = " and ".join(over) if len(over) <= 2 else f"{', '.join(over[:-1])}, and {over[-1]}"
        project_part = f"{names} {'is' if len(over) == 1 else 'are'} forecast to exceed {'its approved budget' if len(over) == 1 else 'their approved budgets'}"
    if depends:
        dep = " and ".join(depends)
        project_part = (project_part + "; " if project_part else "") + f"the outlook for {dep} depends on which budget applies"
    if not parts and not project_part:
        return "Not enough information to produce a reliable financial outlook from these documents."
    text = "Based on the available information, " + (parts[0] if parts else "")
    if project_part:
        text += (". " + project_part[0].upper() + project_part[1:]) if parts else project_part
    return text + "."


def sensitivities(cf: CompanyForecast, projects: list[ProjectForecast], cur: str) -> list[str]:
    H = cf.horizon_months
    out = []

    def op_delta(inp: ScenarioInput) -> tuple[Optional[float], float]:
        r = run_scenario(inp, cf, projects, cur)
        op = next((l for l in r.lines if l.key == "operating_profit"), None)
        proj = sum(l.difference or 0 for l in r.lines if l.key.endswith(".eac"))
        return (op.difference if op else None), proj

    d, proj = op_delta(ScenarioInput(supplier_cost_change_pct=5))
    if d is not None or proj:
        text = "Supplier costs: a further 5% increase would "
        text += (f"{'lower' if d < 0 else 'raise'} operating profit by {money(abs(d), cur)} over {H} months"
                 if d is not None else "change operating profit by an unknown amount")
        if proj:
            text += f" and add {money(proj, cur)} to project costs"
        out.append(text + ".")
    d, _ = op_delta(ScenarioInput(revenue_change_pct=-5))
    if d is not None:
        out.append(f"Revenue: 5% below forecast would {'lower' if d < 0 else 'raise'} operating profit by {money(abs(d), cur)} over {H} months.")
    d, _ = op_delta(ScenarioInput(opex_change_pct=-3))
    if d is not None:
        out.append(f"Operating expenses: a 3% reduction would add {money(d, cur)} to operating profit over {H} months.")
    late = [p for p in projects if p.recent_monthly_cost and p.eac is not None]
    if late:
        p = max(late, key=lambda x: x.recent_monthly_cost)
        _, proj = op_delta(ScenarioInput(project_delay_weeks=4, delayed_project=p.project))
        if proj:
            out.append(f"Schedule: each further 4-week delay on {p.project} could add about {money(proj, cur)} at its recent spending rate.")
    return out


def data_quality(ex: ExtractionResult, cf: CompanyForecast, questions: list[dict], agent_status: dict,
                 rejected_agent_facts: int) -> dict:
    score = 100
    limitations: list[str] = []
    rev = cf.get("revenue")
    n = max((m.data_points for m in cf.metrics if m.method == "statistical"), default=0)
    if n == 0:
        score -= 40
        limitations.append("No monthly company history was found, so company-level forecasts are not possible.")
    elif n < 6:
        score -= 50
        limitations.append(f"Only {n} months of company history were available, too few for a numerical forecast.")
    elif n < 12:
        score -= 25
        limitations.append(f"Only {n} months of company history were available. Forecasts are rough baselines.")
    elif n < 24:
        score -= 10
        limitations.append(f"Only {n} months of history were available, so seasonal patterns cannot be detected.")
    unresolved = [c for c in ex.conflicts if c.material and not c.resolved_fact_id]
    if unresolved:
        score -= 15 * len(unresolved)
        limitations += [f"Unresolved: {c.description}" for c in unresolved]
    skipped = [q for q in questions if q["status"] == "skipped"]
    for q in skipped:
        score -= 15 if q["importance"] == "essential" else 5
        limitations.append(f"Skipped question: {q['text']}")
    crit = [i for i in ex.issues if i.severity == "critical"]
    warn = [i for i in ex.issues if i.severity == "warning"]
    score -= 20 * len(crit) + min(15, 3 * len(warn))
    uncertain_dups = [d for d in ex.duplicates if d.kind == "uncertain"]
    if uncertain_dups:
        limitations.append(f"{len(uncertain_dups)} possible duplicate record(s) need review.")
    if rejected_agent_facts:
        limitations.append(f"{rejected_agent_facts} AI-extracted fact(s) were discarded because they could not be matched to the source text.")
    if not agent_status.get("ai_enabled"):
        limitations.append("AI agents were not run (no OpenAI API key configured). Results come from the calculation engine only.")
    elif agent_status.get("failed"):
        limitations.append("Some AI agents failed: " + ", ".join(agent_status["failed"]) + ". Their sections are missing.")
        errors = agent_status.get("errors") or {}
        first = next((str(v) for v in errors.values() if v), None)
        if first:
            limitations.append("Reason given by the AI service: " + first[:300])
    score = max(0, min(100, score))
    label = "Good" if score >= 80 else "Fair" if score >= 60 else "Limited" if score >= 40 else "Poor"
    return {
        "label": label, "score": score, "limitations": limitations,
        "important_limitation": limitations[0] if limitations else None,
        "history_months": n, "issues": [i.model_dump() for i in ex.issues],
        "conflicts": [c.model_dump() for c in ex.conflicts], "duplicates": [d.model_dump() for d in ex.duplicates],
    }


def why_section(cf: CompanyForecast, projects: list[ProjectForecast], company_drivers: list[Driver],
                project_drivers: list[Driver], reasons: list[Driver], cur: str) -> dict:
    movements = []
    subject_map = {
        "operating_profit": ["company.operating_profit", "company.operating_expenses", "company.gross_profit", "company.cogs", "company.revenue"],
        "operating_expenses": ["company.operating_expenses"],
        "revenue": ["company.revenue"],
        "cogs": ["company.cogs", "company.gross_profit"],
        "gross_profit": ["company.gross_profit", "company.cogs"],
        "cash_balance": ["company.operating_profit"],
    }
    for m in cf.metrics:
        if m.direction not in ("increase", "decrease") or not m.forecast:
            continue
        subjects = subject_map.get(m.metric, [m.id])
        ds = [d for d in company_drivers if d.subject in subjects]
        ds.sort(key=lambda d: (subjects.index(d.subject), -d.weight))
        if not ds:
            continue
        movements.append({
            "id": m.id, "title": f"{m.label} {'increasing' if m.direction == 'increase' else 'decreasing'}",
            "tone": tone_for(m), "summary": f"{pct(m.change_pct)} ({m.comparison_text})" if m.change_pct is not None else m.comparison_text,
            "drivers": [d.model_dump() for d in ds[:4]],
        })
    for p in projects:
        ds = [d for d in project_drivers if d.subject == p.project]
        if ds:
            movements.append({
                "id": p.id, "title": f"{p.project}: {p.outlook.lower()}", "tone": p.tone,
                "summary": f"Estimated final cost {money(p.eac, cur)}" if p.eac is not None else "",
                "drivers": [d.model_dump() for d in ds],
            })
    plain = " ".join(_reason_sentence(d) for d in reasons)
    return {"plain_language": plain, "movements": movements}


def _reason_sentence(d: Driver) -> str:
    s = d.what_changed.rstrip(".")
    if d.scope == "project" and not s.lower().startswith(d.subject.lower()):
        s = f"{d.subject}: {s[0].lower() + s[1:]}"
    return s + "."


def reason_item(d: Driver) -> dict:
    title = d.title if d.scope == "company" else f"{d.subject}: {d.title.lower()}"
    text = d.what_changed + (f" {d.effect_on_forecast}" if d.effect_on_forecast else "")
    return {"driver_id": d.id, "title": title, "text": text, "magnitude": d.magnitude, "fact_ids": d.fact_ids,
            "evidence_type": d.evidence_type, "support": d.support}


def next_step_text(company_drivers: list[Driver], projects: list[ProjectForecast], tone: str) -> str:
    parts = []
    cats = sorted([d for d in company_drivers if d.subject == "company.operating_expenses" and d.support == "supported"
                   and d.impact == "unfavorable" and d.title.endswith("rose")], key=lambda d: -d.weight)
    margin = next((d for d in company_drivers if d.subject == "company.gross_profit" and d.impact == "unfavorable"), None)
    if cats:
        parts.append(f"review the rise in {cats[0].title.replace(' costs rose', '').lower()} costs against revenue growth")
    elif margin:
        parts.append("review supplier and material costs, which are narrowing the gross margin")
    worst = sorted([p for p in projects if p.tone == "unfavorable" and p.variance is not None], key=lambda p: -(p.variance or 0))
    if worst:
        parts.append(f"reassess the remaining spending on {worst[0].project}")
    unresolved = [p.project for p in projects if p.budget_status == "unresolved"]
    if unresolved:
        parts.append(f"confirm the approved budget for {unresolved[0]}")
    if not parts:
        return ("Keep monitoring the main revenue and cost lines monthly and re-run Sentinel when new figures arrive."
                if tone != "unfavorable" else "Review the largest cost increases and re-run Sentinel with updated figures.")
    text = parts[0][0].upper() + parts[0][1:]
    if len(parts) == 2:
        text += f", and {parts[1]}"
    elif len(parts) > 2:
        text += ", " + ", ".join(parts[1:-1]) + f", and {parts[-1]}"
    return text + "."


def compose_outlook(ex: ExtractionResult, cf: CompanyForecast, projects: list[ProjectForecast],
                    company_drivers: list[Driver], project_drivers: list[Driver], questions: list[dict],
                    agents: dict, assumptions: list[str], files: list[dict]) -> dict:
    cur = ex.currency or "USD"
    label, tone = overall_label(cf, projects)
    text = headline(cf, projects, cur)
    review = agents.get("alex")
    verdict = review["overall_verdict"] if review else "not_reviewed"
    qualifier = None
    if verdict == "withhold":
        qualifier = "Alex, the independent reviewer, withheld support for this conclusion: " + review["verdict_reason"]
        label, tone = "CONCLUSION WITHHELD", "uncertain"
    elif verdict == "qualify":
        qualifier = "Qualified by the independent reviewer: " + review["verdict_reason"]

    lines = [metric_line(m, cur) for m in cf.metrics if m.metric in HEADLINE_METRICS]
    other_lines = [metric_line(m, cur) for m in cf.metrics if m.metric not in HEADLINE_METRICS]
    if not any(l["metric"] == "cash_flow" for l in lines) and cf.metrics:
        lines.append({"id": "company.cash_flow", "metric": "cash_flow", "label": "Net cash flow", "tone": "uncertain",
                      "display": "Insufficient data for a reliable forecast", "direction": "unknown", "reliable": False,
                      "message": "No cash information was found.", "fact_ids": [], "history": [], "forecast": []})
    reasons = top_reasons(company_drivers, project_drivers, 3, tone)
    what_changes = sensitivities(cf, projects, cur)
    if review:
        what_changes += [w for w in review.get("what_could_change_outlook", [])[:2]]
    agent_status = agents.get("_status", {})
    dq = data_quality(ex, cf, questions, agent_status, agents.get("_rejected_facts", 0))
    if review and review.get("recommended_next_step"):
        next_step = review["recommended_next_step"]
    elif reasons or projects:
        next_step = next_step_text(company_drivers, projects, tone)
    else:
        next_step = "Upload more financial history to support a forecast."

    methodology = []
    for m in cf.metrics:
        methodology.append({
            "id": m.id, "label": m.label, "method": m.method, "model": m.model_label, "reason": m.model_reason,
            "formula": m.formula, "history_months": m.data_points, "sufficiency": m.sufficiency, "validated": m.validated,
            "validation": [v.model_dump() for v in m.validation], "assumptions": m.assumptions, "outliers": m.outliers,
            "gaps": m.gaps,
        })
    for p in projects:
        methodology.append({
            "id": p.id, "label": f"{p.project} final cost", "method": "project",
            "model": next((x.label for x in p.methods if x.name == p.primary_method), None),
            "reason": "Estimates are listed from strongest to weakest evidence; the strongest available is used.",
            "methods": [x.model_dump() for x in p.methods], "assumptions": p.assumptions,
        })

    all_assumptions = list(assumptions) + cf.notes
    for m in cf.metrics:
        all_assumptions += [f"{m.label}: {a}" for a in m.assumptions]
    for p in projects:
        all_assumptions += [f"{p.project}: {a}" for a in p.assumptions]
        for meth in p.methods:
            if meth.name == p.primary_method and meth.note:
                all_assumptions.append(f"{p.project}: {meth.note}")
    for q in questions:
        if q["status"] == "skipped":
            all_assumptions.append(f"Unresolved (question skipped): {q['text']}")
    all_assumptions = list(dict.fromkeys(all_assumptions))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "company_name": ex.company_name or "Your company",
        "currency": cur,
        "as_of": ex.as_of_period,
        "as_of_label": month_label(ex.as_of_period),
        "horizon_months": cf.horizon_months,
        "forecast_window": {"start": cf.forecast_start, "end": cf.forecast_end,
                            "label": f"{month_label(cf.forecast_start)} to {month_label(cf.forecast_end)}" if cf.forecast_start else None},
        "overall": {"label": label, "tone": tone, "headline": text, "qualifier": qualifier, "reviewer_verdict": verdict},
        "company": lines,
        "company_other": other_lines,
        "projects": [project_line(p) for p in projects],
        "reasons": [reason_item(d) for d in reasons],
        "what_could_change": what_changes,
        "data_quality": dq,
        "next_step": next_step,
        "why": why_section(cf, projects, company_drivers, project_drivers, reasons, cur),
        "methodology": methodology,
        "assumptions": all_assumptions,
        "answers": [
            {"id": q["id"], "text": q["text"], "status": q["status"], "answer": q.get("answer_text"),
             "interpretation": q.get("interpretation"), "changed_analysis": q.get("changed_analysis"),
             "change_summary": q.get("change_summary"), "importance": q["importance"]}
            for q in questions
        ],
        "files": files,
    }
