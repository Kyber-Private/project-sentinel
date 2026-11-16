"""Clarification engine: decide what to ask, interpret answers, apply them.

Questions are ranked essential > helpful > optional. At most five are asked.
Optional items never delay the investigation; they become documented
assumptions instead.
"""
from __future__ import annotations

import re
from typing import Optional

from agents.schemas import DataAnalystOutput
from config import settings
from domain import ExtractionResult
from finance.company_forecast import build_company_forecast
from finance.formatting import money

SKIP_PATTERNS = re.compile(
    r"^\s*(skip|pass|i\s*don'?t\s*know|dont\s*know|not\s*sure|unsure|unknown|idk|no\s*idea|n/?a)\b", re.I
)
IMPORTANCE_ORDER = {"essential": 0, "helpful": 1, "optional": 2}
WORD_NUMBERS = {"three": 3, "six": 6, "twelve": 12, "3": 3, "6": 6, "12": 12}


def _q(key: str, text: str, reason: str, importance: str, input_type: str = "choice",
       options: Optional[list[dict]] = None, related_fields: Optional[list[str]] = None,
       related_fact_ids: Optional[list[str]] = None, source: str = "rules") -> dict:
    return {
        "key": key, "text": text, "reason": reason, "importance": importance, "input_type": input_type,
        "options": options or [], "related_fields": related_fields or [], "related_fact_ids": related_fact_ids or [],
        "source": source,
    }


def horizon_is_material(ex: ExtractionResult) -> tuple[bool, str]:
    """True when a 3-month and a 12-month view point in different directions."""
    a = build_company_forecast(ex, 3)
    b = build_company_forecast(ex, 12)
    for metric in ("operating_profit", "net_profit", "revenue"):
        ma, mb = a.get(metric), b.get(metric)
        if ma and mb and ma.direction not in ("unknown",) and mb.direction not in ("unknown",):
            if ma.direction != mb.direction:
                return True, (
                    f"{ma.label} looks like a {ma.direction} over 3 months "
                    f"but a {mb.direction} over 12 months."
                )
            return False, ""
    return False, ""


def default_horizon(ex: ExtractionResult) -> int:
    periods = sorted({f.period for f in ex.active_facts()
                      if f.entity_type == "company" and f.period and f.metric in ("revenue", "operating_expenses")})
    n = len(periods)
    if n >= 24:
        return 12
    if n >= 12:
        return 6
    return 3


def generate_questions(ex: ExtractionResult, analyst: Optional[DataAnalystOutput], answered_keys: set[str],
                       has_company_series: bool) -> tuple[list[dict], list[str]]:
    """Return (questions to ask, assumptions recorded instead of asking)."""
    cur = ex.currency or "USD"
    cands: list[dict] = []
    assumptions: list[str] = []

    # 1. Conflicts.
    for c in ex.conflicts:
        if not c.material:
            continue
        facts = [ex.fact_by_id(fid) for fid in c.fact_ids]
        facts = [f for f in facts if f]
        if c.metric == "budget":
            options = []
            for f in facts:
                status = "approved budget" if f.metric == "budget_approved" else (f.qualifier or "status unclear")
                options.append({
                    "id": f.id, "label": money(f.value, cur), "value": f.value,
                    "description": f"{status}, from {f.source.label()}",
                })
            options.append({"id": "other", "label": "A different amount", "value": None,
                            "description": "Type the latest approved figure."})
            names = " and ".join(o["label"] for o in options[:-1])
            cands.append(_q(
                f"budget:{c.entity}",
                f"The documents show {names} as the budget for {c.entity}. Which one is the latest approved budget?",
                "The approved budget decides whether this project is forecast to go over budget.",
                "essential", options=options, related_fields=[f"project:{c.entity}:budget"], related_fact_ids=c.fact_ids,
            ))
        elif c.entity == "__company__":
            options = [{"id": f.id, "label": money(f.value, cur), "value": f.value,
                        "description": f"from {f.source.label()}"} for f in facts]
            label = c.metric.replace("_", " ")
            cands.append(_q(
                f"conflict:{c.id}",
                f"Two documents report different {label} for {c.period}. Which figure is correct?",
                f"Monthly {label} feeds directly into the forecast.",
                "essential", options=options, related_fields=[f"company:{c.metric}:{c.period}"], related_fact_ids=c.fact_ids,
            ))
        else:
            options = [{"id": f.id, "label": money(f.value, cur), "value": f.value,
                        "description": f"from {f.source.label()}"} for f in facts]
            cands.append(_q(
                f"conflict:{c.id}", f"{c.description} Which figure is correct?",
                "Conflicting figures should not be chosen arbitrarily.",
                "essential" if c.metric in ("actual_cost", "committed_cost") else "helpful",
                options=options, related_fields=[f"{c.entity}:{c.metric}"], related_fact_ids=c.fact_ids,
            ))

    # 2. Currency.
    if any(i.severity == "critical" and "currency" in i.message.lower() for i in ex.issues):
        cands.append(_q(
            "currency", "Your documents use more than one currency. Which currency should the forecast use?",
            "Mixing currencies would make every total wrong.", "essential",
            options=[{"id": c, "label": c, "value": c, "description": ""} for c in ("USD", "EUR", "GBP", "CAD", "AUD")],
            related_fields=["currency"],
        ))
    elif not ex.currency_evidence and ex.facts:
        cands.append(_q(
            "currency", "Your documents use '$' without naming the currency. Which currency are the amounts in?",
            "Needed to label every figure correctly.", "helpful",
            options=[{"id": c, "label": c, "value": c, "description": ""} for c in ("USD", "CAD", "AUD")],
            related_fields=["currency"],
        ))

    # 3. Projects: missing budget, missing basis for final cost.
    for project in ex.projects:
        pf = [f for f in ex.active_facts() if f.entity == project]
        metrics = {f.metric for f in pf}
        has_cost = "actual_cost" in metrics or "project_cost" in metrics
        if has_cost and not metrics & {"budget_approved", "budget_revised"}:
            cands.append(_q(
                f"budget:{project}", f"What is the approved budget for {project}?",
                "Without a budget Sentinel cannot tell whether the project will go over.", "essential",
                input_type="number", related_fields=[f"project:{project}:budget"],
            ))
        monthly_points = len({f.period for f in pf if f.metric == "project_cost"})
        if has_cost and not metrics & {"percent_complete", "estimate_to_complete", "forecast_at_completion"} and monthly_points < 3:
            cands.append(_q(
                f"etc:{project}",
                f"Roughly how much more do you expect {project} to cost before it is finished?",
                "The documents give no progress, forecast, or spending trend, so the final cost cannot be estimated otherwise.",
                "essential", input_type="number", related_fields=[f"project:{project}:estimate_to_complete"],
            ))

    # 4. Company / project linkage.
    if ex.projects and has_company_series and any(
        f.metric in ("actual_cost", "project_cost") for f in ex.active_facts()
    ):
        cands.append(_q(
            "linkage",
            "Are project costs already included in the company's monthly operating expenses?",
            "This decides whether project spending is counted again in the cash forecast, and avoids double counting.",
            "helpful",
            options=[
                {"id": "included", "label": "Yes, included", "value": "included", "description": "Project costs are part of operating expenses."},
                {"id": "separate", "label": "No, tracked separately", "value": "separate", "description": "For example capitalized or funded separately."},
                {"id": "partial", "label": "Partly", "value": "partial", "description": "Some project costs are included."},
            ],
            related_fields=["company:operating_expenses", "projects:actual_cost"],
        ))

    # 5. Forecast horizon, only when it changes the conclusion.
    if has_company_series:
        material, why = horizon_is_material(ex)
        if material:
            cands.append(_q(
                "horizon", "Should Sentinel focus on the next 3, 6, or 12 months?",
                "The short-term and long-term trends point in different directions. " + why,
                "helpful",
                options=[{"id": str(n), "label": f"{n} months", "value": n, "description": ""} for n in (3, 6, 12)],
                related_fields=["horizon"],
            ))
        else:
            assumptions.append(
                f"Forecast period set to {default_horizon(ex)} months based on the amount of history. "
                "A different period would not change the direction of the main results. You can change it on the outlook screen."
            )

    # 6. Data Analyst suggestions that the rules did not already cover.
    if analyst:
        covered = " ".join(c["text"].lower() + " " + " ".join(c["related_fields"]) for c in cands)
        for i, sq in enumerate(analyst.suggested_questions, start=1):
            words = set(re.findall(r"[a-z]{5,}", sq.question.lower()))
            overlap = len([w for w in words if w in covered]) / max(1, len(words))
            if overlap > 0.5:
                continue
            if sq.importance == "optional":
                assumptions.append(f"Not asked (optional): {sq.question}")
                continue
            cands.append(_q(
                f"agent:{i}:{re.sub(r'[^a-z0-9]+', '-', sq.question.lower())[:60]}", sq.question, sq.reason, sq.importance,
                input_type="choice" if sq.options else "text",
                options=[{"id": f"o{j}", "label": o, "value": o, "description": ""} for j, o in enumerate(sq.options, 1)],
                related_fields=sq.related_fields, source="data_analyst",
            ))

    cands = [c for c in cands if c["key"] not in answered_keys]
    # De-duplicate by key, keep the first.
    seen, unique = set(), []
    for c in cands:
        if c["key"] in seen:
            continue
        seen.add(c["key"])
        unique.append(c)
    unique.sort(key=lambda c: IMPORTANCE_ORDER[c["importance"]])
    asked = [c for c in unique if c["importance"] != "optional"][: settings.max_questions]
    for c in unique:
        if c not in asked:
            assumptions.append(f"Not asked: {c['text']}")
    return asked, assumptions


# ---------------------------------------------------------------- answers
def parse_amount(text: str) -> Optional[float]:
    m = re.search(r"[$€£]?\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(k|m|million|thousand)?\b", text, re.I)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    suf = (m.group(2) or "").lower()
    if suf in ("k", "thousand"):
        v *= 1e3
    elif suf in ("m", "million"):
        v *= 1e6
    return v


def interpret_deterministic(q: dict, text: str) -> Optional[dict]:
    """Interpret common answers without AI. Returns {option_id?, value, summary} or None."""
    t = text.strip().lower()
    key = q["key"]
    options = q.get("options") or []
    if key == "horizon":
        for word, n in WORD_NUMBERS.items():
            if re.search(rf"\b{word}\b", t):
                return {"option_id": str(n), "value": n, "summary": f"Use a {n}-month forecast."}
        if "quarter" in t:
            return {"option_id": "3", "value": 3, "summary": "Use a 3-month forecast."}
        if "year" in t or "annual" in t:
            return {"option_id": "12", "value": 12, "summary": "Use a 12-month forecast."}
        if "half" in t:
            return {"option_id": "6", "value": 6, "summary": "Use a 6-month forecast."}
        return None
    if key == "linkage":
        if re.search(r"\b(partly|partial|some|part)\b", t):
            return {"option_id": "partial", "value": "partial", "summary": "Project costs are partly included in operating expenses."}
        if re.search(r"\b(no|not|separate|separately|capitali[sz]ed|outside|excluded)\b", t):
            return {"option_id": "separate", "value": "separate", "summary": "Project costs are tracked separately from operating expenses."}
        if re.search(r"\b(yes|included|include|inside|part of|in opex|in operating)\b", t):
            return {"option_id": "included", "value": "included", "summary": "Project costs are included in operating expenses."}
        return None
    if key == "currency":
        for o in options:
            if o["id"].lower() in t:
                return {"option_id": o["id"], "value": o["value"], "summary": f"Amounts are in {o['value']}."}
        if "dollar" in t and "us" in t:
            return {"option_id": "USD", "value": "USD", "summary": "Amounts are in USD."}
        return None
    if q["input_type"] == "number":
        v = parse_amount(text)
        if v is None:
            return None
        return {"option_id": None, "value": v, "summary": f"Value given: {v:,.0f}."}
    if options and key.startswith("budget:"):
        picked = _interpret_budget(options, text)
        if picked:
            return picked
    if options:
        amount = parse_amount(text)
        if amount is not None:
            for o in options:
                if isinstance(o.get("value"), (int, float)) and abs(o["value"] - amount) <= 0.01 * abs(o["value"]):
                    return {"option_id": o["id"], "value": o["value"], "summary": f"Use {o['label']} ({o['description']})."}
            if key.startswith("budget:") or key.startswith("conflict:"):
                return {"option_id": "other", "value": amount, "summary": f"Use {amount:,.0f}, supplied in your answer."}
        for o in options:
            if o["label"].lower() in t or (len(o["label"]) > 3 and t in o["label"].lower()):
                return {"option_id": o["id"], "value": o["value"], "summary": f"Selected: {o['label']}."}
    return None


NEGATION = re.compile(r"\b(not|never|wasn'?t|isn'?t|no longer|unapproved|rejected|pending)\b", re.I)


def _all_amounts(text: str) -> list[float]:
    out = []
    for m in re.finditer(r"[$€£]?\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(k|m|million|thousand)?\b", text, re.I):
        v = float(m.group(1).replace(",", ""))
        suf = (m.group(2) or "").lower()
        v *= 1e3 if suf in ("k", "thousand") else 1e6 if suf in ("m", "million") else 1
        out.append(v)
    return out


def _interpret_budget(options: list[dict], text: str) -> Optional[dict]:
    """Budget answers: handle 'the original', 'the revised one', and negations like
    'the 325k was never approved'."""
    num_opts = [o for o in options if isinstance(o.get("value"), (int, float))]
    approved = [o for o in num_opts if "approved budget" in (o.get("description") or "")]
    revised = [o for o in num_opts if o not in approved]

    def match(v: float) -> Optional[dict]:
        return next((o for o in num_opts if abs(o["value"] - v) <= 0.01 * abs(o["value"])), None)

    affirmed, negated = [], []
    for clause in re.split(r"[.;,!?]|\bbut\b|\bso\b", text, flags=re.I):
        opts = [match(v) for v in _all_amounts(clause)]
        opts = [o for o in opts if o]
        (negated if NEGATION.search(clause) else affirmed).extend(opts)
    low = text.lower()
    if re.search(r"\b(original|first|initial|tracker|earlier|old)\b", low) and len(approved) == 1:
        return {"option_id": approved[0]["id"], "value": approved[0]["value"], "summary": f"Use {approved[0]['label']} (the approved budget)."}
    affirmed = [o for o in affirmed if o not in negated]
    if len({o["id"] for o in affirmed}) == 1:
        o = affirmed[0]
        return {"option_id": o["id"], "value": o["value"], "summary": f"Use {o['label']} ({o['description']})."}
    if re.search(r"\b(revised|later|latest|new|newer|updated|increased)\b", low) and not NEGATION.search(low) and len(revised) == 1:
        return {"option_id": revised[0]["id"], "value": revised[0]["value"], "summary": f"Use {revised[0]['label']} (the revised figure)."}
    remaining = [o for o in num_opts if o not in negated]
    if negated and len(remaining) == 1:
        o = remaining[0]
        return {"option_id": o["id"], "value": o["value"], "summary": f"Use {o['label']}; the other figure was not approved."}
    return None


def interpret_answer(q: dict, text: Optional[str], option_id: Optional[str], skip: bool, ai_interpreter=None) -> dict:
    """Return {status, value, option_id, interpretation}."""
    if skip or (text is not None and SKIP_PATTERNS.match(text) and not option_id):
        return {"status": "skipped", "value": None, "option_id": None,
                "interpretation": "Skipped. Kept as an unresolved assumption."}
    if option_id:
        opt = next((o for o in q.get("options", []) if o["id"] == option_id), None)
        if opt is None:
            raise ValueError("Unknown option.")
        if opt["value"] is None:  # e.g. "A different amount": needs the typed value
            amount = parse_amount(text or "")
            if amount is None:
                raise ValueError("Please type the amount.")
            return {"status": "answered", "value": amount, "option_id": "other",
                    "interpretation": f"Use {amount:,.0f}, supplied in your answer."}
        return {"status": "answered", "value": opt["value"], "option_id": opt["id"],
                "interpretation": f"Selected: {opt['label']}" + (f" ({opt['description']})" if opt.get("description") else "") + "."}
    if not text or not text.strip():
        raise ValueError("Please choose an option, type an answer, or skip.")
    det = interpret_deterministic(q, text)
    if det:
        return {"status": "answered", "value": det["value"], "option_id": det.get("option_id"),
                "interpretation": det["summary"]}
    if q["key"].startswith("agent:"):
        return {"status": "answered", "value": text.strip(), "option_id": None,
                "interpretation": "Recorded as context for the analysts."}
    if ai_interpreter is not None:
        try:
            r = ai_interpreter(q, text)
            if r and r.understood:
                value = None
                if r.option_id:
                    opt = next((o for o in q.get("options", []) if o["id"] == r.option_id), None)
                    value = opt["value"] if opt else None
                if value is None and r.numeric_value is not None:
                    value = r.numeric_value
                if value is not None:
                    return {"status": "answered", "value": value, "option_id": r.option_id,
                            "interpretation": r.summary + " (interpreted by AI)"}
        except Exception:
            pass
    return {"status": "answered", "value": None, "option_id": None,
            "interpretation": "Sentinel could not match this answer to a figure, so the item stays an unresolved assumption."}


def resolution_from_answer(q: dict, result: dict) -> dict:
    """Translate an interpreted answer into resolutions entries."""
    if result["status"] != "answered" or result["value"] is None:
        return {}
    key = q["key"]
    if key.startswith("budget:"):
        return {key: {"value": float(result["value"]),
                      "fact_id": result["option_id"] if result["option_id"] not in (None, "other") else None,
                      "source": "user" if result["option_id"] in (None, "other") else "document",
                      "note": result["interpretation"]}}
    if key.startswith("etc:"):
        return {key: {"value": float(result["value"])}}
    if key.startswith("conflict:"):
        return {key: {"fact_id": result["option_id"], "value": result["value"],
                      "fact_ids": q.get("related_fact_ids", [])}}
    if key in ("linkage", "currency"):
        return {key: result["value"]}
    if key == "horizon":
        return {"horizon": int(result["value"])}
    return {}


def apply_resolutions(ex: ExtractionResult, resolutions: dict) -> None:
    """Apply user decisions to the extraction (in place)."""
    if resolutions.get("currency"):
        ex.currency = resolutions["currency"]
        for f in ex.facts:
            if f.unit == "currency":
                f.currency = ex.currency
    for key, res in resolutions.items():
        if key.startswith("conflict:") and isinstance(res, dict):
            chosen = res.get("fact_id")
            ids = res.get("fact_ids", [])
            if chosen in (None, "other") and res.get("value") is not None and ids:
                keeper = ex.fact_by_id(ids[0])
                if keeper:
                    keeper.attributes["original_value"] = keeper.value
                    keeper.value = float(res["value"])
                    keeper.attributes["corrected_by_user"] = True
                    chosen = keeper.id
            for fid in ids:
                f = ex.fact_by_id(fid)
                if f and chosen and fid != chosen:
                    f.superseded = True
                    f.attributes["superseded_by_user"] = True
            cid = key.split(":", 1)[1]
            for c in ex.conflicts:
                if c.id == cid:
                    c.resolved_fact_id = chosen
        if key.startswith("budget:") and isinstance(res, dict):
            project = key.split(":", 1)[1]
            for c in ex.conflicts:
                if c.entity == project and c.metric == "budget":
                    c.resolved_fact_id = res.get("fact_id") or "user"
            if res.get("fact_id"):
                f = ex.fact_by_id(res["fact_id"])
                if f:
                    f.attributes["confirmed_by_user"] = True
