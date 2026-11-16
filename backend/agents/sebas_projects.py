"""Agent 3: Sebas, project financial analyst."""
from __future__ import annotations

import json

from agents.llm_client import call_structured
from agents.prompts import SEBAS
from agents.schemas import ProjectAnalysisSet


def build_input(context: dict) -> str:
    return (
        "Analyze each project's financial health and likely final cost.\n<context_data>\n"
        + json.dumps(context, ensure_ascii=False, default=str)
        + "\n</context_data>"
    )


def run_sebas(context: dict):
    return call_structured("sebas", SEBAS, build_input(context), ProjectAnalysisSet)
