"""Clarification engine and final output, through the API (no AI key)."""
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.clarification_service import generate_questions, interpret_answer


@pytest.fixture(scope="module")
def client():
    from main import app

    with TestClient(app) as c:
        yield c


def wait(c, iid):
    for _ in range(200):
        d = c.get(f"/api/investigations/{iid}").json()
        if d["status"] not in ("extracting", "analyzing"):
            return d
        time.sleep(0.1)
    raise AssertionError("timed out")


def start_sample(c):
    iid = c.post("/api/investigations/sample").json()["id"]
    c.post(f"/api/investigations/{iid}/analyze")
    return iid, wait(c, iid)


# ------------------------------------------------------------ question rules
def test_essential_conflict_triggers_question_first(extraction):
    asked, assumptions = generate_questions(extraction, None, set(), True)
    assert asked[0]["key"] == "budget:Project Beacon" and asked[0]["importance"] == "essential"
    assert len(asked) <= 5


def test_horizon_not_asked_when_it_does_not_change_conclusion(extraction):
    asked, assumptions = generate_questions(extraction, None, set(), True)
    assert "horizon" not in [q["key"] for q in asked]
    assert any("Forecast period set to 6 months" in a for a in assumptions)


def test_previously_answered_questions_not_regenerated(extraction):
    asked, _ = generate_questions(extraction, None, {"budget:Project Beacon"}, True)
    assert "budget:Project Beacon" not in [q["key"] for q in asked]


BUDGET_Q = {
    "key": "budget:Project Beacon", "input_type": "choice", "text": "",
    "options": [
        {"id": "F1", "label": "$300,000", "value": 300000.0, "description": "approved budget, from tracker"},
        {"id": "F2", "label": "$325,000", "value": 325000.0, "description": "approval status unclear, from report"},
        {"id": "other", "label": "A different amount", "value": None, "description": ""},
    ],
}


@pytest.mark.parametrize("text,expected", [
    ("The $325k was never formally approved, use the original", 300000.0),
    ("325,000 is correct, the board approved it", 325000.0),
    ("use the revised one", 325000.0),
    ("the original budget", 300000.0),
    ("Actually it's 340k", 340000.0),
])
def test_conversational_budget_answers(text, expected):
    r = interpret_answer(BUDGET_Q, text, None, False)
    assert r["status"] == "answered" and r["value"] == expected


@pytest.mark.parametrize("text", ["I don't know", "skip", "not sure", "idk"])
def test_skip_phrases(text):
    assert interpret_answer(BUDGET_Q, text, None, False)["status"] == "skipped"


def test_linkage_and_horizon_answers():
    link = {"key": "linkage", "input_type": "choice", "options": [], "text": ""}
    assert interpret_answer(link, "No, we capitalize it separately", None, False)["value"] == "separate"
    assert interpret_answer(link, "yes they're included", None, False)["value"] == "included"
    hz = {"key": "horizon", "input_type": "choice", "options": [], "text": ""}
    assert interpret_answer(hz, "the next year please", None, False)["value"] == 12
    assert interpret_answer(hz, "a quarter", None, False)["value"] == 3


def test_unclear_answer_becomes_assumption_not_guess():
    r = interpret_answer(BUDGET_Q, "hmm, ask finance", None, False)
    assert r["status"] == "answered" and r["value"] is None and "unresolved" in r["interpretation"]


# ------------------------------------------------------------ flow through the API
def test_user_answers_change_the_relevant_calculations(client):
    iid, d = start_sample(client)
    assert d["status"] == "awaiting_answers"
    q = next(q for q in d["questions"] if q["key"] == "budget:Project Beacon")
    r = client.post(f"/api/investigations/{iid}/questions/{q['id']}/answer", json={"text": "use the original 300k"}).json()
    assert r["result"]["changed_analysis"] is True and "Project Beacon" in r["result"]["change_summary"]
    link = next(q for q in d["questions"] if q["key"] == "linkage")
    r = client.post(f"/api/investigations/{iid}/questions/{link['id']}/answer", json={"option_id": "separate"}).json()
    assert r["result"]["changed_analysis"] is True and "Cash" in r["result"]["change_summary"]
    client.post(f"/api/investigations/{iid}/continue")
    d = wait(client, iid)
    beacon = next(p for p in d["outlook"]["projects"] if p["project"] == "Project Beacon")
    assert beacon["budget_text"] == "$300,000" and beacon["outlook"] == "At risk of exceeding budget"
    # Re-analyzing the documents does not ask answered questions again.
    client.post(f"/api/investigations/{iid}/analyze")
    d = wait(client, iid)
    assert d["status"] == "complete"
    assert [q["status"] for q in d["questions"]] == ["answered", "answered"]


def test_helpful_question_skip_does_not_block_and_stays_visible(client):
    iid, d = start_sample(client)
    for q in d["questions"]:
        client.post(f"/api/investigations/{iid}/questions/{q['id']}/answer", json={"skip": True})
    assert client.post(f"/api/investigations/{iid}/continue").status_code == 200
    d = wait(client, iid)
    o = d["outlook"]
    assert d["status"] == "complete"
    assert any(a.startswith("Unresolved (question skipped)") for a in o["assumptions"])
    beacon = next(p for p in o["projects"] if p["project"] == "Project Beacon")
    assert beacon["outlook"] == "Depends on which budget applies" and "unresolved" in beacon["budget_text"]
    assert any("Skipped question" in l for l in o["data_quality"]["limitations"])


def test_cannot_continue_with_open_questions(client):
    iid, d = start_sample(client)
    r = client.post(f"/api/investigations/{iid}/continue")
    assert r.status_code == 400 and "still need" in r.json()["detail"]


@pytest.fixture(scope="module")
def finished(client):
    iid, d = start_sample(client)
    for q in d["questions"]:
        body = {"option_id": q["options"][0]["id"]} if q["options"] else {"skip": True}
        client.post(f"/api/investigations/{iid}/questions/{q['id']}/answer", json=body)
    client.post(f"/api/investigations/{iid}/continue")
    return iid, wait(client, iid)


def test_company_and_project_results_separate(finished):
    _, d = finished
    o = d["outlook"]
    assert {l["metric"] for l in o["company"]} >= {"revenue", "operating_expenses", "operating_profit", "cash_balance"}
    assert [p["project"] for p in o["projects"]] == ["Project Alpha", "Project Beacon"]
    assert all("project" not in l["id"] for l in o["company"])


def test_forecast_periods_correct(finished):
    _, d = finished
    o = d["outlook"]
    assert o["as_of"] == "2026-10" and o["horizon_months"] == 6
    assert o["forecast_window"] == {"start": "2026-11", "end": "2027-04", "label": "Nov 2026 to Apr 2027"}
    rev = next(l for l in o["company"] if l["metric"] == "revenue")
    assert [p["period"] for p in rev["forecast"]] == ["2026-11", "2026-12", "2027-01", "2027-02", "2027-03", "2027-04"]


def test_reasons_grounded_and_sources_open_correct_records(client, finished):
    iid, d = finished
    for r in d["outlook"]["reasons"]:
        assert r["fact_ids"], r
        facts = client.get(f"/api/investigations/{iid}/facts", params={"ids": ",".join(r["fact_ids"])}).json()
        assert {f["id"] for f in facts} == set(r["fact_ids"])
        for f in facts:
            assert f["source"]["file_name"] and (f["source"].get("sheet") or f["source"].get("page") or f["source"].get("row"))
    f = client.get(f"/api/investigations/{iid}/facts", params={"ids": d["outlook"]["reasons"][0]["fact_ids"][0]}).json()[0]
    raw = client.get(f"/api/investigations/{iid}/files/{f['source']['file_id']}/download")
    assert raw.status_code == 200 and len(raw.content) > 100


def test_output_remains_concise(finished):
    _, d = finished
    o = d["outlook"]
    assert len(o["reasons"]) <= 3 and len(o["what_could_change"]) <= 6
    assert len(o["overall"]["headline"]) < 400
    assert len(o["company"]) <= 5
    assert "—" not in o["overall"]["headline"]


def test_report_pdf_downloads(client, finished):
    iid, _ = finished
    r = client.get(f"/api/investigations/{iid}/report.pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["content-type"] == "application/pdf"


def test_scenario_endpoint(client, finished):
    iid, _ = finished
    r = client.post(f"/api/investigations/{iid}/scenarios", json={"opex_change_pct": -3}).json()
    op = next(l for l in r["lines"] if l["key"] == "operating_profit")
    assert op["difference"] > 0 and op["favorable"] is True


def test_insufficient_data_clearly_communicated(client, tmp_path):
    iid = client.post("/api/investigations", json={"name": "tiny"}).json()["id"]
    csv = "Month,Revenue,Operating Expenses\nJul 2026,100000,80000\nAug 2026,105000,82000\nSep 2026,103000,85000\n"
    client.post(f"/api/investigations/{iid}/files", files=[("files", ("tiny.csv", csv.encode(), "text/csv"))])
    client.post(f"/api/investigations/{iid}/analyze")
    d = wait(client, iid)
    if d["status"] == "awaiting_answers":
        for q in d["questions"]:
            client.post(f"/api/investigations/{iid}/questions/{q['id']}/answer", json={"skip": True})
        client.post(f"/api/investigations/{iid}/continue")
        d = wait(client, iid)
    o = d["outlook"]
    rev = next(l for l in o["company"] if l["metric"] == "revenue")
    assert rev["display"] == "Insufficient data for a reliable forecast"
    assert "Not enough information to produce a reliable numerical forecast" in rev["message"]
    assert o["data_quality"]["label"] in ("Limited", "Poor")


def test_upload_validation_and_delete(client):
    iid = client.post("/api/investigations", json={}).json()["id"]
    r = client.post(f"/api/investigations/{iid}/files", files=[("files", ("evil.exe", b"MZ...", "application/octet-stream"))]).json()
    assert r["errors"] and not r["added"]
    r = client.post(f"/api/investigations/{iid}/files", files=[("files", ("a.txt", b"Revenue for October 2026 was $10,000.", "text/plain"))]).json()
    assert len(r["added"]) == 1
    stored = Path(__import__("config").settings.uploads_dir / iid)
    assert any(stored.iterdir())
    assert client.delete(f"/api/investigations/{iid}").json() == {"deleted": True}
    assert client.get(f"/api/investigations/{iid}").status_code == 404
    assert not stored.exists()
