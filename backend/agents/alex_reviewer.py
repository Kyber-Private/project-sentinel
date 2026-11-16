"""Agent 4: Alex, independent forecast reviewer."""
from __future__ import annotations

import json

from agents.llm_client import call_structured
from agents.prompts import ALEX
from agents.schemas import ReviewOutput


def build_input(context: dict) -> str:
    return (
        "Review the analysis below. Challenge anything the evidence does not support.\n<context_data>\n"
        + json.dumps(context, ensure_ascii=False, default=str)
        + "\n</context_data>"
    )


def run_alex(context: dict):
    return call_structured("alex", ALEX, build_input(context), ReviewOutput)
