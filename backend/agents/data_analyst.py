"""Agent 1: Data Analyst. Understands the documents and adds verified facts."""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Optional

from agents.context import deterministic_summary, select_chunks
from agents.llm_client import CallMeta, call_structured, stable_hash
from agents.prompts import DATA_ANALYST
from agents.schemas import DataAnalystOutput
from config import settings
from documents.provenance import parse_number
from domain import ExtractionResult, Fact, ParsedDocument

MAX_VISUAL_PDF_BYTES = 10 * 1024 * 1024


def build_input(documents: list[ParsedDocument], det: ExtractionResult, visual_pdfs: list[tuple[str, Path]]):
    chunks = select_chunks(documents, settings.agent_context_char_budget)
    payload = {
        "deterministic_summary": deterministic_summary(det),
        "text_chunks": [
            {"chunk_id": c["chunk_id"], "source": c["source"].label(), "text": c["text"]} for c in chunks
        ],
    }
    text = (
        "Analyze these business documents.\n<document_data>\n"
        + json.dumps(payload, ensure_ascii=False, default=str)
        + "\n</document_data>"
    )
    content = [{"type": "input_text", "text": text}]
    for name, path in visual_pdfs:
        data = path.read_bytes()
        if len(data) > MAX_VISUAL_PDF_BYTES:
            continue
        content.append({
            "type": "input_file",
            "filename": name,
            "file_data": "data:application/pdf;base64," + base64.b64encode(data).decode(),
        })
        content.append({
            "type": "input_text",
            "text": f"The PDF '{name}' has no text layer. Read it visually. Use chunk_id 'VISUAL:{name}' and quote "
                    "the text exactly as it appears.",
        })
    user_input = [{"role": "user", "content": content}]
    hash_basis = {"payload": payload, "visual": [(n, stable_hash(p.read_bytes().hex()[:2000])) for n, p in visual_pdfs]}
    return user_input, chunks, stable_hash(hash_basis)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _numbers_in(text: str) -> list[float]:
    out = []
    for m in re.finditer(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", text):
        v = parse_number(m.group(0))
        if v is None:
            continue
        tail = text[m.end(): m.end() + 10].lower()
        if re.match(r"\s?(million|m\b)", tail):
            v *= 1e6
        elif re.match(r"\s?(thousand|k\b)", tail):
            v *= 1e3
        out.append(v)
    return out


def verify_facts(output: DataAnalystOutput, chunks: list[dict], visual_files: dict[str, tuple[str, str]]) -> tuple[list[Fact], list[dict]]:
    """Keep only facts whose quote appears in the cited chunk and contains the value.

    visual_files maps file name -> (file_id, file name) for PDFs read visually;
    those facts cannot be checked against a text layer and are marked low confidence.
    """
    by_id = {c["chunk_id"]: c for c in chunks}
    accepted: list[Fact] = []
    rejected: list[dict] = []
    for af in output.facts:
        reason = None
        src = None
        confidence = "medium"
        if af.chunk_id.startswith("VISUAL:"):
            name = af.chunk_id.split(":", 1)[1]
            if name not in visual_files:
                reason = "unknown visual source"
            else:
                fid, fname = visual_files[name]
                from domain import SourceRef

                src = SourceRef(file_id=fid, file_name=fname, excerpt=af.quote[:300])
                confidence = "low"
        else:
            chunk = by_id.get(af.chunk_id)
            if chunk is None:
                reason = "cited chunk does not exist"
            elif _norm(af.quote) not in _norm(chunk["text"]):
                reason = "quote not found in the cited text"
            else:
                src = chunk["source"].model_copy(update={"excerpt": af.quote[:300]})
        if reason is None and af.value is not None:
            nums = _numbers_in(af.quote)
            ok = any(abs(n - af.value) <= max(0.5, 0.005 * abs(af.value)) for n in nums)
            if not ok:
                reason = "value does not appear in the quote"
        if reason is None and af.value is None and not af.text_value:
            reason = "no value or text"
        if reason:
            rejected.append({"fact": af.model_dump(), "reason": reason})
            continue
        period = af.period if af.period and re.match(r"^\d{4}-\d{2}$", af.period) else None
        accepted.append(Fact(
            entity_type=af.entity_type,
            entity="__company__" if af.entity_type == "company" else af.entity.strip(),
            metric=af.metric,
            period=period,
            value=af.value,
            text_value=af.text_value,
            currency=af.currency,
            unit="percent" if af.metric in ("percent_complete", "supplier_price_change_pct") else (
                "text" if af.value is None else "currency"),
            qualifier=af.qualifier,
            source=src,
            extraction_method="agent",
            confidence=confidence,
        ))
    return accepted, rejected


def run_data_analyst(documents: list[ParsedDocument], det: ExtractionResult,
                     visual_pdfs: list[tuple[str, Path]], visual_ids: dict[str, tuple[str, str]],
                     cached: Optional[dict] = None):
    user_input, chunks, input_hash = build_input(documents, det, visual_pdfs)
    meta: Optional[CallMeta] = None
    if cached and cached.get("input_hash") == input_hash and cached.get("output"):
        output = DataAnalystOutput.model_validate(cached["output"]["raw"])
        from_cache = True
    else:
        output, meta = call_structured("data_analyst", DATA_ANALYST, user_input, DataAnalystOutput)
        from_cache = False
    facts, rejected = verify_facts(output, chunks, visual_ids)
    return {
        "output": output,
        "facts": facts,
        "rejected": rejected,
        "input_hash": input_hash,
        "meta": meta,
        "from_cache": from_cache,
        "chunks_sent": len(chunks),
    }
