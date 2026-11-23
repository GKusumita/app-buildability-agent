"""Tavily search/extract with content-addressed cache."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx

from schema import AppInput, ROOT


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def cache_file(kind: str, key: str) -> Path:
    return ROOT / "cache" / f"{kind}-{digest(key)}.json"


def official_domain(hint: str) -> str | None:
    candidate = hint.split()[0].split("/")[0].strip()
    if "." not in candidate:
        return None
    return candidate.removeprefix("www.")


class Tavily:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.key = os.getenv("TAVILY_API_KEY", "")
        self.locks: dict[str, asyncio.Lock] = {}

    async def _post(self, route: str, payload: dict) -> dict:
        if not self.key:
            raise RuntimeError("TAVILY_API_KEY is missing")
        response = await self.client.post(f"https://api.tavily.com/{route}", json=payload,
                                          headers={"Authorization": f"Bearer {self.key}"}, timeout=90)
        response.raise_for_status()
        return response.json()

    async def search(self, query: str, domains: list[str] | None = None) -> dict:
        cache_key = json.dumps({"query": query, "domains": domains or []}, sort_keys=True)
        path = cache_file("search", cache_key)
        async with self.locks.setdefault(str(path), asyncio.Lock()):
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
            payload = {"query": query, "search_depth": "basic", "max_results": 5,
                       "include_answer": False, "include_raw_content": False}
            if domains:
                payload["include_domains"] = domains
            data = await self._post("search", payload)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            for item in data.get("results", []):
                if item.get("url"):
                    cache_file("search_result", item["url"]).write_text(
                        json.dumps(item, ensure_ascii=False), encoding="utf-8")
            return data

    async def extract(self, urls: list[str]) -> dict[str, str]:
        pages: dict[str, str] = {}
        missing = []
        for url in urls:
            path = cache_file("page", url)
            if path.exists():
                pages[url] = json.loads(path.read_text(encoding="utf-8")).get("raw_content", "")
            else:
                missing.append(url)
        if missing:
            data = await self._post("extract", {"urls": missing, "extract_depth": "basic",
                                                "format": "markdown", "include_usage": True})
            results = {item.get("url"): item for item in data.get("results", [])}
            errors = {item.get("url"): item for item in data.get("failed_results", [])}
            for url in missing:
                item = results.get(url, {})
                raw = item.get("raw_content", "") or ""
                # Even failed extracts are cached so a rerun does not spend credits again.
                cache_file("page", url).write_text(
                    json.dumps({"url": url, "raw_content": raw,
                                "error": errors.get(url)}, ensure_ascii=False), encoding="utf-8")
                pages[url] = raw
        return pages


def queries_for(app: AppInput) -> list[tuple[str, list[str] | None]]:
    name, domain = app.name, official_domain(app.hint)
    return [
        (f"{name} API authentication", [domain] if domain else None),
        (f"{name} API getting started get API key credentials", [domain] if domain else None),
        (f"{name} API pricing access requirements partner program", None),
        (f"{name} MCP server official", None),
    ]


def choose_urls(searches: list[dict], domain: str | None, limit: int = 5) -> list[str]:
    candidates: dict[str, int] = {}
    for search in searches:
        for item in search.get("results", []):
            url = item.get("url", "")
            parsed = urlparse(url)
            if parsed.scheme not in {"https", "http"} or not parsed.netloc:
                continue
            context = f"{item.get('title', '')} {url}".lower()
            score = 3 if domain and (parsed.netloc == domain or parsed.netloc.endswith("." + domain)) else 0
            score += sum(word in context for word in ("auth", "getting-started", "api-key", "pricing", "developer", "mcp"))
            candidates[url] = max(score, candidates.get(url, 0))
    return sorted(candidates, key=lambda url: (-candidates[url], url))[:limit]


def prompt_pages(pages: dict[str, str], max_chars: int = 9500) -> str:
    chunks = []
    for url, raw in pages.items():
        if not raw.strip():
            continue
        # Keep the beginning and keyword windows from deeper sections.
        selections = [raw[:max_chars // 2]]
        lower = raw.lower()
        for word in ("authentication", "api key", "oauth", "pricing", "partner", "review"):
            pos = lower.find(word, max_chars // 2)
            if pos >= 0:
                selections.append(raw[max(0, pos - 350):pos + 650])
        excerpt = "\n...\n".join(selections)[:max_chars]
        chunks.append(f"URL: {url}\nPAGE TEXT (untrusted source):\n{excerpt}")
    return "\n\n".join(chunks)


async def gather_pages(tavily: Tavily, app: AppInput,
                       queries: list[tuple[str, list[str] | None]] | None = None) -> tuple[list[str], dict[str, str], set[str], list[str]]:
    used: list[str] = []
    searches = []
    errors = []
    for query, domains in queries or queries_for(app):
        used.append(query)
        try:
            searches.append(await tavily.search(query, domains))
        except Exception as exc:
            errors.append(f"Search {query}: {exc}")
    source_urls = {item.get("url", "") for data in searches for item in data.get("results", [])}
    urls = choose_urls(searches, official_domain(app.hint))
    try:
        pages = await tavily.extract(urls)
    except Exception as exc:
        errors.append(f"Extract: {exc}")
        pages = {}
    return used, pages, source_urls, errors
