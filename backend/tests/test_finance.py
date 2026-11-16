"""Financial calculations, forecasting models, validation, scenarios."""
import numpy as np
import pytest

from domain import ExtractionResult, Fact, SourceRef
from finance import calculations as calc
from finance.company_forecast import build_company_forecast, forecast_statistical
from finance.model_selection import detect_outliers, select_and_forecast
from finance.models import MODEL_BY_NAME, linear_trend, naive
from finance.project_forecast import build_project_forecasts
from finance.scenarios import run_scenario
from finance.types import ScenarioInput, SeriesPoint
from finance.validation import first_origin, rolling_origin_backtest


# ----------------------------------------------------------- formulas
def test_budget_utilization():
    assert calc.budget_utilization(405_000, 500_000) == pytest.approx(81.0)
    assert calc.budget_utilization(100, 0) is None


def test_budget_variance_and_eac():
    eac = calc.estimate_at_completion(405_000, 98_000)
    assert eac == 503_000
    assert calc.budget_variance(eac, 500_000) == 3_000
    assert calc.budget_variance(None, 500_000) is None


def test_cost_to_complete_performance_based():
    # 405k spent for 72% complete -> 562.5k at completion; CPI = 0.889
    assert calc.performance_based_eac(405_000, 72, 500_000) == pytest.approx(562_500)
    assert calc.cost_performance_index(405_000, 72, 500_000) == pytest.approx(0.8889, abs=1e-4)
    assert calc.performance_based_eac(405_000, 0, 500_000) is None


def test_profit_and_margin():
    assert calc.gross_margin_pct(1_000_000, 460_000) == pytest.approx(54.0)
    assert calc.pct_change(110, 100) == pytest.approx(10.0)
    assert calc.pct_change(-90, -100) == pytest.approx(10.0)


def test_currency_precision():
    assert calc.round_money(0.125) == 0.13
    assert calc.round_money(2.675) == 2.68  # binary float would give 2.67
    assert calc.round_money(-1.005) == -1.01


# ----------------------------------------------------------- models
def test_naive_baseline():
    assert list(naive(np.array([1.0, 2.0, 5.0]), 3)) == [5.0, 5.0, 5.0]


def test_linear_trend_extends_slope():
    y = np.array([10.0, 20, 30, 40, 50])
    assert linear_trend(y, 2) == pytest.approx([60.0, 70.0])


def test_trend_forecasting_selects_trend_model():
    y = np.array([100 + 5 * i + (1 if i % 2 else -1) for i in range(14)], dtype=float)
    sel = select_and_forecast(y, 6)
    assert sel.validated and sel.model in ("linear_trend", "holt_damped")
    assert sel.point[-1] > y[-1]
    assert np.all(sel.low <= sel.point) and np.all(sel.high >= sel.point)


def test_forecast_range_widens_with_horizon():
    rng = np.random.default_rng(1)
    y = 100 + np.cumsum(rng.normal(0, 3, 16))
    sel = select_and_forecast(y, 6)
    widths = sel.high - sel.low
    assert widths[-1] >= widths[0]


def test_limited_history_uses_baseline_and_no_validation():
    sel = select_and_forecast(np.array([10.0, 11, 12, 13, 14, 15, 16]), 3)
    assert sel.model == "naive" and not sel.validated and sel.sufficiency == "limited"


def test_insufficient_history_refuses_numbers():
    pts = [SeriesPoint(period=f"2026-0{i}", value=v) for i, v in zip(range(1, 5), [10, 12, 13, 15])]
    mf = forecast_statistical("revenue", pts, 3)
    assert mf.forecast == [] and not mf.reliable
    assert "Not enough information to produce a reliable numerical forecast" in mf.message
    assert mf.direction == "increase" and mf.direction_confidence == "tentative"


def test_time_aware_validation_never_uses_future_data():
    seen_lengths = []

    def spy(y, h):
        seen_lengths.append(len(y))
        return np.repeat(y[-1], h)

    from finance.models import ModelSpec

    y = np.arange(12, dtype=float)
    res = rolling_origin_backtest(y, ModelSpec("spy", "spy", "", 1, 0, spy), 3, first_origin(12))
    assert seen_lengths == list(range(6, 12))  # each fit sees only data before its cutoff
    assert res.n_origins == 6


def test_seasonal_models_not_forced_on_short_history():
    y = np.array([100.0 + i for i in range(14)])
    sel = select_and_forecast(y, 6)
    assert all(s.model not in ("holt_winters", "seasonal_naive") for s in sel.scores)


def test_outlier_detected_and_dampened():
    y = np.array([100.0, 102, 104, 106, 108, 300, 112, 114, 116, 118])
    idx, clean = detect_outliers(y)
    assert idx == [5] and clean[5] < 200 and y[5] == 300


def test_small_dips_are_not_outliers():
    y = np.array([100.0, 101, 98.5, 103, 104, 105, 104.2, 107, 108, 109])
    idx, _ = detect_outliers(y)
    assert idx == []


def test_missing_reporting_periods_use_recent_contiguous_run():
    vals = {"2025-01": 10, "2025-02": 11, "2025-05": 20, "2025-06": 21, "2025-07": 22, "2025-08": 23, "2025-09": 24,
            "2025-10": 25, "2025-11": 26, "2025-12": 27}
    pts = [SeriesPoint(period=k, value=v) for k, v in vals.items()]
    mf = forecast_statistical("revenue", pts, 3)
    assert mf.gaps == ["2025-03", "2025-04"] and mf.data_points == 8


# ----------------------------------------------------------- company & projects on sample
def test_revenue_and_expense_movement(extraction):
    cf = build_company_forecast(extraction, 6)
    rev, opx, op = cf.get("revenue"), cf.get("operating_expenses"), cf.get("operating_profit")
    assert rev.direction == "increase" and rev.effect == "favorable"
    assert opx.direction == "increase" and opx.effect == "unfavorable"
    assert opx.change_pct > rev.change_pct
    assert op.direction == "decrease" and op.effect == "unfavorable"
    assert cf.profit_formula == "revenue - cogs - operating_expenses"
    assert cf.forecast_start == "2026-11" and cf.forecast_end == "2027-04"


def test_derived_profit_matches_components(extraction):
    cf = build_company_forecast(extraction, 6)
    r, c, o, p = (cf.get(m).forecast[0].value for m in ("revenue", "cogs", "operating_expenses", "operating_profit"))
    assert p == pytest.approx(r - c - o)


def test_cash_bridge_uses_linkage_answer(extraction):
    projects = build_project_forecasts(extraction, {})
    plain = build_company_forecast(extraction, 6, None, projects).get("cash_balance")
    sep = build_company_forecast(extraction, 6, "separate", projects).get("cash_balance")
    assert plain.method == "statistical" and sep.method == "bottom_up"
    assert sep.end_value < plain.end_value


def test_project_forecast_alpha(extraction):
    alpha = next(p for p in build_project_forecasts(extraction, {}) if p.project == "Project Alpha")
    assert alpha.budget == 500_000 and alpha.budget_status == "confirmed"
    assert alpha.utilization_pct == pytest.approx(81.0)
    assert alpha.primary_method == "performance"
    assert alpha.supplier_impact["amount"] == pytest.approx(64_000 * 0.12)
    assert alpha.eac == pytest.approx(405_000 / 0.72 + 7_680)
    assert alpha.variance == pytest.approx(alpha.eac - 500_000)
    assert alpha.outlook == "Likely to exceed budget"
    assert alpha.delay_days == 31


def test_unresolved_budget_shows_both_outcomes(extraction):
    beacon = next(p for p in build_project_forecasts(extraction, {}) if p.project == "Project Beacon")
    assert beacon.budget_status == "unresolved"
    assert beacon.outlook == "Depends on which budget applies"
    assert {round(v["budget"]) for v in beacon.variance_by_budget} == {300_000, 325_000}


def test_answer_changes_project_calculation(extraction):
    a = next(p for p in build_project_forecasts(extraction, {"budget:Project Beacon": {"value": 300000}}) if p.project == "Project Beacon")
    b = next(p for p in build_project_forecasts(extraction, {"budget:Project Beacon": {"value": 325000}}) if p.project == "Project Beacon")
    assert a.outlook == "At risk of exceeding budget" and b.outlook == "Close to budget"
    assert a.variance - b.variance == pytest.approx(25_000)


def test_project_without_progress_does_not_assume_proportional_spend():
    src = SourceRef(file_id="x", file_name="x.xlsx")
    facts = [
        Fact(id="F1", entity_type="project", entity="P", metric="budget_approved", value=100, source=src),
        Fact(id="F2", entity_type="project", entity="P", metric="actual_cost", value=80, source=src),
    ]
    ex = ExtractionResult(facts=facts, projects=["P"], currency="USD", as_of_period="2026-10")
    p = build_project_forecasts(ex, {})[0]
    assert p.eac is None and "Not enough information" in p.message
    assert "Progress is not reported" in p.insights[0]


# ----------------------------------------------------------- scenarios
def test_scenario_changes_are_computed(extraction):
    projects = build_project_forecasts(extraction, {"budget:Project Beacon": {"value": 300000}})
    cf = build_company_forecast(extraction, 6, "separate", projects)
    base = run_scenario(ScenarioInput(), cf, projects)
    assert all(abs(l.difference) < 1e-6 for l in base.lines)
    r = run_scenario(ScenarioInput(revenue_change_pct=10), cf, projects)
    rev = next(l for l in r.lines if l.key == "revenue")
    op = next(l for l in r.lines if l.key == "operating_profit")
    cogs = next(l for l in r.lines if l.key == "cogs")
    assert rev.difference == pytest.approx(rev.original * 0.10)
    assert op.difference == pytest.approx(rev.difference - cogs.difference)
    assert "hypothetical" in " ".join(r.assumptions).lower()
    d = run_scenario(ScenarioInput(project_delay_weeks=4, delayed_project="Project Alpha"), cf, projects)
    alpha = next(l for l in d.lines if l.key == "project.Project Alpha.eac")
    assert alpha.difference > 0 and not any(l.key.startswith("project.Project Beacon") for l in d.lines)


def test_months_between_accepts_written_months():
    """AI-extracted project dates may use written month names."""
    from finance.calculations import months_between
    assert months_between("2026-10", "January 2027") == 3
    assert months_between("Jan 2027", "2027-04") == 3
    assert months_between("2027-01-15", "2027-03") == 2
