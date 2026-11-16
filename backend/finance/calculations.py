"""Explicit, testable financial formulas. Every function documents its formula."""
from __future__ import annotations

from datetime import date
from typing import Optional


def safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def pct_change(new: Optional[float], old: Optional[float]) -> Optional[float]:
    """Percent change = (new - old) / |old| x 100."""
    if new is None or old is None or old == 0:
        return None
    return (new - old) / abs(old) * 100.0


def budget_utilization(actual_cost: Optional[float], budget: Optional[float]) -> Optional[float]:
    """Budget Utilization = Actual Cost / Approved Budget x 100."""
    r = safe_div(actual_cost, budget)
    return None if r is None else r * 100.0


def estimate_at_completion(actual_cost: float, estimate_to_complete: float) -> float:
    """Estimate at Completion = Actual Cost + Estimate to Complete."""
    return actual_cost + estimate_to_complete


def budget_variance(eac: Optional[float], budget: Optional[float]) -> Optional[float]:
    """Forecast Budget Variance = Estimate at Completion - Approved Budget (positive = overrun)."""
    if eac is None or budget is None:
        return None
    return eac - budget


def performance_based_eac(actual_cost: float, percent_complete: float, budget: float) -> Optional[float]:
    """Earned-value EAC = BAC / CPI where CPI = EV / AC and EV = BAC x % complete.

    Simplifies to AC / (% complete / 100). Assumes remaining work is delivered at
    the same cost efficiency as completed work.
    """
    if percent_complete is None or percent_complete <= 0 or actual_cost is None or budget is None:
        return None
    ev = budget * percent_complete / 100.0
    cpi = ev / actual_cost if actual_cost else None
    if not cpi:
        return None
    return budget / cpi


def cost_performance_index(actual_cost: float, percent_complete: float, budget: float) -> Optional[float]:
    """CPI = Earned Value / Actual Cost, Earned Value = Budget x % complete."""
    if not actual_cost or percent_complete is None or budget is None:
        return None
    return budget * percent_complete / 100.0 / actual_cost


def gross_margin_pct(revenue: Optional[float], cogs: Optional[float]) -> Optional[float]:
    """Gross margin % = (Revenue - COGS) / Revenue x 100."""
    if revenue in (None, 0) or cogs is None:
        return None
    return (revenue - cogs) / revenue * 100.0


def months_between(start: str, end: str) -> int:
    """Whole months between ISO periods or written calendar months."""
    from datetime import datetime

    def parse(value: str):
        value = str(value).strip()
        for fmt in ("%Y-%m", "%Y-%m-%d", "%B %Y", "%b %Y", "%B %d, %Y", "%b %d, %Y", "%m/%Y"):
            try:
                date = datetime.strptime(value, fmt)
                return date.year, date.month
            except ValueError:
                pass
        raise ValueError(f"Unsupported date format: {value!r}")

    y1, m1 = parse(start)
    y2, m2 = parse(end)
    return (y2 - y1) * 12 + m2 - m1


def add_months(period: str, n: int) -> str:
    y, m = int(period[:4]), int(period[5:7])
    total = y * 12 + (m - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def period_end_date(period: str) -> date:
    y, m = int(period[:4]), int(period[5:7])
    nxt = date(y + (m // 12), m % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)


def elapsed_schedule_pct(start: str, planned_end: str, as_of: date) -> Optional[float]:
    """Share of planned duration elapsed = (as_of - start) / (planned_end - start) x 100."""
    s, e = date.fromisoformat(start), date.fromisoformat(planned_end)
    if e <= s:
        return None
    return max(0.0, min(150.0, (as_of - s).days / (e - s).days * 100.0))


def round_money(value: Optional[float]) -> Optional[float]:
    """Currency precision: round half away from zero to cents."""
    if value is None:
        return None
    from decimal import ROUND_HALF_UP, Decimal

    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
