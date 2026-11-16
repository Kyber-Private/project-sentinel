"""Investigation orchestration.

Stage order:
 1. Read documents (deterministic parsing).
 2. Data Analyst agent adds verified facts and suggests questions.
 3. Reconcile: duplicates, conflicts, data quality.
 4. Clarification questions (pause for the user if needed).
 5. Forecast engine: project and company calculations (Python, no AI).
 6. Emily (company) and Sebas (projects) run in parallel and interpret the numbers.
 7. Alex reviews everything independently.
 8. The outlook is composed.

The forecast engine runs before Emily and Sebas so the analysts explain real
calculations instead of producing their own numbers. Agent results are cached
by a hash of their input, so after a clarification answer only the agents
whose inputs changed are called again.
"""
from __future__ import annotations

import copy
import logging
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy import select

from agents import alex_reviewer, emily_company, sebas_projects
from agents.claim_checker import check_claims, collect_known_numbers
from agents.context import company_context, forecast_summary, project_context, project_summary
from agents.data_analyst import run_data_analyst
from agents.llm_client import AgentError, stable_hash
from agents.schemas import CompanyAnalysis, DataAnalystOutput, ProjectAnalysisSet, ReviewOutput
from config import settings
from database.models import AgentRun, Investigation, Question
from database.repository import replace_facts, session_scope
from documents.document_normalizer import extract_facts
from documents.pipeline import parse_file
from documents.reconciliation import reconcile
from domain import DataQualityIssue, ExtractionResult, ParsedDocument
from finance.company_forecast import build_company_forecast
from finance.drivers import company_drivers, project_drivers
from finance.project_forecast import build_project_forecasts
from services.clarification_service import apply_resolutions, default_horizon, generate_questions
from services.prediction_service import compose_outlook

log = logging.getLogger("sentinel.orchestrator")

STEPS = [
    ("read", "Reading documents"),
    ("data_analyst", "Data Analyst: extracting facts"),
    ("quality", "Checking data quality and conflicts"),
    ("clarify", "Clarification questions"),
    ("forecast", "Forecast engine: calculating forecasts"),
    ("emily", "Emily: company analysis"),
    ("sebas", "Sebas: project analysis"),
    ("alex", "Alex: independent review"),
    ("outlook", "Preparing your outlook"),
]
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def lock_for(inv_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(inv_id, threading.Lock())


def now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ progress
def init_progress(keep_done_until: Optional[str] = None, previous: Optional[list] = None) -> list[dict]:
    steps = [{"key": k, "label": label, "status": "pending", "detail": None} for k, label in STEPS]
    if keep_done_until and previous:
        prev = {s["key"]: s for s in previous}
        for s in steps:
            if s["key"] == keep_done_until:
                break
            if s["key"] in prev:
                s.update({"status": prev[s["key"]]["status"], "detail": prev[s["key"]]["detail"]})
    return steps


def set_step(inv_id: str, key: str, status: str, detail: Optional[str] = None, message: Optional[str] = None) -> None:
    with session_scope() as s:
        inv = s.get(Investigation, inv_id)
        if inv is None:
            return
        progress = copy.deepcopy(inv.progress or init_progress())
        for step in progress:
            if step["key"] == key:
                step["status"] = status
                step["detail"] = detail
        inv.progress = progress
        if message:
            inv.stage_message = message


def record_run(inv_id: str, agent: str, status: str, input_hash: Optional[str] = None, output: Any = None,
               error: Optional[str] = None, meta=None) -> None:
    with session_scope() as s:
        s.add(AgentRun(
            id=str(uuid.uuid4()), investigation_id=inv_id, agent=agent, status=status,
            model=(meta.model if meta else (settings.openai_model if status in ("success", "cached") else None)),
            input_hash=input_hash, output=output, error=error,
            tokens_in=meta.tokens_in if meta else None, tokens_out=meta.tokens_out if meta else None,
            duration_ms=meta.duration_ms if meta else None, started_at=now(), finished_at=now(),
        ))


def last_success(inv_id: str, agent: str) -> Optional[AgentRun]:
    with session_scope() as s:
        return s.scalars(
            select(AgentRun)
            .where(AgentRun.investigation_id == inv_id, AgentRun.agent == agent, AgentRun.status.in_(["success", "cached"]))
            .order_by(AgentRun.started_at.desc())
        ).first()


# ---------------------------------------------------------------- extraction
def parse_documents(inv_id: str) -> tuple[list[ParsedDocument], list[tuple[str, Path]], dict]:
    docs, visual, visual_ids = [], [], {}
    with session_scope() as s:
        inv = s.get(Investigation, inv_id)
        for f in inv.files:
            doc = parse_file(Path(f.stored_path), f.id, f.original_name, f.file_type)
            f.page_count = doc.page_count
            if any(w.startswith("Could not read") or w.startswith("Unsupported") for w in doc.warnings) or (
                doc.file_type == "doc" and not doc.blocks
            ):
                f.status, f.message = "error", "; ".join(doc.warnings)
            else:
                f.status = "parsed"
                f.message = "; ".join(doc.warnings) or None
            if doc.needs_visual_extraction:
                visual.append((f.original_name, Path(f.stored_path)))
                visual_ids[f.original_name] = (f.id, f.original_name)
            docs.append(doc)
    return docs, visual, visual_ids


def build_extraction(inv_id: str, resolutions: dict, progress: bool = True) -> tuple[ExtractionResult, Optional[DataAnalystOutput], int]:
    """Parse, run (or reuse) the Data Analyst, reconcile, and apply user decisions."""
    if progress:
        set_step(inv_id, "read", "running", message="Reading documents")
    docs, visual, visual_ids = parse_documents(inv_id)
    facts, issues, meta = extract_facts(docs)
    det = reconcile(copy.deepcopy(facts), list(issues), meta)
    if progress:
        set_step(inv_id, "read", "done", f"{len(docs)} file(s), {len([f for f in det.facts if not f.superseded])} records")

    analyst: Optional[DataAnalystOutput] = None
    rejected_count = 0
    agent_facts = []
    agent_issues: list[DataQualityIssue] = []
    if settings.ai_enabled:
        if progress:
            set_step(inv_id, "data_analyst", "running", message="Data Analyst is reading the documents")
        prev = last_success(inv_id, "data_analyst")
        try:
            r = run_data_analyst(docs, det, visual, visual_ids,
                                 cached={"input_hash": prev.input_hash, "output": prev.output} if prev else None)
            analyst = r["output"]
            agent_facts = r["facts"]
            rejected_count = len(r["rejected"])
            agent_issues = [DataQualityIssue(severity="info", message=f"Data Analyst: {m}") for m in analyst.data_quality_issues]
            record_run(inv_id, "data_analyst", "cached" if r["from_cache"] else "success", r["input_hash"],
                       {"raw": analyst.model_dump(), "accepted_facts": len(agent_facts), "rejected": r["rejected"],
                        "chunks_sent": r["chunks_sent"]}, meta=r["meta"])
            if progress:
                set_step(inv_id, "data_analyst", "done",
                         f"{len(agent_facts)} verified fact(s) added" + (f", {rejected_count} discarded" if rejected_count else "")
                         + (" (reused)" if r["from_cache"] else ""))
        except AgentError as exc:
            record_run(inv_id, "data_analyst", "failed", error=str(exc))
            if progress:
                set_step(inv_id, "data_analyst", "failed", str(exc)[:200])
            agent_issues.append(DataQualityIssue(severity="warning", message=f"Data Analyst agent failed: {exc}"))
    else:
        if progress:
            set_step(inv_id, "data_analyst", "skipped", "OpenAI API key not configured")
            record_run(inv_id, "data_analyst", "skipped", error="OPENAI_API_KEY is not set.")

    if progress:
        set_step(inv_id, "quality", "running", message="Checking data quality")
    combined = copy.deepcopy(facts) + agent_facts
    ex = reconcile(combined, list(issues) + agent_issues, meta)
    apply_resolutions(ex, resolutions)
    if progress:
        set_step(inv_id, "quality", "done",
                 f"{len(ex.conflicts)} conflict(s), {len(ex.duplicates)} duplicate group(s), "
                 f"{len([i for i in ex.issues if i.severity != 'info'])} warning(s)")
    return ex, analyst, rejected_count


def run_extraction(inv_id: str) -> None:
    """Stage 1 to 4. Ends waiting for answers or continues straight to analysis."""
    lock = lock_for(inv_id)
    with lock:
        try:
            with session_scope() as s:
                inv = s.get(Investigation, inv_id)
                inv.status, inv.error = "extracting", None
                inv.progress = init_progress()
                inv.results = None
                resolutions = dict(inv.resolutions or {})
            ex, analyst, _ = build_extraction(inv_id, resolutions)
            set_step(inv_id, "clarify", "running", message="Deciding what to ask")
            has_series = any(f.entity_type == "company" and f.period and f.metric != "expense_category"
                             for f in ex.active_facts())
            with session_scope() as s:
                inv = s.get(Investigation, inv_id)
                answered = {q.key for q in inv.questions if q.status in ("answered", "skipped")}
                for q in list(inv.questions):
                    if q.status == "open":
                        s.delete(q)
                s.flush()
                asked, assumptions = generate_questions(ex, analyst, answered, has_series)
                start = len([q for q in inv.questions if q.status != "open"])
                for i, spec in enumerate(asked):
                    s.add(Question(id=str(uuid.uuid4()), investigation_id=inv_id, position=start + i, **spec))
                data = ex.model_dump()
                data["clarification_assumptions"] = assumptions
                inv.extraction = data
                replace_facts(s, inv_id, ex.facts)
                if asked:
                    inv.status = "awaiting_answers"
                    inv.stage_message = f"{len(asked)} question(s) need your input"
            if asked:
                set_step(inv_id, "clarify", "waiting", f"{len(asked)} question(s) for you")
                return
            set_step(inv_id, "clarify", "done", "No questions needed")
        except Exception as exc:  # never leave the investigation stuck
            log.exception("extraction failed")
            _fail(inv_id, exc)
            return
    run_analysis(inv_id)


def _fail(inv_id: str, exc: Exception) -> None:
    with session_scope() as s:
        inv = s.get(Investigation, inv_id)
        if inv:
            inv.status = "error"
            inv.error = f"{type(exc).__name__}: {exc}"
            inv.stage_message = "Something went wrong. You can try again."
            log.error(traceback.format_exc())


# ----------------------------------------------------------------- analysis
def _answers(inv: Investigation) -> list[dict]:
    return [
        {"question": q.text, "status": q.status, "answer": q.answer_text, "interpretation": q.interpretation}
        for q in inv.questions if q.status in ("answered", "skipped")
    ]


def _cached_agent(inv_id: str, agent: str, input_hash: str):
    prev = last_success(inv_id, agent)
    if prev and prev.input_hash == input_hash and prev.output:
        return prev.output
    return None


def _run_agent(inv_id: str, agent: str, fn: Callable, context: dict, schema) -> tuple[Optional[Any], str]:
    h = stable_hash({"model": settings.openai_model, "context": context})
    cached = _cached_agent(inv_id, agent, h)
    if cached is not None:
        record_run(inv_id, agent, "cached", h, cached)
        return schema.model_validate(cached), "cached"
    try:
        result, meta = fn(context)
        record_run(inv_id, agent, "success", h, result.model_dump(), meta=meta)
        return result, "success"
    except AgentError as exc:
        record_run(inv_id, agent, "failed", h, error=str(exc))
        return None, f"failed: {exc}"


def run_analysis(inv_id: str) -> None:
    lock = lock_for(inv_id)
    with lock:
        try:
            _run_analysis(inv_id)
        except Exception as exc:
            log.exception("analysis failed")
            set_step(inv_id, "outlook", "failed", str(exc)[:200])
            _fail(inv_id, exc)


def compute_core(ex: ExtractionResult, resolutions: dict, horizon: int):
    projects = build_project_forecasts(ex, resolutions)
    cf = build_company_forecast(ex, horizon, resolutions.get("linkage"), projects)
    return projects, cf, company_drivers(ex, cf), project_drivers(projects)


def _run_analysis(inv_id: str) -> None:
    with session_scope() as s:
        inv = s.get(Investigation, inv_id)
        inv.status, inv.error = "analyzing", None
        inv.progress = init_progress("forecast", inv.progress)
        resolutions = dict(inv.resolutions or {})
        answers = _answers(inv)
        questions = [_q_dict(q) for q in inv.questions]
        files = [{"id": f.id, "name": f.original_name, "type": f.file_type, "pages": f.page_count, "status": f.status}
                 for f in inv.files]
        horizon_override = inv.horizon_months
        pre_assumptions = (inv.extraction or {}).get("clarification_assumptions", [])
    ex, _, rejected = build_extraction(inv_id, resolutions, progress=False)
    if _step_status(inv_id, "clarify") in ("waiting", "pending", "running"):
        set_step(inv_id, "clarify", "done", "Answers received")

    set_step(inv_id, "forecast", "running", message="Calculating forecasts")
    horizon = horizon_override or resolutions.get("horizon") or default_horizon(ex)
    projects, cf, cdrv, pdrv = compute_core(ex, resolutions, horizon)
    n_fc = len([m for m in cf.metrics if m.forecast])
    set_step(inv_id, "forecast", "done", f"{n_fc} company metric(s), {len(projects)} project(s), {horizon}-month horizon")

    agents: dict[str, Any] = {"_status": {"ai_enabled": settings.ai_enabled, "failed": [], "errors": {}}, "_rejected_facts": rejected}
    emily = sebas = review = None
    claims: list[dict] = []
    if settings.ai_enabled:
        e_ctx = company_context(ex, cf, cdrv, answers) if cf.metrics else None
        s_ctx = project_context(ex, projects, pdrv, answers) if projects else None
        set_step(inv_id, "emily", "running" if e_ctx else "skipped", None if e_ctx else "No company data")
        set_step(inv_id, "sebas", "running" if s_ctx else "skipped", None if s_ctx else "No project data",
                 message="Emily and Sebas are analyzing")
        with ThreadPoolExecutor(max_workers=2) as pool:
            fe = pool.submit(_run_agent, inv_id, "emily", emily_company.run_emily, e_ctx, CompanyAnalysis) if e_ctx else None
            fs = pool.submit(_run_agent, inv_id, "sebas", sebas_projects.run_sebas, s_ctx, ProjectAnalysisSet) if s_ctx else None
            if fe:
                emily, st = fe.result()
                set_step(inv_id, "emily", "done" if emily else "failed", st)
                if not emily:
                    agents["_status"]["failed"].append("Emily")
                    agents["_status"]["errors"]["Emily"] = st
            if fs:
                sebas, st = fs.result()
                set_step(inv_id, "sebas", "done" if sebas else "failed", st)
                if not sebas:
                    agents["_status"]["failed"].append("Sebas")
                    agents["_status"]["errors"]["Sebas"] = st
        known_ids = {f.id for f in ex.facts} | {m.id for m in cf.metrics} | {p.id for p in projects} | {d.id for d in cdrv + pdrv}
        claims = check_claims(emily, sebas, known_ids, collect_known_numbers(ex, cf, projects, cdrv + pdrv))
        set_step(inv_id, "alex", "running", message="Alex is reviewing the analysis")
        a_ctx = {
            "company": ex.company_name, "currency": ex.currency, "latest_period": ex.as_of_period,
            "forecasts": [forecast_summary(m) for m in cf.metrics],
            "projects": [project_summary(p) for p in projects],
            "drivers": [d.model_dump() for d in cdrv + pdrv],
            "emily": emily.model_dump() if emily else "Emily did not produce a result.",
            "sebas": sebas.model_dump() if sebas else ("Sebas did not produce a result." if projects else "No projects."),
            "automated_claim_checks": claims,
            "conflicts": [c.model_dump() for c in ex.conflicts],
            "data_quality_issues": [i.message for i in ex.issues][:20],
            "user_answers": answers,
            "skipped_questions": [q["text"] for q in questions if q["status"] == "skipped"],
        }
        review, st = _run_agent(inv_id, "alex", alex_reviewer.run_alex, a_ctx, ReviewOutput)
        set_step(inv_id, "alex", "done" if review else "failed", st)
        if not review:
            agents["_status"]["failed"].append("Alex")
            agents["_status"]["errors"]["Alex"] = st
    else:
        for key in ("emily", "sebas", "alex"):
            set_step(inv_id, key, "skipped", "OpenAI API key not configured")
            record_run(inv_id, key, "skipped", error="OPENAI_API_KEY is not set.")

    agents["emily"] = emily.model_dump() if emily else None
    agents["sebas"] = sebas.model_dump() if sebas else None
    agents["alex"] = review.model_dump() if review else None

    set_step(inv_id, "outlook", "running", message="Preparing your outlook")
    outlook = compose_outlook(ex, cf, projects, cdrv, pdrv, questions, agents, pre_assumptions, files)
    outlook["agent_review"] = build_agent_review(agents, claims, inv_id)
    with session_scope() as s:
        inv = s.get(Investigation, inv_id)
        data = ex.model_dump()
        data["clarification_assumptions"] = pre_assumptions
        inv.extraction = data
        replace_facts(s, inv_id, ex.facts)
        inv.results = {
            "outlook": outlook,
            "company_forecast": cf.model_dump(),
            "projects": [p.model_dump() for p in projects],
            "drivers": [d.model_dump() for d in cdrv + pdrv],
            "claim_checks": claims,
            "horizon_months": horizon,
        }
        inv.status = "complete"
        inv.stage_message = "Outlook ready"
    set_step(inv_id, "outlook", "done", None)


def _step_status(inv_id: str, key: str) -> Optional[str]:
    with session_scope() as s:
        inv = s.get(Investigation, inv_id)
        for step in inv.progress or []:
            if step["key"] == key:
                return step["status"]
    return None


def _q_dict(q: Question) -> dict:
    return {
        "id": q.id, "key": q.key, "text": q.text, "reason": q.reason, "importance": q.importance,
        "input_type": q.input_type, "options": q.options, "status": q.status, "answer_text": q.answer_text,
        "interpretation": q.interpretation, "changed_analysis": q.changed_analysis,
        "change_summary": q.change_summary, "related_fact_ids": q.related_fact_ids,
    }


def build_agent_review(agents: dict, claims: list[dict], inv_id: str) -> dict:
    review = agents.get("alex") or {}
    assessments = {c["claim_id"]: c for c in review.get("claim_reviews", [])}
    checks = {c["claim_id"]: c for c in claims}

    def annotate(prefix: str, findings: list[dict]) -> list[dict]:
        out = []
        for i, f in enumerate(findings, start=1):
            cid = f"{prefix}.{i}"
            out.append({**f, "claim_id": cid, "check": checks.get(cid), "review": assessments.get(cid)})
        return out

    emily = agents.get("emily")
    sebas = agents.get("sebas")
    with session_scope() as s:
        inv = s.get(Investigation, inv_id)
        runs = [
            {"agent": r.agent, "status": r.status, "model": r.model, "duration_ms": r.duration_ms,
             "tokens_in": r.tokens_in, "tokens_out": r.tokens_out, "error": r.error,
             "at": r.started_at.isoformat() if r.started_at else None}
            for r in inv.agent_runs
        ][-12:]
    return {
        "ai_enabled": agents["_status"]["ai_enabled"],
        "failed": agents["_status"]["failed"],
        "emily": {**emily, "findings": annotate("emily", emily["findings"])} if emily else None,
        "sebas": {
            **sebas,
            "projects": [{**p, "findings": annotate(f"sebas.{p['project']}", p["findings"])} for p in sebas["projects"]],
        } if sebas else None,
        "alex": review or None,
        "runs": runs,
    }
