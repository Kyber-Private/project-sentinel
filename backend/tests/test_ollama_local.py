"""Regression tests for opt-in, keyless Ollama mode (network mocked)."""
from __future__ import annotations
from types import SimpleNamespace
import json
import pytest
import httpx
from pydantic import BaseModel
import config
from agents import llm_client
from finance.calculations import months_between

class Ping(BaseModel):
    ok: bool
    message: str

def test_ollama_requires_no_key(monkeypatch):
    monkeypatch.setenv("SENTINEL_AI_PROVIDER", "ollama")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    s = config.Settings()
    assert s.ai_enabled and s.using_ollama and s.openai_model == "qwen3:8b"
    assert s.ollama_url == "http://127.0.0.1:11434"

def test_ollama_schema_validation_and_local_only(monkeypatch):
    monkeypatch.setattr(config.settings, "using_ollama", True)
    monkeypatch.setattr(config.settings, "ollama_model", "qwen3:8b")
    monkeypatch.setattr(config.settings, "openai_model", "qwen3:8b")
    seen = []
    class Client:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json):
            assert url == "http://127.0.0.1:11434/api/chat"
            assert json["format"]["type"] == "object"
            assert json["think"] is False
            seen.append(json)
            return httpx.Response(200, json={"message":{"content":'{"ok":true,"message":"Local connection works"}'},"prompt_eval_count":10,"eval_count":8}, request=httpx.Request("POST",url))
    monkeypatch.setattr(httpx, "Client", Client)
    obj, meta = llm_client.call_structured("ping", "Reply as JSON", "test", Ping)
    assert obj.ok and meta.model == "qwen3:8b" and len(seen) == 1

def test_ollama_rejects_invalid_schema(monkeypatch):
    monkeypatch.setattr(config.settings, "using_ollama", True)
    monkeypatch.setattr(config.settings, "openai_max_retries", 0)
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json):
            return httpx.Response(200, json={"message":{"content":'{"ok":"not_boolean","message":55}'}},request=httpx.Request("POST",url))
    monkeypatch.setattr(httpx, "Client", Client)
    with pytest.raises(llm_client.AgentError, match="could not produce valid structured"):
        llm_client.call_structured("ping", "Reply", "test", Ping)

def test_written_months_are_supported():
    assert months_between("2026-10", "January 2027") == 3
    assert months_between("Oct 2026", "2027-01") == 3
