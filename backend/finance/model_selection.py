"""Choose a forecasting model appropriate to the amount of data, and build ranges."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from finance.models import MODEL_BY_NAME, MODELS
from finance.validation import MIN_OBS_FOR_VALIDATION, BacktestResult, first_origin, rolling_origin_backtest

Z_80 = 1.2816  # two-sided 80% normal quantile, used for approximate ranges
SIMPLER_TOLERANCE = 0.02  # prefer a simpler model if within 2% of the best MAE


@dataclass
class Selection:
    model: Optional[str]
    reason: str
    sufficiency: str  # insufficient | limited | moderate | good
    scores: list[BacktestResult] = field(default_factory=list)
    point: Optional[np.ndarray] = None
    low: Optional[np.ndarray] = None
    high: Optional[np.ndarray] = None
    validated: bool = False
    step_sigma: list[float] = field(default_factory=list)


def sufficiency_label(n: int) -> str:
    if n < 6:
        return "insufficient"
    if n < MIN_OBS_FOR_VALIDATION:
        return "limited"
    if n < 18:
        return "moderate"
    return "good"


def select_and_forecast(y: np.ndarray, horizon: int) -> Selection:
    n = len(y)
    suff = sufficiency_label(n)
    if n < 6:
        return Selection(
            model=None,
            reason=f"Only {n} monthly observation(s). At least 6 are needed for a numerical forecast.",
            sufficiency=suff,
        )
    if n < MIN_OBS_FOR_VALIDATION:
        model = MODEL_BY_NAME["naive"]
        point = model.fn(y, horizon)
        diffs = np.diff(y.astype(float))
        sigma = float(np.std(diffs, ddof=1)) if len(diffs) > 1 else float(abs(y[-1]) * 0.1)
        steps = np.arange(1, horizon + 1)
        half = Z_80 * sigma * np.sqrt(steps)
        return Selection(
            model=model.name,
            reason=(
                f"Only {n} months of history, too few to validate competing models. "
                "Using the naive baseline with a wide range."
            ),
            sufficiency=suff,
            point=point,
            low=point - half,
            high=point + half,
            validated=False,
            step_sigma=[sigma * float(np.sqrt(s)) for s in steps],
        )

    start = first_origin(n)
    candidates = [m for m in MODELS if m.min_train <= start and not (m.min_train >= 24 and n < 24)]
    scores: list[BacktestResult] = []
    for m in candidates:
        r = rolling_origin_backtest(y, m, horizon, start)
        if r is not None:
            scores.append(r)
    if not scores:
        return Selection(model=None, reason="No model could be validated on this history.", sufficiency=suff)
    best = min(scores, key=lambda s: s.mae)
    # Prefer the simplest model whose error is within tolerance of the best.
    near = [s for s in scores if s.mae <= best.mae * (1 + SIMPLER_TOLERANCE)]
    chosen = min(near, key=lambda s: MODEL_BY_NAME[s.model].complexity)
    model = MODEL_BY_NAME[chosen.model]
    point = model.fn(y, horizon)

    # Ranges: empirical error spread per step where available, scaled by sqrt(step) beyond.
    sig1_errors = chosen.errors_by_step.get(1, [])
    base_sigma = float(np.sqrt(np.mean(np.square(sig1_errors)))) if sig1_errors else float(chosen.mae * 1.25)
    sigmas = []
    for k in range(1, horizon + 1):
        errs = chosen.errors_by_step.get(k, [])
        rule = base_sigma * np.sqrt(k)
        if len(errs) >= 3:
            emp = float(np.sqrt(np.mean(np.square(errs))))
            sigmas.append(max(emp, rule))
        else:
            sigmas.append(rule)
    sig = np.array(sigmas)
    naive_score = next((s for s in scores if s.model == "naive"), None)
    reason = (
        f"Compared {len(scores)} models using rolling-origin backtests over {chosen.n_origins} cutoffs. "
        f"{model.label} had the lowest average error (MAE {chosen.mae:,.0f}"
        + (f", MAPE {chosen.mape:.1f}%" if np.isfinite(chosen.mape) else "")
        + ")"
        + (f" versus the naive baseline (MAE {naive_score.mae:,.0f})." if naive_score and chosen.model != "naive" else ".")
    )
    if chosen.model != best.model:
        reason += f" A more complex model scored within {SIMPLER_TOLERANCE:.0%}, so the simpler one was kept."
    return Selection(
        model=model.name,
        reason=reason,
        sufficiency=suff,
        scores=sorted(scores, key=lambda s: s.mae),
        point=point,
        low=point - Z_80 * sig,
        high=point + Z_80 * sig,
        validated=True,
        step_sigma=list(sig),
    )


def detect_outliers(y: np.ndarray, threshold: float = 3.5) -> tuple[list[int], np.ndarray]:
    """Robust outlier detection on residuals from a linear fit (median / MAD).

    Returns indices of outliers and a winsorized copy used for model fitting.
    The raw history is still shown to the user.
    """
    n = len(y)
    if n < 6:
        return [], y.astype(float)
    t = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(t, y.astype(float), 1)
    resid = y - (intercept + slope * t)
    med = np.median(resid)
    mad = np.median(np.abs(resid - med)) * 1.4826
    if mad == 0:
        return [], y.astype(float)
    z = (resid - med) / mad
    fitted = intercept + slope * t
    # Flag only points that are statistically unusual AND materially large (over 5% of the trend level).
    rel = np.abs(resid) / np.maximum(np.abs(fitted), 1e-9)
    idx = [int(i) for i in np.where((np.abs(z) > threshold) & (rel > 0.05))[0]]
    clean = y.astype(float).copy()
    for i in idx:
        bound = threshold * mad * np.sign(z[i])
        clean[i] = intercept + slope * t[i] + med + bound
    return idx, clean
