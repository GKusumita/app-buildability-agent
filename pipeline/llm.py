"""Strict JSON output via OpenRouter or OpenAI, with call logs."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pydantic import BaseModel

from schema import AppResult, ROOT


def normalise_app_result_payload(payload: dict) -> list[str]:
    """Resolve mixed sentinel values before Pydantic's cross-field validation."""
    changes = []
    for field in ("auth_methods", "api_type"):
        values = payload.get(field)
        if not isinstance(values, list) or len(values) < 2:
            continue
        sentinels = {"unknown"}
        if field == "auth_methods":
            sentinels.add("none")
        reduced = [value for value in values if value not in sentinels]
        if reduced and len(reduced) != len(values):
            payload[field] = reduced
            changes.append(f"{field}: removed mixed sentinel")
    return changes


def strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic schemas here use only the supported object/array/enum subset."""
    schema = model.model_json_schema()
    def clean(node: object) -> object:
        if isinstance(node, list):
            return [clean(item) for item in node]
        if not isinstance(node, dict):
            return node
        return {key: clean(value) for key, value in node.items()
                if key not in {"title", "default", "minLength", "maxLength"}}
    return clean(schema)


def provider_config(model: str) -> tuple[str, str, str, str]:
    router_key = os.getenv("OPENROUTER_API_KEY")
    if router_key:
        routed_model = "openai/" + model if model.startswith("gpt-") else model
        return "openrouter", "https://openrouter.ai/api/v1/chat/completions", router_key, routed_model
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Set OPENROUTER_API_KEY or OPENAI_API_KEY")
    return "openai", "https://api.openai.com/v1/responses", key, model.removeprefix("openai/")


async def structured_call(client: httpx.AsyncClient, model: str, prompt: str,
                          output_model: type[BaseModel], label: str) -> tuple[BaseModel, dict]:
    provider, endpoint, key, actual_model = provider_config(model)
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    format_schema = {"name": output_model.__name__.lower(), "strict": True,
                     "schema": strict_schema(output_model)}
    if provider == "openrouter":
        body = {"model": actual_model, "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_schema", "json_schema": format_schema},
                "provider": {"require_parameters": True}}
    else:
        body = {"model": actual_model, "temperature": 0, "store": False,
                "input": [{"role": "user", "content": prompt}],
                "text": {"format": {"type": "json_schema", **format_schema}}}
    usage: dict = {}
    error = ""
    attempts = 0
    try:
        for attempts in range(1, 4):
            response = await client.post(endpoint, json=body,
                                         headers={"Authorization": f"Bearer {key}"}, timeout=120)
            if response.status_code in {429, 500, 502, 503, 504} and attempts < 3:
                await asyncio.sleep(2 ** attempts)
                continue
            response.raise_for_status()
            break
        data = response.json()
        usage = data.get("usage", {})
        if provider == "openrouter":
            choices = data.get("choices", [])
            if len(choices) != 1 or choices[0].get("finish_reason") != "stop":
                raise RuntimeError("OpenRouter returned no complete structured response")
            message = choices[0].get("message", {})
            if message.get("refusal"):
                raise RuntimeError("OpenRouter model refused the request")
            output_text = message.get("content")
        else:
            if data.get("status") != "completed":
                raise RuntimeError(f"OpenAI response status: {data.get('status')}")
            texts = [part.get("text", "") for item in data.get("output", [])
                     for part in item.get("content", []) if part.get("type") == "output_text"]
            output_text = texts[0] if len(texts) == 1 else None
        if not isinstance(output_text, str) or not output_text.strip():
            raise RuntimeError("Expected one structured output text")
        if output_model is AppResult:
            payload = json.loads(output_text)
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object")
            changes = normalise_app_result_payload(payload)
            if changes:
                usage = {**usage, "schema_normalisations": changes}
            parsed = output_model.model_validate(payload)
        else:
            parsed = output_model.model_validate_json(output_text)
        return parsed, usage
    except Exception as exc:
        error = str(exc)[:500]
        raise
    finally:
        log = {"at": datetime.now(timezone.utc).isoformat(), "label": label,
               "prompt_sha256": prompt_hash, "provider": provider,
               "model": actual_model, "usage": usage, "attempts": attempts, "error": error}
        with (ROOT / "logs" / "llm.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(log, ensure_ascii=False) + "\n")


def rubric_text() -> str:
    return (ROOT / "rubric.md").read_text(encoding="utf-8")
