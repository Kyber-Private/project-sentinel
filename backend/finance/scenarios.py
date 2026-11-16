"""What-If scenarios. Pure Python recalculation; the AI never produces these numbers."""
from __future__ import annotations

from typing import Optional

from finance.formatting import money
from finance.types import CompanyForecast, ProjectForecast, ScenarioInput, ScenarioLine, ScenarioResult

WEEKS_PER_MONTH = 52 / 12


def _sum(mf, n: int) -> Optional[float]:
    if mf is None or not mf.forecast:
        return None
    return float(sum(p.value for p in mf.forecast[:n]))


def run_scenario(inp: ScenarioInput, cf: CompanyForecast, projects: list[ProjectForecast],
                 currency: str = "USD") -> ScenarioResult:
    H = cf.horizon_months
    res = ScenarioResult(input=inp, horizon_months=H)
    r, o, s = inp.revenue_change_pct / 100, inp.opex_change_pct / 100, inp.supplier_cost_change_pct / 100
    hire = inp.extra_monthly_hiring_cost

    rev0 = _sum(cf.get("revenue"), H)
    cogs0 = _sum(cf.get("cogs"), H)
    opx0 = _sum(cf.get("operating_expenses"), H)
    op_mf = cf.get("operating_profit")
    op0 = _sum(op_mf, H)
    cash_mf = cf.get("cash_balance")

    rev1 = rev0 * (1 + r) if rev0 is not None else None
    # COGS is treated as variable: it scales with revenue volume and with supplier prices.
    cogs1 = cogs0 * (1 + r) * (1 + s) if cogs0 is not None else None
    opx1 = opx0 * (1 + o) + hire * H if opx0 is not None else None

    if r:
        res.changed.append(f"Revenue {inp.revenue_change_pct:+g}% against the forecast")
        res.assumptions.append("Cost of goods sold moves in proportion to revenue (treated as a variable cost).")
    if o:
        res.changed.append(f"Operating expenses {inp.opex_change_pct:+g}%")
    if s:
        res.changed.append(f"Supplier costs {inp.supplier_cost_change_pct:+g}%")
        res.assumptions.append(
            "The supplier change applies to cost of goods sold and to open project purchase orders."
        )
    if hire:
        res.changed.append(f"Extra hiring cost {money(hire, currency)} per month")

    lines: list[ScenarioLine] = []

    def line(key, label, a, b, higher_is_good: bool):
        if a is None or b is None:
            return
        diff = b - a
        fav = None if abs(diff) < 0.5 else ((diff > 0) == higher_is_good)
        lines.append(ScenarioLine(key=key, label=label, original=a, new=b, difference=diff, favorable=fav))

    line("revenue", f"Revenue, next {H} months", rev0, rev1, True)
    line("cogs", f"Cost of goods sold, next {H} months", cogs0, cogs1, False)
    line("operating_expenses", f"Operating expenses, next {H} months", opx0, opx1, False)

    op1 = None
    if op0 is not None:
        formula = (op_mf.formula or "") if op_mf else ""
        delta = 0.0
        if rev0 is not None:
            delta += rev1 - rev0
        if cogs0 is not None and "cost of goods" in formula:
            delta -= cogs1 - cogs0
        if opx0 is not None:
            delta -= opx1 - opx0
        op1 = op0 + delta
        line("operating_profit", f"Operating profit, next {H} months", op0, op1, True)

    # Projects
    project_delta_total = 0.0
    for p in projects:
        if p.eac is None:
            continue
        add = 0.0
        notes = []
        if s and p.supplier_impact:
            open_value = sum(i["open_value"] for i in p.supplier_impact["items"])
            extra = open_value * (1 + p.supplier_impact["items"][0]["price_change_pct"] / 100) * s
            add += extra
            notes.append(f"supplier change on open orders {money(extra, currency, signed=True)}")
        elif s and p.committed:
            extra = p.committed * s
            add += extra
            notes.append(f"supplier change applied to remaining commitments {money(extra, currency, signed=True)}")
        if inp.project_delay_weeks and (inp.delayed_project in (None, "", p.project)) and p.recent_monthly_cost:
            extra = p.recent_monthly_cost * inp.project_delay_weeks / WEEKS_PER_MONTH
            add += extra
            notes.append(
                f"{inp.project_delay_weeks:g}-week delay at the recent rate of {money(p.recent_monthly_cost, currency)} per month "
                f"{money(extra, currency, signed=True)}"
            )
        if add:
            project_delta_total += add
            line(f"project.{p.project}.eac", f"{p.project} estimated final cost", p.eac, p.eac + add, False)
            if p.budget is not None:
                line(f"project.{p.project}.variance", f"{p.project} variance vs budget",
                     p.eac - p.budget, p.eac + add - p.budget, False)
            res.explanations.append(f"{p.project}: " + "; ".join(notes) + ".")
    if inp.project_delay_weeks:
        target = inp.delayed_project or "each project"
        res.changed.append(f"{target} delayed {inp.project_delay_weeks:g} weeks")
        res.assumptions.append(
            "During a delay, spending continues at the project's average monthly cost over the last 3 months."
        )

    # Cash
    if cash_mf and cash_mf.forecast and op1 is not None and op0 is not None:
        cash0 = cash_mf.forecast[-1].value
        cash_delta = (op1 - op0)
        if cash_mf.method == "bottom_up" and "project" in (cash_mf.formula or ""):
            cash_delta -= project_delta_total
            if project_delta_total:
                res.assumptions.append("Extra project costs are paid in cash within the forecast period.")
        line("cash_balance", f"Cash at end of period", cash0, cash0 + cash_delta, True)

    res.lines = lines
    # Plain explanation of why the outcome moved.
    op_line = next((l for l in lines if l.key == "operating_profit"), None)
    if op_line and op_line.difference:
        parts = []
        if rev0 is not None and r:
            parts.append(f"revenue {money(rev1 - rev0, currency, signed=True)}")
        if cogs0 is not None and (r or s):
            parts.append(f"cost of goods sold {money(cogs1 - cogs0, currency, signed=True)}")
        if opx0 is not None and (o or hire):
            parts.append(f"operating expenses {money(opx1 - opx0, currency, signed=True)}")
        res.explanations.insert(
            0,
            f"Operating profit moves {money(op_line.difference, currency, signed=True)} over {H} months because "
            + ", ".join(parts) + ".",
        )
    if not res.changed:
        res.explanations.append("No assumptions were changed, so the scenario matches the forecast.")
    res.assumptions.append("This is a hypothetical scenario, not a confirmed prediction.")
    return res
