"""Deterministic checks on agent claims, given to Alex as evidence.

For each finding: do the cited ids exist, and does every number in the
statement match a known fact or calculation (allowing for rounding)?
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from agents.schemas import CompanyAnalysis, Finding, ProjectAnalysisSet

NUM_RE = re.compile(
    r"(?P<cur>[$€£])?\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(?P<suf>%|k\b|m\b|million|thousand|percentage points)?",
    re.I,
)


def extract_numbers(text: str) -> list[tuple[float, str]]:
    out = []
    for m in NUM_RE.finditer(text):
        raw = m.group("num").replace(",", "")
        try:
            v = float(raw)
        except ValueError:
            continue
        suf = (m.group("suf") or "").lower()
        if suf in ("k", "thousand"):
            v *= 1e3
        elif suf in ("m", "million"):
            v *= 1e6
        kind = "pct" if suf in ("%", "percentage points") else ("money" if m.group("cur") or suf in ("k", "m", "million", "thousand") else "plain")
        # Skip years, day counts, and small counts that are not financial claims.
        if kind == "plain" and (1900 <= v <= 2100 or v < 100):
            continue
        out.append((v, kind))
    return out


def number_supported(value: float, kind: str, known: Iterable[float]) -> bool:
    for k in known:
        if k is None:
            continue
        if kind == "pct":
            if abs(abs(value) - abs(k)) <= 0.6:
                return True
        else:
            tol = max(1.0, 0.01 * abs(k))
            # Allow rounding to thousands, e.g. "$548k" for 548,000 or "$570,000" for 570,180.
            if abs(abs(value) - abs(k)) <= tol or abs(abs(value) - abs(k)) <= 1000 and abs(k) >= 50000:
                return True
    return False


def _check(claim_id: str, f: Finding, known_ids: set[str], known_numbers: list[float]) -> dict:
    cited = f.cited_fact_ids + f.cited_calculation_ids
    unknown = [c for c in cited if c not in known_ids]
    numbers = extract_numbers(f.statement)
    unverified = [f"{v:g}{'%' if k == 'pct' else ''}" for v, k in numbers if not number_supported(v, k, known_numbers)]
    if not cited:
        status = "no_citations"
    elif unknown or unverified:
        status = "partially_verified" if len(unknown) < len(cited) else "unverified"
    else:
        status = "verified"
    return {
        "claim_id": claim_id,
        "title": f.title,
        "statement": f.statement,
        "cited": cited,
        "unknown_ids": unknown,
        "numbers_found": len(numbers),
        "unverified_numbers": unverified,
        "status": status,
    }


def check_claims(emily: Optional[CompanyAnalysis], sebas: Optional[ProjectAnalysisSet],
                 known_ids: set[str], known_numbers: list[float]) -> list[dict]:
    results = []
    if emily:
        for i, f in enumerate(emily.findings, start=1):
            results.append(_check(f"emily.{i}", f, known_ids, known_numbers))
    if sebas:
        for p in sebas.projects:
            for i, f in enumerate(p.findings, start=1):
                results.append(_check(f"sebas.{p.project}.{i}", f, known_ids, known_numbers))
    return results


def collect_known_numbers(extraction, cf, projects, drivers) -> list[float]:
    """Every number an agent may legitimately quote."""
    nums: list[float] = []
    for f in extraction.active_facts():
        if f.value is not None:
            nums.append(f.value)
    for m in cf.metrics:
        for v in (m.change_pct, m.recent_total, m.forecast_total, m.forecast_total_low, m.forecast_total_high,
                  m.end_value, m.end_low, m.end_high, m.change_abs):
            if v is not None:
                nums.append(v)
        nums += [p.value for p in m.history] + [p.value for p in m.forecast]
        if m.recent_total and m.forecast_total and m.history:
            w = min(len(m.forecast), len(m.history))
            nums += [m.recent_total / w, m.forecast_total / w]
    for p in projects:
        for v in (p.budget, p.actual_cost, p.utilization_pct, p.percent_complete, p.cpi, p.elapsed_pct, p.committed,
                  p.management_forecast, p.eac, p.eac_low, p.eac_high, p.estimate_to_complete, p.variance,
                  p.variance_pct, p.delay_days, p.recent_monthly_cost):
            if v is not None:
                nums.append(float(v))
        nums += [m.eac for m in p.methods] + [c.value for c in p.budget_candidates]
        nums += [x["variance"] for x in p.variance_by_budget] + [x["variance_pct"] for x in p.variance_by_budget]
        if p.supplier_impact:
            nums.append(p.supplier_impact["amount"])
            for i in p.supplier_impact["items"]:
                nums += [i["open_value"], i["impact"], i["price_change_pct"]]
        if p.budget and p.eac:
            nums.append((p.eac - p.budget) / p.budget * 100)
    for d in drivers:
        for text in (d.magnitude or "", d.what_changed or ""):
            nums += [v for v, _ in extract_numbers(text)]
    return nums
