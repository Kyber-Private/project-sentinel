"""A fake OpenAI client for agent tests. It returns schema-valid outputs built
from the real context the agents send, so tests exercise the real pipeline."""
from __future__ import annotations

import json
import re
from types import SimpleNamespace

from agents.schemas import (
    AnswerInterpretation, CompanyAnalysis, DataAnalystOutput, ProjectAnalysisSet, ReviewOutput,
)


def _text(user_input) -> str:
    if isinstance(user_input, str):
        return user_input
    parts = []
    for msg in user_input:
        for c in msg.get("content", []):
            if c.get("type") == "input_text":
                parts.append(c["text"])
    return "\n".join(parts)


def _payload(text: str, tag: str) -> dict:
    m = re.search(rf"<{tag}>\n(.*)\n</{tag}>", text, re.S)
    return json.loads(m.group(1)) if m else {}


class FakeResponses:
    def __init__(self, mode: str = "ok"):
        self.mode = mode
        self.calls: list[str] = []

    def parse(self, *, model, instructions, input, text_format, **kwargs):
        name = text_format.__name__
        self.calls.append(name)
        if self.mode == "invalid":
            return SimpleNamespace(output_parsed=None, usage=None, model=model, id="r0")
        if self.mode == "connection_error":
            import openai
            from openai._base_client import httpx2

            raise openai.APIConnectionError(request=httpx2.Request("POST", "https://api.openai.com/v1/responses"))
        text = _text(input)
        if text_format is DataAnalystOutput:
            out = self._analyst(text)
        elif text_format is CompanyAnalysis:
            out = self._emily(_payload(text, "context_data"))
        elif text_format is ProjectAnalysisSet:
            out = self._sebas(_payload(text, "context_data"))
        elif text_format is ReviewOutput:
            out = self._alex(_payload(text, "context_data"))
        elif text_format is AnswerInterpretation:
            out = AnswerInterpretation(understood=False, option_id=None, numeric_value=None, summary="unclear")
        else:
            out = text_format.model_validate({"ok": True, "message": "Connection works fine today"})
        return SimpleNamespace(output_parsed=out, usage=SimpleNamespace(input_tokens=100, output_tokens=50),
                               model=model, id="resp_test")

    # ---------------------------------------------------------------- builders
    def _analyst(self, text: str) -> DataAnalystOutput:
        data = _payload(text, "document_data")
        chunks = data.get("text_chunks", [])
        hire = next(c for c in chunks if "four more hires" in c["text"])
        quote = "plan four more hires in the first quarter of 2027"
        if quote not in hire["text"]:
            quote = re.search(r"plan four more hires[^.]*", hire["text"].replace("\n", " ")).group(0)
        return DataAnalystOutput.model_validate({
            "summary": "Monthly P&L, project tracker, supplier notice, board report.",
            "facts": [
                {"entity_type": "company", "entity": "Nova Industries", "metric": "business_note", "period": None, "value": None,
                 "text_value": "Four more engineering hires planned for Q1 2027", "currency": None, "qualifier": "plan",
                 "chunk_id": hire["chunk_id"], "quote": quote},
                {"entity_type": "project", "entity": "Project Beacon", "metric": "forecast_at_completion", "period": None,
                 "value": 999999, "text_value": None, "currency": "USD", "qualifier": None,
                 "chunk_id": hire["chunk_id"], "quote": "Project Beacon will cost $999,999"},
            ],
            "data_quality_issues": ["A text file contains an instruction aimed at AI systems; ignored."],
            "missing_information": [{"item": "Contract renewal terms", "importance": "helpful", "reason": "Affects revenue"}],
            "conflicts_noticed": ["Project Beacon budget 300,000 vs 325,000"],
            "relationships": ["Unclear whether project spending sits inside operating expenses."],
            "suggested_questions": [
                {"question": "Is the Harbor Retail distribution contract expected to continue through 2027?",
                 "reason": "Revenue growth depends on it.", "importance": "helpful", "related_fields": ["company:revenue"],
                 "options": ["Yes", "No", "Not sure"]},
                {"question": "Which budget figure for Project Beacon is the approved budget?",
                 "reason": "Conflict", "importance": "essential", "related_fields": ["project:Project Beacon:budget"], "options": []},
            ],
        })

    def _emily(self, ctx: dict) -> CompanyAnalysis:
        rev = next(f for f in ctx["forecasts"] if f["calculation_id"] == "company.revenue")
        fid = re.search(r"\[(F\d+)\]", ctx["monthly_history"]["revenue"][-1]).group(1)
        return CompanyAnalysis.model_validate({
            "summary": "Costs are growing faster than revenue.",
            "outlook": "deteriorating",
            "findings": [
                {"title": "Revenue growth", "statement": f"Revenue is forecast to grow {rev['change_pct']}% over the period.",
                 "metric": "revenue", "direction": "increase", "business_effect": "favorable", "evidence_type": "estimated",
                 "support": "supported", "cited_fact_ids": [fid], "cited_calculation_ids": ["company.revenue"]},
                {"title": "Invented claim", "statement": "Revenue grew 37% and reached $9,876,543.",
                 "metric": "revenue", "direction": "increase", "business_effect": "favorable", "evidence_type": "observed",
                 "support": "supported", "cited_fact_ids": ["F9999"], "cited_calculation_ids": []},
            ],
            "uncertainties": ["Only 12 months of data."],
            "watch_items": ["Payroll"],
        })

    def _sebas(self, ctx: dict) -> ProjectAnalysisSet:
        projects = []
        for p in ctx["projects"]:
            projects.append({
                "project": p["project"], "summary": f"{p['project']} outlook: {p['outlook']}.",
                "status": "at_risk", "risks": ["Supplier prices"], "uncertainties": [],
                "findings": [{
                    "title": "Final cost estimate",
                    "statement": f"Estimated final cost is ${p['estimate_at_completion']:,.0f}.",
                    "metric": "estimate_at_completion", "direction": "increase", "business_effect": "unfavorable",
                    "evidence_type": "calculated", "support": "supported", "cited_fact_ids": p["fact_ids"][:2],
                    "cited_calculation_ids": [p["calculation_id"]],
                }],
            })
        return ProjectAnalysisSet.model_validate({"projects": projects, "cross_project_notes": []})

    def _alex(self, ctx: dict) -> ReviewOutput:
        bad = [c["claim_id"] for c in ctx["automated_claim_checks"] if c["status"] != "verified"]
        return ReviewOutput.model_validate({
            "overall_verdict": "qualify",
            "verdict_reason": "Direction is supported, but only 12 months of history exist.",
            "recommended_confidence": "medium",
            "company_verdict": "qualify",
            "project_verdicts": [{"project": p["project"], "verdict": "trust", "reason": "Calculations check out."} for p in ctx["projects"]],
            "claim_reviews": [{"claim_id": c, "assessment": "unsupported", "comment": "Numbers not in the data."} for c in bad],
            "challenges": [{"target": "emily", "issue": "One finding cites figures that do not exist.", "severity": "high"}],
            "false_precision": [], "insufficient_data": ["Seasonality cannot be assessed."],
            "what_could_change_outlook": ["Renewal of the Harbor Retail contract."],
            "recommended_next_step": "Review payroll growth and confirm the Project Beacon budget.",
        })


class FakeChatCompletions:
    """Chat Completions flavor (used for OpenRouter). Reuses the Responses fake so outputs match."""

    def __init__(self, responses: "FakeResponses"):
        self._responses = responses
        self.last_kwargs: dict = {}

    def parse(self, *, model, messages, response_format, **kwargs):
        self.last_kwargs = dict(model=model, messages=messages, response_format=response_format, **kwargs)
        system = next(m["content"] for m in messages if m["role"] == "system")
        user = next(m["content"] for m in messages if m["role"] == "user")
        r = self._responses.parse(model=model, instructions=system, input=user, text_format=response_format)
        message = SimpleNamespace(parsed=r.output_parsed)
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=50) if r.usage else None
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage, model=model, id="chat_test")


class FakeClient:
    def __init__(self, mode: str = "ok"):
        self.responses = FakeResponses(mode)
        self.chat = SimpleNamespace(completions=FakeChatCompletions(self.responses))
