"""Agent 2: Emily, company financial analyst."""
from __future__ import annotations

import json

from agents.llm_client import call_structured
from agents.prompts import EMILY
from agents.schemas import CompanyAnalysis


def build_input(context: dict) -> str:
    return (
        "Analyze the company's financial performance.\n<context_data>\n"
        + json.dumps(context, ensure_ascii=False, default=str)
        + "\n</context_data>"
    )


def run_emily(context: dict):
    return call_structured("emily", EMILY, build_input(context), CompanyAnalysis)
