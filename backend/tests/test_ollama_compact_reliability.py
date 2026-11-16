"""New adversarial regression tests using actual Nova files and compact local schema.

Network responses are stubbed because user-local Ollama is not accessible here.
These tests check output size, traceability, failure visibility, model cache
invalidation, and schema constraints, not model reasoning quality.
"""
import json
from agents import data_analyst
from agents.llm_client import AgentError, CallMeta
from agents.schemas import DataAnalystOutput
from documents.pipeline import extract_all


def meta():
    return CallMeta("qwen3:8b", 3, 30, 25, None, 1)


def test_compact_schema_has_no_deep_nested_analyst_fields():
    schema = data_analyst.LocalObservations.model_json_schema()
    assert set(schema["properties"]) == {"facts"}
    fields = schema["$defs"]["LocalObservation"]["properties"]
    assert set(fields) == {"quote", "metric", "value", "entity", "entity_type"}
    assert "suggested_questions" not in json.dumps(schema)
    assert len(json.dumps(schema)) < 2200


def test_actual_documents_are_split_individually_without_losing_evidence(parsed_docs):
    det = extract_all(parsed_docs)
    _, chunks, _ = data_analyst.build_input(parsed_docs, det, [])
    batches = data_analyst._local_batches(chunks)
    assert len(batches) >= 5
    assert all(len(group) == 1 for group in batches)
    assert [group[0]["chunk_id"] for group in batches] == [c["chunk_id"] for c in chunks]


def test_fact_extract_uses_quote_not_model_supplied_source(monkeypatch, parsed_docs):
    det = extract_all(parsed_docs)
    _, chunks, _ = data_analyst.build_input(parsed_docs, det, [])
    monkeypatch.setattr(data_analyst.settings, "using_ollama", True)
    source = next(c for c in chunks if 'supplier price' in c['text'].lower())
    quoted = source['text'][:min(60,len(source['text']))]
    idx = source['chunk_id']
    calls = []
    def fake(agent, instructions, user_input, schema, max_output_tokens):
        calls.append((user_input, max_output_tokens))
        if idx in user_input:
            return data_analyst.LocalObservations(facts=[data_analyst.LocalObservation(
                quote=quoted, metric='business_note', value=None,
                entity='Nova Industries', entity_type='company'
            )]), meta()
        return data_analyst.LocalObservations(facts=[]), meta()
    monkeypatch.setattr(data_analyst, 'call_structured', fake)
    out = data_analyst.run_data_analyst(parsed_docs, det, [], {})
    assert len(calls)==len(chunks)
    assert all(limit<=2000 for _,limit in calls)
    assert out['from_cache'] is False
    assert all(f.source.file_name for f in out['facts'])
    assert all(f.source.excerpt in quoted for f in out['facts'])


def test_invented_quotes_and_numbers_rejected(monkeypatch, parsed_docs):
    det=extract_all(parsed_docs)
    monkeypatch.setattr(data_analyst.settings,'using_ollama',True)
    def fake(*args,**kwargs):
        return data_analyst.LocalObservations(facts=[data_analyst.LocalObservation(
            quote='CEO said 500000000 dollars in gold revenue', metric='revenue',
            value=500000000, entity='Nova', entity_type='company')]),meta()
    monkeypatch.setattr(data_analyst,'call_structured',fake)
    out=data_analyst.run_data_analyst(parsed_docs,det,[],{})
    assert not out['facts']
    assert len(out['rejected'])>0


def test_invalid_metric_is_dropped(monkeypatch, parsed_docs):
    det=extract_all(parsed_docs)
    monkeypatch.setattr(data_analyst.settings,'using_ollama',True)
    def fake(*args,**kwargs):
        return data_analyst.LocalObservations(facts=[data_analyst.LocalObservation(
            quote='Lots of money', metric='make_it_rain', value=42,
            entity='Nova', entity_type='company')]),meta()
    monkeypatch.setattr(data_analyst,'call_structured',fake)
    out=data_analyst.run_data_analyst(parsed_docs,det,[],{})
    assert not out['facts']


def test_cached_old_provider_output_not_reused(monkeypatch,parsed_docs):
    det=extract_all(parsed_docs)
    monkeypatch.setattr(data_analyst.settings,'using_ollama',True)
    calls=[]
    def fake(*args,**kwargs):
        calls.append(1)
        return data_analyst.LocalObservations(facts=[]),meta()
    monkeypatch.setattr(data_analyst,'call_structured',fake)
    old={'input_hash':'OLD_HASH','output':{'raw':DataAnalystOutput(summary='cloud',facts=[],data_quality_issues=[],missing_information=[],conflicts_noticed=[],relationships=[],suggested_questions=[]).model_dump()}}
    out=data_analyst.run_data_analyst(parsed_docs,det,[],{},cached=old)
    assert calls and not out['from_cache']


def test_model_error_is_not_marked_success(monkeypatch,parsed_docs):
    det=extract_all(parsed_docs)
    monkeypatch.setattr(data_analyst.settings,'using_ollama',True)
    def fake(*args,**kwargs): raise AgentError('bad model response')
    monkeypatch.setattr(data_analyst,'call_structured',fake)
    import pytest
    with pytest.raises(AgentError,match='source 1/'):
        data_analyst.run_data_analyst(parsed_docs,det,[],{})


def test_oversized_source_split_with_stable_citations(parsed_docs):
    det=extract_all(parsed_docs)
    _,chunks,_=data_analyst.build_input(parsed_docs,det,[])
    original=chunks[0]
    giant=dict(original, text='Test budget: $123,456. '*500)
    parts=data_analyst._local_batches([giant],target_chars=1200)
    assert len(parts)>=5
    assert all(part[0]['chunk_id']==giant['chunk_id'] for part in parts)
    assert all(len(part[0]['text'])<=1200 for part in parts)
    assert 'Test budget: $123,456.' in parts[0][0]['text']
