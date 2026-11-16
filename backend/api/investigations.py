"""Investigation, upload, clarification, forecast, and report endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from finance.types import ScenarioInput
from services import investigation_service as svc
from services.report_service import build_report

router = APIRouter(prefix="/api")

MEDIA = {
    "pdf": "application/pdf", "csv": "text/csv", "txt": "text/plain",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel", "doc": "application/msword",
}


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.ServiceError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


class CreateBody(BaseModel):
    name: Optional[str] = None


class AnswerBody(BaseModel):
    text: Optional[str] = None
    option_id: Optional[str] = None
    skip: bool = False


class HorizonBody(BaseModel):
    months: int


@router.get("/investigations")
def list_investigations():
    return svc.list_investigations()


@router.post("/investigations")
def create_investigation(body: CreateBody):
    inv_id = svc.create_investigation(body.name)
    return svc.serialize(inv_id)


@router.post("/investigations/sample")
def create_sample():
    inv_id = _wrap(svc.create_sample)
    return svc.serialize(inv_id)


@router.get("/investigations/{inv_id}")
def get_investigation(inv_id: str):
    return _wrap(svc.serialize, inv_id)


@router.delete("/investigations/{inv_id}")
def delete_investigation(inv_id: str):
    _wrap(svc.delete_investigation, inv_id)
    return {"deleted": True}


@router.post("/investigations/{inv_id}/files")
async def upload_files(inv_id: str, files: list[UploadFile] = File(...)):
    added, errors = [], []
    for f in files:
        data = await f.read()
        try:
            added.append(svc.add_file(inv_id, f.filename or "upload", data))
        except svc.ServiceError as exc:
            if exc.status == 404:
                raise HTTPException(404, str(exc))
            errors.append({"name": f.filename, "error": str(exc)})
    return {"added": added, "errors": errors, "investigation": svc.serialize(inv_id)}


@router.delete("/investigations/{inv_id}/files/{file_id}")
def delete_file(inv_id: str, file_id: str):
    _wrap(svc.remove_file, inv_id, file_id)
    return svc.serialize(inv_id)


@router.get("/investigations/{inv_id}/files/{file_id}/download")
def download_file(inv_id: str, file_id: str):
    path, name, ftype = _wrap(svc.file_path, inv_id, file_id)
    return FileResponse(path, media_type=MEDIA.get(ftype, "application/octet-stream"), filename=name,
                        content_disposition_type="inline" if ftype in ("pdf", "txt", "csv") else "attachment")


@router.post("/investigations/{inv_id}/analyze")
def analyze(inv_id: str):
    _wrap(svc.start_analysis, inv_id)
    return svc.serialize(inv_id)


@router.post("/investigations/{inv_id}/questions/{qid}/answer")
def answer(inv_id: str, qid: str, body: AnswerBody):
    result = _wrap(svc.answer_question, inv_id, qid, body.text, body.option_id, body.skip)
    return {"result": result, "investigation": svc.serialize(inv_id)}


@router.post("/investigations/{inv_id}/questions/{qid}/reopen")
def reopen(inv_id: str, qid: str):
    _wrap(svc.reopen_question, inv_id, qid)
    return svc.serialize(inv_id)


@router.post("/investigations/{inv_id}/continue")
def continue_analysis(inv_id: str):
    _wrap(svc.continue_analysis, inv_id)
    return svc.serialize(inv_id)


@router.post("/investigations/{inv_id}/horizon")
def horizon(inv_id: str, body: HorizonBody):
    _wrap(svc.set_horizon, inv_id, body.months)
    return svc.serialize(inv_id)


@router.get("/investigations/{inv_id}/facts")
def get_facts(inv_id: str, ids: str = Query("")):
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    return _wrap(svc.facts, inv_id, id_list)


@router.post("/investigations/{inv_id}/scenarios")
def run_scenario(inv_id: str, body: ScenarioInput):
    return _wrap(svc.scenario, inv_id, body)


@router.get("/investigations/{inv_id}/report.pdf")
def report(inv_id: str):
    data = _wrap(svc.serialize, inv_id)
    if not data.get("outlook"):
        raise HTTPException(400, "The outlook is not ready yet.")
    ids = set()
    for r in data["outlook"].get("reasons", []):
        ids.update(r.get("fact_ids", []))
    sources = {f["id"]: f for f in svc.facts(inv_id, list(ids))}
    pdf = build_report(data["outlook"], data["name"], sources)
    safe = "".join(c for c in data["name"] if c.isalnum() or c in " -_").strip().replace(" ", "_") or "outlook"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="Sentinel_Outlook_{safe}.pdf"'})
