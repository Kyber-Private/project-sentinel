"""Agents and orchestration, using a fake OpenAI client (no network)."""
import time

import pytest
from fastapi.testclient import TestClient

from agents import llm_client
from agents.claim_checker import check_claims, extract_numbers
from agents.data_analyst import run_data_analyst
from agents.schemas import CompanyAnalysis
from config import settings
from documents.pipeline import extract_all
from tests.fake_openai import FakeClient


@pytest.fixture()
def fake(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_max_retries", 1)
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    llm_client.set_client_factory(lambda: client)
    yield client
    llm_client.set_client_factory(None)


def wait(c, iid):
    for _ in range(200):
        d = c.get(f"/api/investigations/{iid}").json()
        if d["status"] not in ("extracting", "analyzing"):
            return d
        time.sleep(0.1)
    raise AssertionError("timed out")


def run_sample(c):
    iid = c.post("/api/investigations/sample").json()["id"]
    c.post(f"/api/investigations/{iid}/analyze")
    d = wait(c, iid)
    for q in d["questions"]:
        if q["key"].startswith("budget:"):
            c.post(f"/api/investigations/{iid}/questions/{q['id']}/answer", json={"option_id": q["options"][0]["id"]})
        else:
            c.post(f"/api/investigations/{iid}/questions/{q['id']}/answer", json={"skip": True})
    c.post(f"/api/investigations/{iid}/continue")
    return iid, wait(c, iid)


def test_data_analyst_extracts_structured_verified_facts(fake, parsed_docs):
    det = extract_all(parsed_docs)
    r = run_data_analyst(parsed_docs, det, [], {})
    assert len(r["facts"]) == 1 and r["facts"][0].metric == "business_note"
    assert r["facts"][0].source.file_name == "Nova_Board_Report_Oct2026.pdf" and r["facts"][0].source.page == 1
    assert len(r["rejected"]) == 1 and r["rejected"][0]["reason"] == "quote not found in the cited text"


def test_claim_checker_flags_invented_numbers():
    emily = CompanyAnalysis.model_validate({
        "summary": "", "outlook": "mixed", "uncertainties": [], "watch_items": [],
        "findings": [
            {"title": "ok", "statement": "Revenue rose 4.8% to $1,284,000.", "metric": "revenue", "direction": "increase",
             "business_effect": "favorable", "evidence_type": "observed", "support": "supported",
             "cited_fact_ids": ["F1"], "cited_calculation_ids": []},
            {"title": "bad", "statement": "Revenue rose 37% to $9,876,543.", "metric": "revenue", "direction": "increase",
             "business_effect": "favorable", "evidence_type": "observed", "support": "supported",
             "cited_fact_ids": ["F404"], "cited_calculation_ids": []},
        ],
    })
    res = check_claims(emily, None, {"F1"}, [4.8, 1_284_000])
    assert res[0]["status"] == "verified"
    assert res[1]["status"] == "unverified" and res[1]["unknown_ids"] == ["F404"] and len(res[1]["unverified_numbers"]) == 2


def test_extract_numbers_ignores_years():
    assert extract_numbers("In 2026 revenue was $1.2M, up 5%") == [(1_200_000.0, "money"), (5.0, "pct")]


def test_full_orchestration_with_agents(fake):
    from main import app

    with TestClient(app) as c:
        iid, d = run_sample(c)
        assert d["status"] == "complete"
        # Data Analyst question that rules did not cover is asked; the duplicate budget one is not.
        keys = [q["key"] for q in d["questions"]]
        assert any(k.startswith("agent:") and "harbor" in k for k in keys)
        assert sum(1 for q in d["questions"] if "Beacon" in q["text"]) == 1
        o = d["outlook"]
        review = o["agent_review"]
        assert review["ai_enabled"] and review["failed"] == []
        assert o["overall"]["reviewer_verdict"] == "qualify" and o["overall"]["qualifier"]
        assert o["next_step"] == "Review payroll growth and confirm the Project Beacon budget."
        bad = next(f for f in review["emily"]["findings"] if f["title"] == "Invented claim")
        assert bad["check"]["status"] == "unverified" and bad["review"]["assessment"] == "unsupported"
        good = next(f for f in review["emily"]["findings"] if f["title"] == "Revenue growth")
        assert good["check"]["status"] == "verified"
        agents_run = {r["agent"] for r in review["runs"] if r["status"] == "success"}
        assert {"data_analyst", "emily", "sebas", "alex"} <= agents_run
        # Alex ran after Emily and Sebas.
        calls = fake.responses.calls
        assert calls.index("ReviewOutput") > calls.index("CompanyAnalysis")
        assert calls.index("ReviewOutput") > calls.index("ProjectAnalysisSet")


def test_rerun_only_calls_agents_whose_inputs_changed(fake):
    from main import app

    with TestClient(app) as c:
        iid, d = run_sample(c)
        before = list(fake.responses.calls)
        c.post(f"/api/investigations/{iid}/continue")
        wait(c, iid)
        after = fake.responses.calls[len(before):]
        assert after == []  # nothing changed, so every agent result is reused
        c.post(f"/api/investigations/{iid}/horizon", json={"months": 12})
        wait(c, iid)
        changed = fake.responses.calls[len(before):]
        assert "DataAnalystOutput" not in changed and "CompanyAnalysis" in changed and "ReviewOutput" in changed


def test_invalid_model_results_are_handled(monkeypatch):
    client = FakeClient("invalid")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_max_retries", 1)
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    llm_client.set_client_factory(lambda: client)
    try:
        from main import app

        with TestClient(app) as c:
            iid, d = run_sample(c)
            assert d["status"] == "complete"
            o = d["outlook"]
            assert set(o["agent_review"]["failed"]) == {"Emily", "Sebas", "Alex"}
            assert o["overall"]["reviewer_verdict"] == "not_reviewed"
            assert any("agents failed" in l for l in o["data_quality"]["limitations"])
    finally:
        llm_client.set_client_factory(None)


def test_api_errors_do_not_crash(monkeypatch):
    client = FakeClient("connection_error")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_max_retries", 2)
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    llm_client.set_client_factory(lambda: client)
    try:
        from main import app

        with TestClient(app) as c:
            iid, d = run_sample(c)
            assert d["status"] == "complete" and d["outlook"]["company"]
            runs = d["outlook"]["agent_review"]["runs"]
            assert all(r["status"] == "failed" for r in runs if r["agent"] in ("emily", "sebas", "alex"))
            assert len(client.responses.calls) >= 3 * 4  # three attempts per agent
            r = c.post("/api/health/openai-test").json()
            assert r["ok"] is False and "failed after 3 attempt" in r["error"]
    finally:
        llm_client.set_client_factory(None)


def test_missing_key_never_fakes_ai(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)
    llm_client.set_client_factory(None)
    from main import app

    with TestClient(app) as c:
        assert c.get("/api/health").json()["setup_message"]
        assert c.post("/api/health/openai-test").json()["ok"] is False
        iid, d = run_sample(c)
        review = d["outlook"]["agent_review"]
        assert review["ai_enabled"] is False and review["emily"] is None and review["alex"] is None
        assert all(r["status"] == "skipped" for r in review["runs"])
        assert d["outlook"]["overall"]["reviewer_verdict"] == "not_reviewed"


def test_openrouter_key_switches_to_chat_mode(monkeypatch):
    import config

    monkeypatch.setenv("OPENAI_API_KEY", "sk-or-v1-abc")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_MODE", raising=False)
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6-luna")
    s = config.Settings()
    assert s.using_openrouter and s.openai_base_url == "https://openrouter.ai/api/v1"
    assert s.openai_api_mode == "chat" and s.openai_model == "openai/gpt-6-luna"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-abc")
    s2 = config.Settings()
    assert not s2.using_openrouter and s2.openai_api_mode == "responses" and s2.openai_model == "gpt-6-luna"


def test_chat_mode_runs_the_full_pipeline(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(settings, "openai_api_key", "sk-or-v1-test")
    monkeypatch.setattr(settings, "openai_api_mode", "chat")
    monkeypatch.setattr(settings, "using_openrouter", True)
    monkeypatch.setattr(settings, "openai_model", "openai/gpt-6-luna")
    llm_client.set_client_factory(lambda: client)
    try:
        result = llm_client.test_connection()
        assert result["ok"] is True
        sent = client.chat.completions.last_kwargs
        assert sent["model"] == "openai/gpt-6-luna" and sent["extra_body"] == {"reasoning": {"effort": "medium"}}
        assert [m["role"] for m in sent["messages"]] == ["system", "user"]
        assert client.responses.calls  # shared fake recorded the call
    finally:
        llm_client.set_client_factory(None)


def test_chat_mode_falls_back_to_plain_json_when_provider_refuses_schema(monkeypatch):
    import openai
    from openai._base_client import httpx2
    from types import SimpleNamespace

    class Refusing:
        def __init__(self):
            self.parse_calls = 0
            self.create_calls = 0
            self.completions = self

        def parse(self, **kw):
            self.parse_calls += 1
            req = httpx2.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
            raise openai.NotFoundError("No endpoints found that support structured outputs", response=httpx2.Response(404, request=req), body=None)

        def create(self, **kw):
            self.create_calls += 1
            assert "response_format" not in kw and "JSON Schema" in kw["messages"][0]["content"]
            msg = SimpleNamespace(parsed=None, content="```json\n{\"ok\": true, \"message\": \"Connection works fine today\"}\n```")
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None, model=kw["model"], id="c1")

    client = SimpleNamespace(chat=Refusing())
    monkeypatch.setattr(settings, "openai_api_key", "sk-or-v1-test")
    monkeypatch.setattr(settings, "openai_api_mode", "chat")
    monkeypatch.setattr(settings, "using_openrouter", True)
    monkeypatch.setattr(settings, "openai_model", "openai/gpt-6-luna")
    monkeypatch.setattr(settings, "openai_max_retries", 0)
    llm_client.set_client_factory(lambda: client)
    try:
        assert llm_client.test_connection()["ok"] is True
        assert client.chat.parse_calls == 1 and client.chat.create_calls == 1
    finally:
        llm_client.set_client_factory(None)
