"""Health and OpenAI setup checks."""
from __future__ import annotations

from fastapi import APIRouter

from agents.llm_client import test_connection
from config import settings

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {
        "ok": True,
        "ai_enabled": settings.ai_enabled,
        "model": settings.openai_model,
        "provider": "ollama" if settings.using_ollama else ("openrouter" if settings.using_openrouter else "openai"),
        "setup_message": None if settings.ai_enabled else (
            "AI agents are not configured. Add OPENAI_API_KEY to backend/.env or set SENTINEL_AI_PROVIDER=ollama and restart. "
            "Until then Sentinel runs document extraction and the forecasting engine only, and says so in every result."
        ),
    }


@router.post("/health/openai-test")
def openai_test():
    return test_connection()
