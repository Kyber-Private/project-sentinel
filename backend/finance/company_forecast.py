"""Company-level forecasts: revenue, costs, profit, and cash."""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

import numpy as np

from domain import COMPANY_SERIES_METRICS, METRIC_LABELS, ExtractionResult, Fact
from finance.calculations import add_months, months_between, pct_change
from finance.formatting import month_label
from finance.model_selection import Z_80, detect_outliers, select_and_forecast
from finance.models import MODEL_BY_NAME
from finance.types import CompanyForecast, ForecastPoint, MetricForecast, ModelScore, ProjectForecast, SeriesPoint

FLOW_METRICS = {"revenue", "cogs", "gross_profit", "operating_expenses", "operating_profit", "net_profit", "cash_flow"}
BALANCE_METRICS = {"cash_balance", "accounts_receivable", "accounts_payable", "debt"}
# +1: an increase is good, -1: an increase is bad, 0: depends on context.
EFFECT_SIGN = {
    "revenue": 1, "gross_profit": 1, "operating_profit": 1, "net_profit": 1, "cash_balance": 1, "cash_flow": 1,
    "cogs": -1, "operating_expenses": -1, "debt": -1, "accounts_receivable": 0, "accounts_payable": 0,
}
STABLE_THRESHOLD_PCT = 2.0
DISPLAY_ORDER = [
    "revenue", "cogs", "gross_profit", "operating_expenses", "operating_profit", "net_profit",
    "cash_balance", "cash_flow", "accounts_receivable", "accounts_payable", "debt",
]


def collect_series(extraction: ExtractionResult) -> tuple[dict[str, list[SeriesPoint]], list[str]]:
    """Monthly actuals per company metric. Returns (series, notes)."""
    by_metric: dict[str, dict[str, list[Fact]]] = defaultdict(lambda: defaultdict(list))
    for f in extraction.active_facts():
        if f.entity_type != "company" or f.metric not in COMPANY_SERIES_METRICS:
            continue
        if not f.period or len(f.period) != 7 or f.value is None:
            continue
        if f.qualifier not in (None, "actual"):
            continue
        by_metric[f.metric][f.period].append(f)
    series: dict[str, list[SeriesPoint]] = {}
    notes: list[str] = []
    for metric, periods in by_metric.items():
        pts = []
        for period in sorted(periods):
            facts = periods[period]
            chosen = facts[0]
            if len(facts) > 1:
                notes.append(
                    f"{METRIC_LABELS.get(metric, metric)} for {month_label(period)} has more than one value; "
                    f"used {chosen.value:,.0f} from {chosen.source.label()}."
                )
            pts.append(SeriesPoint(period=period, value=float(chosen.value), fact_id=chosen.id))
        series[metric] = pts
    return series, notes


def contiguous_tail(points: list[SeriesPoint]) -> tuple[list[SeriesPoint], list[str]]:
    """Longest run of consecutive months ending at the latest month, and the missing months."""
    if not points:
        return [], []
    pts = sorted(points, key=lambda p: p.period)
    gaps: list[str] = []
    for a, b in zip(pts, pts[1:]):
        missing = months_between(a.period, b.period) - 1
        for k in range(1, missing + 1):
            gaps.append(add_months(a.period, k))
    tail = [pts[-1]]
    for p in reversed(pts[:-1]):
        if months_between(p.period, tail[0].period) == 1:
            tail.insert(0, p)
        else:
            break
    return tail, gaps


def _window_text(start: str, n: int) -> str:
    end = add_months(start, n - 1)
    return f"{month_label(start)} to {month_label(end)}"


def _finish(mf: MetricForecast, history_values: list[float]) -> MetricForecast:
    """Compute totals, direction, and confidence for a metric forecast."""
    if not mf.forecast:
        return mf
    n = len(history_values)
    H = len(mf.forecast)
    mf.end_value = mf.forecast[-1].value
    mf.end_low = mf.forecast[-1].low
    mf.end_high = mf.forecast[-1].high
    if mf.is_balance:
        last = history_values[-1] if history_values else None
        mf.recent_total = last
        mf.change_pct = pct_change(mf.end_value, last)
        mf.change_abs = None if last is None else mf.end_value - last
        mf.comparison_text = (
            f"Balance at {month_label(mf.forecast[-1].period)} vs {month_label(mf.history[-1].period)}"
            if mf.history else ""
        )
        inside = last is not None and mf.end_low <= last <= mf.end_high
    else:
        w = min(H, n)
        mf.recent_total = float(sum(history_values[-w:]))
        mf.forecast_total = float(sum(p.value for p in mf.forecast[:w]))
        mf.forecast_total_low = float(sum(p.low for p in mf.forecast[:w]))
        mf.forecast_total_high = float(sum(p.high for p in mf.forecast[:w]))
        mf.change_pct = pct_change(mf.forecast_total, mf.recent_total)
        mf.change_abs = mf.forecast_total - mf.recent_total
        if mf.metric == "cash_flow" and mf.recent_total <= 0:
            # Percent change is misleading when the base is negative; direction uses the absolute change.
            mf.change_pct = None
        hist_start = mf.history[-w].period if mf.history else None
        mf.comparison_text = (
            f"Next {w} months ({_window_text(mf.forecast[0].period, w)}) vs last {w} months "
            f"({_window_text(hist_start, w)})" if hist_start else ""
        )
        inside = mf.forecast_total_low <= mf.recent_total <= mf.forecast_total_high
    if mf.change_pct is None and mf.change_abs is not None and mf.recent_total is not None:
        scale = max(abs(mf.recent_total), 1.0)
        mf.direction = "stable" if abs(mf.change_abs) / scale * 100 < STABLE_THRESHOLD_PCT else (
            "increase" if mf.change_abs > 0 else "decrease")
    elif mf.change_pct is None:
        mf.direction = "unknown"
    elif abs(mf.change_pct) < STABLE_THRESHOLD_PCT:
        mf.direction = "stable"
    else:
        mf.direction = "increase" if mf.change_pct > 0 else "decrease"
    mf.direction_confidence = "tentative" if inside else "clear"
    return mf


def forecast_statistical(metric: str, points: list[SeriesPoint], horizon: int, label: Optional[str] = None) -> MetricForecast:
    tail, gaps = contiguous_tail(points)
    mf = MetricForecast(
        id=f"company.{metric}", metric=metric, label=label or METRIC_LABELS.get(metric, metric),
        history=sorted(points, key=lambda p: p.period), horizon_months=horizon, gaps=gaps,
        data_points=len(tail), is_balance=metric in BALANCE_METRICS,
        fact_ids=[p.fact_id for p in points if p.fact_id],
    )
    if gaps:
        mf.assumptions.append(
            f"{len(gaps)} missing month(s) in the history; only the most recent {len(tail)} consecutive months were used."
        )
    y = np.array([p.value for p in tail], dtype=float)
    outlier_idx, y_fit = detect_outliers(y)
    if outlier_idx:
        mf.outliers = [tail[i].period for i in outlier_idx]
        mf.assumptions.append(
            "Unusual month(s) " + ", ".join(month_label(p) for p in mf.outliers)
            + " were dampened when fitting the model. The original values are still shown."
        )
    sel = select_and_forecast(y_fit, horizon)
    mf.sufficiency = sel.sufficiency
    mf.model_reason = sel.reason
    mf.validated = sel.validated
    if sel.model is None or sel.point is None:
        mf.method = "none"
        mf.reliable = False
        mf.message = "Not enough information to produce a reliable numerical forecast."
        if len(y) >= 3:
            slope = np.polyfit(np.arange(len(y)), y, 1)[0]
            mf.direction = "increase" if slope > 0 else "decrease" if slope < 0 else "stable"
            mf.direction_confidence = "tentative"
            mf.message += f" Directional signal only: the {len(y)} available months trend {mf.direction}."
        return mf
    spec = MODEL_BY_NAME[sel.model]
    mf.model, mf.model_label = spec.name, spec.label
    mf.validation = [
        ModelScore(model=s.model, label=MODEL_BY_NAME[s.model].label, mae=round(s.mae, 2),
                   mape=None if not np.isfinite(s.mape) else round(s.mape, 2), n_origins=s.n_origins)
        for s in sel.scores
    ]
    start = add_months(tail[-1].period, 1)
    mf.forecast = [
        ForecastPoint(period=add_months(start, k), value=float(sel.point[k]), low=float(sel.low[k]), high=float(sel.high[k]))
        for k in range(horizon)
    ]
    mf.reliable = sel.sufficiency in ("moderate", "good")
    if sel.sufficiency == "limited":
        mf.message = "Limited history. Treat this as a rough baseline, not a dependable forecast."
    _finish(mf, list(y))
    return mf


def _combine(metric: str, label: str, parts: list[tuple[MetricForecast, int]], formula: str,
             history: list[SeriesPoint], horizon: int) -> MetricForecast:
    """Derived forecast as a signed sum of component forecasts. Ranges combine
    component half-widths in quadrature (assumes independent errors)."""
    mf = MetricForecast(
        id=f"company.{metric}", metric=metric, label=label, history=history, horizon_months=horizon,
        method="derived", formula=formula, data_points=len(history), is_balance=False,
        fact_ids=[f for p, _ in parts for f in p.fact_ids],
    )
    if any(not p.forecast for p, _ in parts):
        mf.method = "none"
        mf.message = "Not enough information to produce a reliable numerical forecast."
        return mf
    periods = [fp.period for fp in parts[0][0].forecast]
    pts = []
    for k, period in enumerate(periods):
        v = sum(sign * p.forecast[k].value for p, sign in parts)
        hw = np.sqrt(sum(((p.forecast[k].high - p.forecast[k].low) / 2) ** 2 for p, _ in parts))
        pts.append(ForecastPoint(period=period, value=float(v), low=float(v - hw), high=float(v + hw)))
    mf.forecast = pts
    mf.sufficiency = min((p.sufficiency for p, _ in parts), key=["insufficient", "limited", "moderate", "good"].index)
    mf.reliable = all(p.reliable for p, _ in parts)
    mf.validated = all(p.validated for p, _ in parts)
    mf.model_label = "Derived from component forecasts"
    mf.model_reason = f"Calculated as {formula} using each component's validated forecast."
    mf.assumptions.append("The range combines component ranges assuming their errors are independent.")
    _finish(mf, [p.value for p in history])
    return mf


def _history_combo(series: dict[str, list[SeriesPoint]], parts: list[tuple[str, int]]) -> list[SeriesPoint]:
    maps = [{p.period: p.value for p in series[m]} for m, _ in parts]
    common = sorted(set.intersection(*[set(m) for m in maps]))
    return [SeriesPoint(period=per, value=sum(sign * mp[per] for mp, (_, sign) in zip(maps, parts))) for per in common]


def detect_profit_formula(series: dict[str, list[SeriesPoint]]) -> Optional[str]:
    """Infer how operating profit relates to the reported lines, from the history itself."""
    needed = ("revenue", "operating_expenses", "operating_profit")
    if not all(m in series for m in needed):
        return None
    rev = {p.period: p.value for p in series["revenue"]}
    opx = {p.period: p.value for p in series["operating_expenses"]}
    op = {p.period: p.value for p in series["operating_profit"]}
    cogs = {p.period: p.value for p in series.get("cogs", [])}
    periods = [p for p in op if p in rev and p in opx]
    if not periods:
        return None

    def share_ok(fn) -> float:
        ok = sum(1 for p in periods if fn(p) is not None and abs(fn(p) - op[p]) <= max(1000, 0.005 * abs(rev[p])))
        return ok / len(periods)

    if cogs and share_ok(lambda p: rev[p] - cogs[p] - opx[p] if p in cogs else None) >= 0.8:
        return "revenue - cogs - operating_expenses"
    if share_ok(lambda p: rev[p] - opx[p]) >= 0.8:
        return "revenue - operating_expenses"
    return None


def project_outflows(projects: list[ProjectForecast], as_of: Optional[str], horizon: int) -> list[float]:
    """Remaining project cost spread evenly to each project's forecast completion month."""
    out = [0.0] * horizon
    if not as_of:
        return out
    for p in projects:
        if p.eac is None or p.actual_cost is None:
            continue
        remaining = max(0.0, p.eac - p.actual_cost)
        end = (p.forecast_completion or p.planned_completion or "")[:7]
        months = months_between(as_of, end) if end else horizon
        months = max(1, months)
        monthly = remaining / months
        for k in range(min(horizon, months)):
            out[k] += monthly
    return out


def forecast_cash(series: dict[str, list[SeriesPoint]], op: Optional[MetricForecast], linkage: Optional[str],
                  projects: list[ProjectForecast], project_spend_hist: dict[str, float], as_of: Optional[str],
                  horizon: int) -> Optional[MetricForecast]:
    if "cash_balance" not in series:
        return None
    stat = forecast_statistical("cash_balance", series["cash_balance"], horizon)
    if linkage not in ("included", "separate") or op is None or not op.forecast or not op.history:
        if linkage is None and projects:
            stat.assumptions.append(
                "Cash is projected from its own trend because it is not yet known whether project costs "
                "are included in operating expenses."
            )
        return stat
    cash_pts = sorted(series["cash_balance"], key=lambda p: p.period)
    op_hist = {p.period: p.value for p in op.history}
    residuals = []
    for prev, cur in zip(cash_pts, cash_pts[1:]):
        if months_between(prev.period, cur.period) != 1 or cur.period not in op_hist:
            continue
        spend = project_spend_hist.get(cur.period, 0.0) if linkage == "separate" else 0.0
        residuals.append((cur.value - prev.value) - op_hist[cur.period] + spend)
    if len(residuals) < 3:
        return stat
    avg_resid = float(np.mean(residuals))
    resid_sd = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0
    outflows = project_outflows(projects, as_of, horizon) if linkage == "separate" else [0.0] * horizon
    last = cash_pts[-1]
    start = add_months(last.period, 1)
    pts = []
    level = last.value
    op_hw_cum = 0.0
    for k in range(horizon):
        f = op.forecast[k] if k < len(op.forecast) else op.forecast[-1]
        level += f.value + avg_resid - outflows[k]
        op_hw_cum += (f.high - f.low) / 2
        hw = np.sqrt(op_hw_cum ** 2 + (Z_80 * resid_sd) ** 2 * (k + 1))
        pts.append(ForecastPoint(period=add_months(start, k), value=float(level), low=float(level - hw), high=float(level + hw)))
    mf = MetricForecast(
        id="company.cash_balance", metric="cash_balance", label=METRIC_LABELS["cash_balance"],
        history=cash_pts, forecast=pts, horizon_months=horizon, method="bottom_up",
        model_label="Cash bridge from operating profit",
        formula="cash(t) = cash(t-1) + operating profit(t) + other cash movements"
        + (" - project spending(t)" if linkage == "separate" else ""),
        model_reason=(
            "Projected from the operating profit forecast. Other cash movements use the historical monthly average "
            f"({avg_resid:,.0f}), calculated from {len(residuals)} months of reported cash and profit."
        ),
        data_points=len(cash_pts), sufficiency=op.sufficiency, reliable=op.reliable, validated=op.validated,
        is_balance=True, fact_ids=[p.fact_id for p in cash_pts if p.fact_id],
        validation=stat.validation,
    )
    mf.assumptions.append("Operating profit is assumed to turn into cash in the same month.")
    if linkage == "separate":
        mf.assumptions.append(
            "Project costs are paid outside operating expenses. Each project's remaining estimated cost is spread "
            "evenly until its forecast completion date."
        )
    else:
        mf.assumptions.append("Project costs are already inside operating expenses, so they are not subtracted again.")
    mf.assumptions.append(f"Statistical cash trend for comparison: {stat.end_value:,.0f} at the end of the period."
                          if stat.end_value is not None else "No statistical cash trend available for comparison.")
    _finish(mf, [p.value for p in cash_pts])
    return mf


def assign_effects(cf: CompanyForecast) -> None:
    rev = cf.get("revenue")
    rev_change = rev.change_pct if rev and rev.direction != "unknown" else None
    for m in cf.metrics:
        sign = EFFECT_SIGN.get(m.metric, 0)
        if m.direction == "unknown":
            m.effect, m.effect_reason = "uncertain", "Direction could not be determined."
            continue
        if m.direction == "stable":
            m.effect, m.effect_reason = "neutral", "Expected to stay within 2% of recent levels."
            continue
        up = m.direction == "increase"
        if sign == 0:
            m.effect, m.effect_reason = "uncertain", "Whether this is good or bad depends on context."
        elif sign > 0:
            m.effect = "favorable" if up else "unfavorable"
            m.effect_reason = f"Higher {m.label.lower()} is generally positive." if up else f"Lower {m.label.lower()} is a warning sign."
        else:
            if up and rev_change is not None and m.change_pct is not None and m.change_pct <= rev_change + 0.5:
                m.effect = "neutral"
                m.effect_reason = (
                    f"Rising ({m.change_pct:+.1f}%) but no faster than revenue ({rev_change:+.1f}%)."
                )
            elif up:
                m.effect = "unfavorable"
                m.effect_reason = (
                    f"Rising faster than revenue ({m.change_pct:+.1f}% vs {rev_change:+.1f}%)."
                    if rev_change is not None else "Rising costs reduce profit unless revenue keeps pace."
                )
            else:
                m.effect = "favorable"
                m.effect_reason = "Lower costs support profit."
        if m.message and not m.reliable:
            m.effect = "uncertain" if m.method == "none" else m.effect


def build_company_forecast(extraction: ExtractionResult, horizon: int, linkage: Optional[str] = None,
                           projects: Optional[list[ProjectForecast]] = None) -> CompanyForecast:
    projects = projects or []
    series, notes = collect_series(extraction)
    cf = CompanyForecast(horizon_months=horizon, notes=notes)
    if not series:
        cf.notes.append("No monthly company financial history was found in the documents.")
        return cf
    all_periods = sorted({p.period for pts in series.values() for p in pts})
    cf.first_period, cf.last_period = all_periods[0], all_periods[-1]
    cf.forecast_start = add_months(cf.last_period, 1)
    cf.forecast_end = add_months(cf.last_period, horizon)

    results: dict[str, MetricForecast] = {}
    for metric in ("revenue", "cogs", "operating_expenses", "net_profit", "accounts_receivable", "accounts_payable", "debt"):
        if metric in series:
            results[metric] = forecast_statistical(metric, series[metric], horizon)

    if "revenue" in results and "cogs" in results:
        hist = series.get("gross_profit") or _history_combo(series, [("revenue", 1), ("cogs", -1)])
        results["gross_profit"] = _combine(
            "gross_profit", METRIC_LABELS["gross_profit"], [(results["revenue"], 1), (results["cogs"], -1)],
            "revenue - cost of goods sold", hist, horizon,
        )
    elif "gross_profit" in series:
        results["gross_profit"] = forecast_statistical("gross_profit", series["gross_profit"], horizon)

    formula = detect_profit_formula(series)
    cf.profit_formula = formula
    op_parts = None
    if formula == "revenue - cogs - operating_expenses" and {"revenue", "cogs", "operating_expenses"} <= results.keys():
        op_parts = [(results["revenue"], 1), (results["cogs"], -1), (results["operating_expenses"], -1)]
        op_text = "revenue - cost of goods sold - operating expenses"
    elif formula == "revenue - operating_expenses" and {"revenue", "operating_expenses"} <= results.keys():
        op_parts = [(results["revenue"], 1), (results["operating_expenses"], -1)]
        op_text = "revenue - operating expenses"
    elif "operating_profit" not in series and {"revenue", "operating_expenses"} <= results.keys():
        if "cogs" in results:
            op_parts = [(results["revenue"], 1), (results["cogs"], -1), (results["operating_expenses"], -1)]
            op_text = "revenue - cost of goods sold - operating expenses"
        else:
            op_parts = [(results["revenue"], 1), (results["operating_expenses"], -1)]
            op_text = "revenue - operating expenses"
        cf.notes.append(f"Operating profit is not reported, so it was calculated as {op_text}.")
    if op_parts:
        hist = series.get("operating_profit") or _history_combo(
            series, [(m.metric, s) for m, s in op_parts]
        )
        results["operating_profit"] = _combine(
            "operating_profit", METRIC_LABELS["operating_profit"], op_parts, op_text, hist, horizon
        )
        if formula:
            results["operating_profit"].assumptions.append(
                f"The reported history confirms operating profit = {op_text}."
            )
    elif "operating_profit" in series:
        results["operating_profit"] = forecast_statistical("operating_profit", series["operating_profit"], horizon)

    # Cash
    proj_hist: dict[str, float] = defaultdict(float)
    for f in extraction.active_facts():
        if f.metric == "project_cost" and f.period and f.value is not None:
            proj_hist[f.period] += f.value
    cash = forecast_cash(series, results.get("operating_profit"), linkage, projects, proj_hist,
                         extraction.as_of_period, horizon)
    if cash:
        results["cash_balance"] = cash
        flat_baseline = cash.method == "statistical" and cash.model in ("naive", "moving_average_3", "ses")
        if flat_baseline:
            results["cash_flow"] = MetricForecast(
                id="company.cash_flow", metric="cash_flow", label=METRIC_LABELS["cash_flow"], horizon_months=horizon,
                method="none", data_points=max(0, len(cash.history) - 1),
                message="Not enough information to produce a reliable numerical forecast. The cash forecast is a flat "
                "baseline, so it says nothing about future cash flow.",
            )
        elif cash.forecast and len(cash.history) >= 2:
            hist_flow = [
                SeriesPoint(period=b.period, value=b.value - a.value)
                for a, b in zip(cash.history, cash.history[1:]) if months_between(a.period, b.period) == 1
            ]
            levels = [cash.history[-1].value] + [p.value for p in cash.forecast]
            flow_pts = []
            for k, p in enumerate(cash.forecast):
                v = levels[k + 1] - levels[k]
                hw = (p.high - p.low) / 2 / max(1.0, np.sqrt(k + 1))
                flow_pts.append(ForecastPoint(period=p.period, value=v, low=v - hw, high=v + hw))
            cfm = MetricForecast(
                id="company.cash_flow", metric="cash_flow", label=METRIC_LABELS["cash_flow"], history=hist_flow,
                forecast=flow_pts, horizon_months=horizon, method="derived", formula="change in cash balance",
                model_label="Derived from the cash forecast", model_reason="Monthly change in the projected cash balance.",
                data_points=len(hist_flow), sufficiency=cash.sufficiency, reliable=cash.reliable,
                validated=cash.validated, fact_ids=cash.fact_ids,
            )
            _finish(cfm, [p.value for p in hist_flow])
            results["cash_flow"] = cfm
    elif "cash_flow" in series:
        results["cash_flow"] = forecast_statistical("cash_flow", series["cash_flow"], horizon)

    cf.metrics = [results[m] for m in DISPLAY_ORDER if m in results]
    assign_effects(cf)
    return cf
