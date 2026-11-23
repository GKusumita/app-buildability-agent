from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from schema import AppResult, Evidence, load_apps, unknown_result
from pipeline.evidence_check import validate_evidence
from pipeline.llm import provider_config
from pipeline.pass3_verify import consistency
from pipeline.research import Tavily


class FakeResponse:
    def __init__(self, data):
        self.data = data
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeClient:
    def __init__(self):
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append(url)
        if url.endswith("/search"):
            return FakeResponse({"results": [{"url": "https://docs.example.com/auth", "title": "Auth"}]})
        return FakeResponse({"results": [{"url": "https://docs.example.com/auth",
                                          "raw_content": "Use an API key."}]})


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.app = load_apps()[0]

    def test_closed_schema_and_identity(self):
        row = unknown_result(self.app, "test").model_dump(mode="json")
        row["verdict"] = "certainly_buildable"
        with self.assertRaises(ValidationError):
            AppResult.model_validate(row)
        self.assertEqual(len(load_apps()), 100)

    def test_verbatim_evidence_fails_closed(self):
        url = "https://docs.example.com/auth"
        row = unknown_result(self.app, "test")
        row.auth_methods = ["api_key"]
        row.self_serve = "free_self_serve"
        row.evidence = [Evidence(field="auth_methods", url=url, snippet="Use an  API key."),
                        Evidence(field="self_serve", url=url, snippet="Free forever")]
        checked, invalid = validate_evidence(row, {url: "Use an API key."})
        self.assertEqual([str(x) for x in checked.auth_methods], ["api_key"])
        self.assertEqual(str(checked.self_serve), "unknown")
        self.assertTrue(any(x.startswith("self_serve: evidence_invalid") for x in invalid))

    def test_inconsistent_now_is_removed(self):
        row = unknown_result(self.app, "test")
        row.verdict = "buildable_now"
        checked, issue = consistency(row)
        self.assertEqual(str(checked.verdict), "could_not_identify")
        self.assertIn("lacks known", issue)

    def test_tavily_cache_avoids_repeat_credits(self):
        async def work():
            client = FakeClient()
            tavily = Tavily(client)
            tavily.key = "fake-key"
            with tempfile.TemporaryDirectory() as directory, patch("pipeline.research.ROOT", Path(directory)):
                (Path(directory) / "cache").mkdir()
                await tavily.search("Example API")
                await tavily.search("Example API")
                await tavily.extract(["https://docs.example.com/auth"])
                await tavily.extract(["https://docs.example.com/auth"])
                self.assertEqual(len(list((Path(directory) / "cache").glob("search_result-*.json"))), 1)
            self.assertEqual(len(client.calls), 2)
        asyncio.run(work())

    def test_openrouter_model_mapping(self):
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fake-key"}):
            provider, endpoint, key, model = provider_config("gpt-4.1-mini")
        self.assertEqual(provider, "openrouter")
        self.assertEqual(model, "openai/gpt-4.1-mini")
        self.assertEqual(key, "fake-key")
        self.assertTrue(endpoint.endswith("/chat/completions"))


if __name__ == "__main__":
    unittest.main()
