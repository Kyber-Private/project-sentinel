"""Investigation lifecycle: create, upload, analyze, answer, scenarios, delete."""
from __future__ import annotations

import hashlib
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from agents import orchestrator
from agents.llm_client import AgentError, call_structured
from agents.prompts import ANSWER_INTERPRETER
from agents.schemas import AnswerInterpretation
from config import SAMPLE_DIR, settings
from database.models import Investigation, Question, Scenario, UploadedFile
from database.repository import session_scope
from documents.security import FileValidationError, validate_file
from domain import ExtractionResult
from finance.formatting import money
from finance.scenarios import run_scenario
from finance.types import CompanyForecast, ProjectForecast, ScenarioInput
from services.clarification_service import (
    apply_resolutions,
    default_horizon,
    interpret_answer,
    resolution_from_answer,
)

executor = ThreadPoolExecutor(max_workers=4)
RUNNING = {"extracting", "analyzing"}


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _inv_dir(inv_id: str) -> Path:
    return settings.uploads_dir / inv_id


def create_investigation(name: Optional[str] = None, is_sample: bool = False) -> str:
    inv_id = str(uuid.uuid4())
    with session_scope() as s:
        s.add(Investigation(id=inv_id, name=name or "Untitled investigation", is_sample=is_sample,
                            resolutions={}, progress=orchestrator.init_progress()))
    _inv_dir(inv_id).mkdir(parents=True, exist_ok=True)
    return inv_id


def list_investigations() -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(Investigation).order_by(Investigation.updated_at.desc())).all()
        return [
            {"id": r.id, "name": r.name, "status": r.status, "is_sample": r.is_sample,
             "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat(),
             "files": len(r.files),
             "headline": (r.results or {}).get("outlook", {}).get("overall", {}).get("label")}
            for r in rows
        ]


def add_file(inv_id: str, filename: str, data: bytes) -> dict:
    with session_scope() as s:
        inv = s.get(Investigation, inv_id)
        if inv is None:
            raise ServiceError("Investigation not found.", 404)
        if inv.status in RUNNING:
            raise ServiceError("Analysis is running. Wait for it to finish before adding files.", 409)
        if len(inv.files) >= settings.max_files_per_investigation:
            raise ServiceError(f"At most {settings.max_files_per_investigation} files per investigation.")
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            raise ServiceError(f"'{filename}' is larger than {settings.max_upload_mb} MB.")
        if not data:
            raise ServiceError(f"'{filename}' is empty.")
        safe_name = Path(filename).name[:200] or "upload"
        file_id = str(uuid.uuid4())
        ext = Path(safe_name).suffix.lower()
        dest = _inv_dir(inv_id) / f"{file_id}{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        try:
            ftype = validate_file(dest, safe_name)
        except FileValidationError as exc:
            dest.unlink(missing_ok=True)
            raise ServiceError(str(exc))
        digest = hashlib.sha256(data).hexdigest()
        if any(f.sha256 == digest for f in inv.files):
            dest.unlink(missing_ok=True)
            raise ServiceError(f"'{safe_name}' has already been uploaded to this investigation.")
        rec = UploadedFile(id=file_id, investigation_id=inv_id, original_name=safe_name, stored_path=str(dest),
                           file_type=ftype, size_bytes=len(data), sha256=digest, status="uploaded")
        s.add(rec)
        if inv.status in ("complete", "awaiting_answers", "error"):
            inv.status = "draft"
        return {"id": file_id, "name": safe_name, "type": ftype, "size": len(data), "status": "uploaded"}


def remove_file(inv_id: str, file_id: str) -> None:
    with session_scope() as s:
        f = s.get(UploadedFile, file_id)
        if f is None or f.investigation_id != inv_id:
            raise ServiceError("File not found.", 404)
        if f.investigation.status in RUNNING:
            raise ServiceError("Analysis is running.", 409)
        Path(f.stored_path).unlink(missing_ok=True)
        f.investigation.status = "draft"
        s.delete(f)


def delete_investigation(inv_id: str) -> None:
    with session_scope() as s:
        inv = s.get(Investigation, inv_id)
        if inv is None:
            raise ServiceError("Investigation not found.", 404)
        s.delete(inv)
    shutil.rmtree(_inv_dir(inv_id), ignore_errors=True)


def create_sample() -> str:
    if not SAMPLE_DIR.exists() or not any(SAMPLE_DIR.iterdir()):
        from sample_data.generate_samples import main as generate

        generate()
    inv_id = create_investigation("Nova Industries (fictional sample)", is_sample=True)
    for path in sorted(SAMPLE_DIR.iterdir()):
        if path.is_file():
            add_file(inv_id, path.name, path.read_bytes())
    return inv_id


def start_analysis(inv_id: str, background: bool = True) -> None:
    with session_scope() as s:
        inv = s.get(Investigation, inv_id)
        if inv is None:
            raise ServiceError("Investigation not found.", 404)
        if not inv.files:
            raise ServiceError("Upload at least one document first.")
        if inv.status in RUNNING:
            raise ServiceError("Analysis is already running.", 409)
        inv.status = "extracting"
    if background:
        executor.submit(orchestrator.run_extraction, inv_id)
    else:
        orchestrator.run_extraction(inv_id)


def continue_analysis(inv_id: str, background: bool = True) -> None:
    with session_scope() as s:
        inv = s.get(Investigation, inv_id)
        if inv is None:
            raise ServiceError("Investigation not found.", 404)
        if inv.status in RUNNING:
            raise ServiceError("Analysis is already running.", 409)
        if inv.extraction is None:
            raise ServiceError("Analyze the documents first.")
        open_q = [q for q in inv.questions if q.status == "open"]
        if open_q:
            raise ServiceError(f"{len(open_q)} question(s) still need an answer or a skip.")
        inv.status = "analyzing"
    if background:
        executor.submit(orchestrator.run_analysis, inv_id)
    else:
        orchestrator.run_analysis(inv_id)


def set_horizon(inv_id: str, months: int, background: bool = True) -> None:
    if months not in (3, 6, 12):
        raise ServiceError("Horizon must be 3, 6, or 12 months.")
    with session_scope() as s:
        inv = s.get(Investigation, inv_id)
        if inv is None:
            raise ServiceError("Investigation not found.", 404)
        inv.horizon_months = months
    continue_analysis(inv_id, background)


def reopen_question(inv_id: str, qid: str) -> None:
    with session_scope() as s:
        q = s.get(Question, qid)
        if q is None or q.investigation_id != inv_id:
            raise ServiceError("Question not found.", 404)
        inv = q.investigation
        if inv.status in RUNNING:
            raise ServiceError("Analysis is running.", 409)
        res = dict(inv.resolutions or {})
        for k in list(res):
            if k == q.key or (q.key == "horizon" and k == "horizon"):
                res.pop(k)
        inv.resolutions = res
        q.status, q.answer_text, q.answer_value, q.interpretation = "open", None, None, None
        q.changed_analysis, q.change_summary, q.answered_at = None, None, None
        inv.status = "awaiting_answers"


def _ai_interpreter(q: dict, text: str):
    if not settings.ai_enabled:
        return None
    payload = (
        "<context_data>\n" + str({"question": q["text"], "options": [{"id": o["id"], "label": o["label"]} for o in q["options"]]})
        + "\n</context_data>\n<user_answers>\n" + text[:1000] + "\n</user_answers>"
    )
    try:
        result, _ = call_structured("answer_interpreter", ANSWER_INTERPRETER, payload, AnswerInterpretation, 2000)
        return result
    except AgentError:
        return None


def _snapshot(ex: ExtractionResult, resolutions: dict, horizon: int) -> dict:
    projects, cf, _, _ = orchestrator.compute_core(ex, resolutions, horizon)
    snap = {}
    for p in projects:
        snap[f"{p.project} final cost"] = (round(p.eac or 0), p.outlook, round(p.variance or 0))
    for m in cf.metrics:
        snap[m.label] = (m.direction, round(m.change_pct or 0, 1), round(m.end_value or 0))
    return snap


def answer_question(inv_id: str, qid: str, text: Optional[str], option_id: Optional[str], skip: bool) -> dict:
    with session_scope() as s:
        q = s.get(Question, qid)
        if q is None or q.investigation_id != inv_id:
            raise ServiceError("Question not found.", 404)
        inv = q.investigation
        if inv.status in RUNNING:
            raise ServiceError("Analysis is running.", 409)
        qd = {"key": q.key, "text": q.text, "options": q.options or [], "input_type": q.input_type,
              "related_fact_ids": q.related_fact_ids or []}
        try:
            result = interpret_answer(qd, text, option_id, skip, _ai_interpreter)
        except ValueError as exc:
            raise ServiceError(str(exc))
        old_res = dict(inv.resolutions or {})
        new_res = dict(old_res)
        new_res.update(resolution_from_answer(qd, result))
        changed, summary = None, None
        if inv.extraction and new_res != old_res:
            base = ExtractionResult.model_validate(inv.extraction)
            ex_old = base.model_copy(deep=True)
            ex_new = base.model_copy(deep=True)
            apply_resolutions(ex_old, old_res)
            apply_resolutions(ex_new, new_res)
            horizon = inv.horizon_months or old_res.get("horizon") or default_horizon(base)
            before = _snapshot(ex_old, old_res, horizon)
            after = _snapshot(ex_new, new_res, new_res.get("horizon") or horizon)
            diffs = [k for k in after if before.get(k) != after.get(k)]
            changed = bool(diffs)
            summary = ("Changes: " + ", ".join(diffs[:4]) + ".") if diffs else "No change to the forecasts."
        elif q.key.startswith("agent:") and result["status"] == "answered":
            summary = "Passed to the analysts as context."
        q.status = result["status"]
        q.answer_text = text if text else (next((o["label"] for o in q.options if o["id"] == option_id), None) if option_id else None)
        if skip:
            q.answer_text = "Skipped"
        q.answer_value = {"value": result["value"], "option_id": result["option_id"]}
        q.interpretation = result["interpretation"]
        q.changed_analysis = changed
        q.change_summary = summary
        q.answered_at = datetime.now(timezone.utc)
        inv.resolutions = new_res
        if "horizon" in new_res and new_res.get("horizon") != old_res.get("horizon"):
            inv.horizon_months = None  # the answer sets the horizon
        return {"id": q.id, "status": q.status, "interpretation": q.interpretation,
                "changed_analysis": q.changed_analysis, "change_summary": q.change_summary}


def scenario(inv_id: str, inp: ScenarioInput) -> dict:
    with session_scope() as s:
        inv = s.get(Investigation, inv_id)
        if inv is None or not inv.results:
            raise ServiceError("Run the analysis first.", 400)
        cf = CompanyForecast.model_validate(inv.results["company_forecast"])
        projects = [ProjectForecast.model_validate(p) for p in inv.results["projects"]]
        currency = (inv.extraction or {}).get("currency") or "USD"
        result = run_scenario(inp, cf, projects, currency)
        rec = Scenario(id=str(uuid.uuid4()), investigation_id=inv_id, input=inp.model_dump(), result=result.model_dump())
        s.add(rec)
        out = result.model_dump()
        out["id"] = rec.id
        out["currency"] = currency
        return out


def serialize(inv_id: str) -> dict:
    with session_scope() as s:
        inv = s.get(Investigation, inv_id)
        if inv is None:
            raise ServiceError("Investigation not found.", 404)
        ex = inv.extraction or {}
        return {
            "id": inv.id, "name": inv.name, "status": inv.status, "stage_message": inv.stage_message,
            "error": inv.error, "is_sample": inv.is_sample, "created_at": inv.created_at.isoformat(),
            "updated_at": inv.updated_at.isoformat(), "horizon_months": inv.horizon_months,
            "ai_enabled": settings.ai_enabled, "model": settings.openai_model,
            "files": [
                {"id": f.id, "name": f.original_name, "type": f.file_type, "size": f.size_bytes, "status": f.status,
                 "message": f.message, "pages": f.page_count}
                for f in inv.files
            ],
            "questions": [orchestrator._q_dict(q) for q in inv.questions],
            "progress": inv.progress or [],
            "extraction_summary": {
                "company_name": ex.get("company_name"), "currency": ex.get("currency"),
                "as_of": ex.get("as_of_period"), "projects": ex.get("projects", []),
                "facts": len([f for f in ex.get("facts", []) if not f.get("superseded")]),
                "conflicts": len(ex.get("conflicts", [])), "duplicates": len(ex.get("duplicates", [])),
            } if ex else None,
            "outlook": (inv.results or {}).get("outlook"),
            "scenarios": [{"id": sc.id, **sc.result} for sc in inv.scenarios][-5:],
        }


def facts(inv_id: str, ids: list[str]) -> list[dict]:
    from database.repository import get_facts

    with session_scope() as s:
        rows = get_facts(s, inv_id, ids or None)
        return [r.data for r in rows][:500]


def file_path(inv_id: str, file_id: str) -> tuple[Path, str, str]:
    with session_scope() as s:
        f = s.get(UploadedFile, file_id)
        if f is None or f.investigation_id != inv_id:
            raise ServiceError("File not found.", 404)
        return Path(f.stored_path), f.original_name, f.file_type
