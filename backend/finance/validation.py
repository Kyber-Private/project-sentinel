"""Time-aware validation (rolling origin). Never uses random splits."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from finance.models import ModelSpec

MIN_OBS_FOR_VALIDATION = 8


@dataclass
class BacktestResult:
    model: str
    mae: float
    mape: float
    n_origins: int
    errors_by_step: dict[int, list[float]] = field(default_factory=dict)


def first_origin(n: int) -> int:
    """First training cutoff: at least 6 months, and at least half the history."""
    return max(6, int(np.ceil(n * 0.5)))


def rolling_origin_backtest(y: np.ndarray, model: ModelSpec, horizon: int, start: int) -> BacktestResult | None:
    """Fit on y[:o] and forecast the next steps for each origin o >= start.

    Errors are collected per forecast step so prediction ranges can widen with
    the horizon. Returns None if the model cannot be evaluated.
    """
    n = len(y)
    if start < model.min_train or start >= n:
        return None
    abs_errors: list[float] = []
    pct_errors: list[float] = []
    by_step: dict[int, list[float]] = {}
    origins = 0
    for o in range(start, n):
        steps = min(horizon, n - o)
        try:
            pred = model.fn(y[:o], steps)
        except Exception:
            return None
        if not np.all(np.isfinite(pred)):
            return None
        origins += 1
        for k in range(steps):
            err = float(y[o + k] - pred[k])
            abs_errors.append(abs(err))
            if y[o + k] != 0:
                pct_errors.append(abs(err) / abs(y[o + k]) * 100.0)
            by_step.setdefault(k + 1, []).append(err)
    if not abs_errors:
        return None
    return BacktestResult(
        model=model.name,
        mae=float(np.mean(abs_errors)),
        mape=float(np.mean(pct_errors)) if pct_errors else float("nan"),
        n_origins=origins,
        errors_by_step=by_step,
    )
