"""Small OpenAI Responses client with strict structured output and call logs."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pydantic import BaseModel

from schema import ROOT


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


async def structured_call(client: httpx.AsyncClient, model: str, prompt: str,
                          output_model: type[BaseModel], label: str) -> tuple[BaseModel, dict]:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing")
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    body = {
        "model": model, "temperature": 0, "store": False,
        "input": [{"role": "user", "content": prompt}],
        "text": {"format": {"type": "json_schema", "name": output_model.__name__.lower(),
                            "strict": True, "schema": strict_schema(output_model)}},
    }
    usage: dict = {}
    error = ""
    try:
        response = await client.post("https://api.openai.com/v1/responses", json=body,
                                     headers={"Authorization": f"Bearer {key}"}, timeout=120)
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage", {})
        if data.get("status") != "completed":
            raise RuntimeError(f"OpenAI response status: {data.get('status')}")
        texts = [part.get("text", "") for item in data.get("output", [])
                 for part in item.get("content", []) if part.get("type") == "output_text"]
        if len(texts) != 1:
            raise RuntimeError("Expected one structured output text")
        parsed = output_model.model_validate_json(texts[0])
        return parsed, usage
    except Exception as exc:
        error = str(exc)[:500]
        raise
    finally:
        log = {"at": datetime.now(timezone.utc).isoformat(), "label": label,
               "prompt_sha256": prompt_hash, "model": model, "usage": usage, "error": error}
        with (ROOT / "logs" / "llm.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(log, ensure_ascii=False) + "\n")


def rubric_text() -> str:
    return (ROOT / "rubric.md").read_text(encoding="utf-8")
