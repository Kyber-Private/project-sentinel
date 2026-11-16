"""Offline unit tests for Ollama batching and financial health classification."""
from agents import data_analyst
from agents.llm_client import AgentError, CallMeta
from agents.data_analyst import LocalObservations, LocalObservation
from documents.pipeline import extract_all
from finance.company_forecast import build_company_forecast
from services.prediction_service import overall_label


def test_local_document_batching_preserves_sources(parsed_docs):
    det = extract_all(parsed_docs)
    _, chunks, _ = data_analyst.build_input(parsed_docs, det, [])
    batches = data_analyst._local_batches(chunks, target_chars=2000)
    assert len(batches) >= 2
    assert [c["chunk_id"] for group in batches for c in group] == [c["chunk_id"] for c in chunks]


def test_local_batches_merge_validated_json(monkeypatch, parsed_docs):
    det = extract_all(parsed_docs)
    _, chunks, _ = data_analyst.build_input(parsed_docs, det, [])
    monkeypatch.setattr(data_analyst.settings, "using_ollama", True)
    seen = []

    def fake(agent, instructions, user_input, schema, max_output_tokens=16000):
        seen.append(user_input)
        assert schema is LocalObservations
        assert max_output_tokens <= 2000
        return LocalObservations(facts=[]), CallMeta("qwen3:8b", 20, 10, 10, None, 1)

    monkeypatch.setattr(data_analyst, "call_structured", fake)
    r = data_analyst.run_data_analyst(parsed_docs, det, [], {})
    assert r["output"].summary == f"Local evidence extraction examined {len(seen)} source passages."
    assert r["output"].data_quality_issues == []
    assert len(seen) >= 2 and r["meta"].tokens_in == 10 * len(seen)


def test_local_batch_failure_is_not_silently_ignored(monkeypatch, parsed_docs):
    det = extract_all(parsed_docs)
    monkeypatch.setattr(data_analyst.settings, "using_ollama", True)
    def fake(*args, **kwargs):
        raise AgentError("invalid response")
    monkeypatch.setattr(data_analyst, "call_structured", fake)
    import pytest
    with pytest.raises(AgentError, match="source 1/"):
        data_analyst.run_data_analyst(parsed_docs, det, [], {})


def test_profit_decline_overrides_mixed_headline(extraction):
    cf = build_company_forecast(extraction, 6)
    assert cf.get("operating_profit").change_pct < -10
    assert overall_label(cf, [])[0] == "LIKELY DETERIORATING"
