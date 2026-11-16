"""Candidate time-series forecasting models.

Each model takes a 1D array of monthly observations and a horizon h and
returns h point forecasts. Models are deliberately simple; Sentinel works
with small business datasets where complex models overfit.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Callable

import numpy as np


@dataclass(frozen=True)
class ModelSpec:
    name: str
    label: str
    description: str
    min_train: int
    complexity: int
    fn: Callable[[np.ndarray, int], np.ndarray]


def naive(y: np.ndarray, h: int) -> np.ndarray:
    return np.repeat(y[-1], h).astype(float)


def moving_average_3(y: np.ndarray, h: int) -> np.ndarray:
    return np.repeat(float(np.mean(y[-3:])), h)


def linear_trend(y: np.ndarray, h: int) -> np.ndarray:
    t = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(t, y.astype(float), 1)
    future = np.arange(len(y), len(y) + h, dtype=float)
    return intercept + slope * future


def simple_exponential_smoothing(y: np.ndarray, h: int) -> np.ndarray:
    """SES with alpha chosen by minimizing in-sample one-step squared error."""
    y = y.astype(float)
    best_alpha, best_sse, best_level = 0.5, np.inf, y[-1]
    for alpha in np.linspace(0.1, 0.95, 18):
        level = y[0]
        sse = 0.0
        for v in y[1:]:
            sse += (v - level) ** 2
            level = alpha * v + (1 - alpha) * level
        if sse < best_sse:
            best_alpha, best_sse, best_level = alpha, sse, level
    return np.repeat(best_level, h)


def holt_damped(y: np.ndarray, h: int) -> np.ndarray:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = ExponentialSmoothing(y.astype(float), trend="add", damped_trend=True,
                                   initialization_method="estimated").fit(optimized=True)
        return np.asarray(fit.forecast(h), dtype=float)


def holt_winters_seasonal(y: np.ndarray, h: int) -> np.ndarray:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = ExponentialSmoothing(y.astype(float), trend="add", seasonal="add", seasonal_periods=12,
                                   initialization_method="estimated").fit(optimized=True)
        return np.asarray(fit.forecast(h), dtype=float)


def seasonal_naive(y: np.ndarray, h: int) -> np.ndarray:
    return np.array([y[len(y) - 12 + (i % 12)] for i in range(h)], dtype=float)


MODELS: list[ModelSpec] = [
    ModelSpec("naive", "Naive baseline", "Next months equal the latest month.", 1, 0, naive),
    ModelSpec("moving_average_3", "3-month moving average", "Next months equal the average of the last 3 months.", 3, 1, moving_average_3),
    ModelSpec("ses", "Exponential smoothing", "Weighted average that favors recent months, no trend.", 3, 2, simple_exponential_smoothing),
    ModelSpec("linear_trend", "Linear trend", "Straight-line trend fitted to the history and extended forward.", 4, 3, linear_trend),
    ModelSpec("holt_damped", "Damped trend smoothing", "Exponential smoothing with a trend that flattens over time.", 8, 4, holt_damped),
    ModelSpec("seasonal_naive", "Seasonal naive", "Each month equals the same month last year.", 24, 5, seasonal_naive),
    ModelSpec("holt_winters", "Seasonal smoothing (Holt-Winters)", "Trend plus a yearly seasonal pattern.", 24, 6, holt_winters_seasonal),
]
MODEL_BY_NAME = {m.name: m for m in MODELS}
