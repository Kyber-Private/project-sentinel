"""OpenAI Responses API wrapper with structured outputs, timeouts, and retries.

Every agent call goes through call_structured(). The output is parsed by the
SDK against a Pydantic schema and validated again before use. Nothing here
fabricates a result: on failure an AgentError is raised and the caller
records the failure.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from config import settings

log = logging.getLogger("sentinel.agents")
T = TypeVar("T", bound=BaseModel)


class AgentError(Exception):
    """Raised when an agent call cannot produce a valid result."""


class AgentNotConfigured(AgentError):
    pass


@dataclass
class CallMeta:
    model: str
    duration_ms: int
    tokens_in: Optional[int]
    tokens_out: Optional[int]
    response_id: Optional[str]
    attempts: int


# Tests can replace this with a fake client factory.
_client_factory = None


def set_client_factory(factory) -> None:
    global _client_factory
    _client_factory = factory


def _client():
    if _client_factory is not None:
        return _client_factory()
    if not settings.openai_api_key:
        raise AgentNotConfigured("OPENAI_API_KEY is not set.")
    from openai import OpenAI

    kwargs: dict[str, Any] = dict(api_key=settings.openai_api_key, timeout=settings.openai_timeout_seconds, max_retries=0)
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    if settings.using_openrouter:
        kwargs["default_headers"] = {"HTTP-Referer": "http://localhost:3000", "X-Title": "Project Sentinel"}
    return OpenAI(**kwargs)


def _input_as_text(user_input: Any) -> str:
    """Flatten Responses-style input messages into plain text for Chat Completions."""
    if isinstance(user_input, str):
        return user_input
    parts: list[str] = []
    for msg in user_input:
        content = msg.get("content", [])
        if isinstance(content, str):
            parts.append(content)
            continue
        for part in content:
            if part.get("type") in ("input_text", "text"):
                parts.append(part["text"])
    return "\n".join(parts)


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def call_structured(
    agent: str,
    instructions: str,
    user_input: Any,
    schema: Type[T],
    max_output_tokens: int = 16000,
) -> tuple[T, CallMeta]:
    """Run one Responses API call and return a validated schema instance."""
    try:
        import openai
    except ImportError as exc:  # pragma: no cover
        raise AgentError("The openai package is not installed.") from exc

    client = _client()
    retryable = (
        openai.APITimeoutError,
        openai.APIConnectionError,
        openai.RateLimitError,
        openai.InternalServerError,
    )
    effort = os.environ.get("OPENAI_REASONING_EFFORT", "medium").strip()
    chat_mode = settings.openai_api_mode == "chat"
    structured = True  # chat mode: ask for a JSON schema; falls back to plain JSON if the provider refuses
    attempts = 0
    last_error: Optional[Exception] = None
    start = time.monotonic()
    max_attempts = 1 + max(0, settings.openai_max_retries)
    while attempts < max_attempts:
        attempts += 1
        if chat_mode:
            system_text = instructions
            if not structured:
                system_text += (
                    "\n\nReturn ONLY one JSON object that follows this JSON Schema. No markdown, no commentary.\n"
                    + json.dumps(schema.model_json_schema())
                )
            kwargs: dict[str, Any] = dict(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": _input_as_text(user_input)},
                ],
                max_tokens=max_output_tokens,
            )
            if structured:
                kwargs["response_format"] = schema
            if effort:
                kwargs["extra_body"] = {"reasoning": {"effort": effort}}
        else:
            kwargs = dict(
                model=settings.openai_model,
                instructions=instructions,
                input=user_input,
                text_format=schema,
                max_output_tokens=max_output_tokens,
            )
            if effort:
                kwargs["reasoning"] = {"effort": effort}
        try:
            if chat_mode:
                if structured:
                    response = client.chat.completions.parse(**kwargs)
                else:
                    response = client.chat.completions.create(**kwargs)
                message = response.choices[0].message if getattr(response, "choices", None) else None
                parsed = getattr(message, "parsed", None) if message else None
                if parsed is None and message is not None and getattr(message, "content", None):
                    parsed = _json_from_text(message.content)  # provider ignored the schema but returned JSON text
            else:
                response = client.responses.parse(**kwargs)
                parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                raise AgentError(f"{agent}: the model returned no structured output (possibly a refusal or truncation).")
            result = schema.model_validate(parsed.model_dump() if isinstance(parsed, BaseModel) else parsed)
            usage = getattr(response, "usage", None)
            tokens_in = getattr(usage, "prompt_tokens" if chat_mode else "input_tokens", None) if usage else None
            tokens_out = getattr(usage, "completion_tokens" if chat_mode else "output_tokens", None) if usage else None
            meta = CallMeta(
                model=getattr(response, "model", settings.openai_model) or settings.openai_model,
                duration_ms=int((time.monotonic() - start) * 1000),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                response_id=getattr(response, "id", None),
                attempts=attempts,
            )
            log.info("agent=%s ok attempts=%s ms=%s structured=%s", agent, attempts, meta.duration_ms, structured)
            return result, meta
        except retryable as exc:
            last_error = exc
            log.warning("agent=%s retryable error attempt=%s: %s", agent, attempts, exc)
            time.sleep(min(8.0, 1.5 * attempts))
        except (openai.BadRequestError, openai.NotFoundError) as exc:
            msg = str(exc)
            last_error = exc
            log.warning("agent=%s request rejected: %s", agent, msg[:500])
            if "reasoning" in msg.lower() and effort:
                effort = ""  # model does not accept the reasoning parameter; retry without it
                attempts -= 1
                continue
            if chat_mode and structured:
                structured = False  # provider cannot do JSON-schema outputs; ask for plain JSON instead
                effort = effort  # keep reasoning as is
                attempts -= 1
                continue
            if isinstance(exc, openai.NotFoundError):
                raise AgentError(
                    f"{agent}: model '{settings.openai_model}' was not found or has no available provider. "
                    f"Server said: {msg[:250]}"
                ) from exc
            raise AgentError(f"{agent}: the API rejected the request: {msg[:300]}") from exc
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            where = "OpenRouter" if settings.using_openrouter else "OpenAI"
            raise AgentError(f"{agent}: {where} authentication failed. Check OPENAI_API_KEY. Server said: {str(exc)[:200]}") from exc
        except (ValidationError, json.JSONDecodeError) as exc:
            last_error = exc
            log.warning("agent=%s invalid output attempt=%s: %s", agent, attempts, exc)
            if chat_mode and structured:
                structured = False
        except AgentError as exc:
            last_error = exc
    raise AgentError(f"{agent}: failed after {attempts} attempt(s): {last_error}")


def _json_from_text(text: str) -> Any:
    """Pull one JSON object out of a model reply, tolerating code fences and stray words."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    first, last = t.find("{"), t.rfind("}")
    if first == -1 or last <= first:
        raise json.JSONDecodeError("no JSON object in the reply", t, 0)
    return json.loads(t[first : last + 1])


def test_connection() -> dict:
    """Small live call used by the setup check endpoint."""

    class Ping(BaseModel):
        ok: bool
        message: str

    try:
        result, meta = call_structured(
            "connection_test",
            "Reply with ok=true and a five-word message.",
            "Connection test from Project Sentinel.",
            Ping,
            max_output_tokens=2000,
        )
        return {"ok": True, "model": meta.model, "duration_ms": meta.duration_ms, "message": result.message}
    except AgentNotConfigured as exc:
        return {"ok": False, "error": str(exc)}
    except AgentError as exc:
        return {"ok": False, "error": str(exc)}
