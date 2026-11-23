from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from schema import (APIType, AppResult, Auth, Breadth, Confidence, Evidence,
                    SelfServe, Tri, Verdict, load_apps, unknown_result)
from pipeline.evidence_check import validate_evidence
from pipeline.common import path_for
from pipeline.llm import model_for, normalise_app_result_payload, provider_config, structured_call
from pipeline.pass3_verify import (Check, Verification, compute_confidence,
                                   consistency, unknown_fields, verify)
from pipeline.research import Tavily, quote_bank, resolve_quote_ids
from pipeline.rules import apply_rule2, constrain_official_mcp
from pipeline.score import TUNED_APPS, exclude_tuned, label_issues, normalize


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

    def test_scoring_rejects_incomplete_or_non_enum_human_labels(self):
        row = {"name": "Salesforce", "auth_methods": "oauth2", "self_serve": "free_self_serve",
               "app_review_required": "false", "api_type": "rest", "official_mcp": "not_exists",
               "verdict": "buildable_now", "blocker": "none"}
        self.assertEqual(label_issues([row]), [])
        row["self_serve"] = "paid_self_serve"
        row["verdict"] = ""
        issues = label_issues([row])
        self.assertTrue(any("self_serve" in issue for issue in issues))
        self.assertTrue(any("verdict" in issue for issue in issues))

    def test_scoring_excludes_all_six_tuned_apps(self):
        rows = [{"name": name} for name in sorted(TUNED_APPS)] + [{"name": "Pipedrive"}]
        self.assertEqual([row["name"] for row in exclude_tuned(rows)], ["Pipedrive"])
        self.assertEqual(len(TUNED_APPS), 6)

    def test_unconfirmed_mcp_is_not_scored_as_not_exists(self):
        self.assertEqual(normalize("official_mcp", "unknown"), "unconfirmed")
        self.assertEqual(normalize("official_mcp", "unconfirmed"), "unconfirmed")
        self.assertEqual(normalize("official_mcp", "none"), "none")

    def test_single_app_run_tag_keeps_old_output_name_available(self):
        self.assertEqual(path_for("pass2", False, self.app, "retry2").name,
                         f"pass2_app_{self.app.id}_retry2.json")
        self.assertEqual(path_for("pass2", False, self.app, "").name,
                         f"pass2_app_{self.app.id}.json")

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
        self.assertIn("unknown", issue)

    def test_now_requires_known_auth_and_access(self):
        row = unknown_result(self.app, "test")
        row.api_type = ["rest"]
        row.app_review_required = "false"
        row.verdict = "buildable_now"
        for auth, access in [(["unknown"], "free_self_serve"), (["api_key"], "unknown")]:
            candidate = row.model_copy(deep=True)
            candidate.auth_methods = auth
            candidate.self_serve = access
            checked, issue = consistency(candidate)
            self.assertEqual(str(checked.verdict), "could_not_identify")
            self.assertIn("unknown", issue)

    def test_rule2_is_deterministic_for_mermaid_cli(self):
        app = next(app for app in load_apps() if app.name == "Mermaid CLI")
        row = unknown_result(app, "test")
        url = "https://github.com/mermaid-js/mermaid-cli"
        pages = {url: ("[MIT license](#MIT-1-ov-file)\n"
                       "This is a command-line interface (CLI) that generates SVG diagrams from local files.\n")}
        fixed, rule = apply_rule2(app, row, pages)
        self.assertIsNotNone(rule)
        self.assertEqual([str(auth) for auth in fixed.auth_methods], ["none"])
        self.assertEqual(str(fixed.self_serve), "not_applicable")
        self.assertEqual(str(fixed.verdict), "not_applicable")
        checked, invalid = validate_evidence(fixed, pages)
        self.assertEqual(invalid, [])
        self.assertEqual(str(checked.self_serve), "not_applicable")

    def test_official_mcp_requires_app_owned_mcp_location(self):
        row = unknown_result(self.app, "test")
        row.official_mcp = "https://github.com/unrelated/mcp-server"
        checked, issue = constrain_official_mcp(self.app, row)
        self.assertEqual(checked.official_mcp, "unknown")
        self.assertIsNotNone(issue)
        row.official_mcp = "https://mcp.salesforce.com/mcp"
        checked, issue = constrain_official_mcp(self.app, row)
        self.assertEqual(checked.official_mcp, row.official_mcp)
        self.assertIsNone(issue)

    def test_confidence_comes_from_checks_and_unknown_count(self):
        row = unknown_result(self.app, "test")
        row.auth_methods = [Auth.API_KEY]
        row.self_serve = SelfServe.FREE
        row.api_type = [APIType.REST]
        row.verdict = Verdict.NOW
        row.app_review_required = Tri.FALSE
        row.confidence = Confidence.HIGH  # Deliberately untrusted model value.
        decisions = [{"initial": {"status": "supported"}, "retry": None} for _ in range(5)]
        self.assertEqual(str(compute_confidence(row, decisions, [], [])), "medium")
        row.api_breadth = Breadth.BROAD
        row.official_mcp = "none"
        row.webhooks = Tri.TRUE
        row.rate_limits = "documented"
        self.assertEqual(unknown_fields(row), [])
        self.assertEqual(str(compute_confidence(row, decisions, [], [])), "high")
        self.assertEqual(str(compute_confidence(row, decisions, [], ["verdict rejected"])), "low")

    def test_verifier_cannot_support_an_unknown_claim(self):
        row = unknown_result(self.app, "test")
        yes = Check(status="supported", reason="model says supported")
        answer = Verification(**{field: yes.model_copy(deep=True) for field in
                                 ("auth_methods", "self_serve", "api_type",
                                  "app_review_required", "verdict")})
        async def fake_call(*args, **kwargs):
            return answer, {}
        async def work():
            with patch("pipeline.pass3_verify.structured_call", fake_call):
                return await verify(None, row, {}, "test")
        checked, _ = asyncio.run(work())
        self.assertEqual(checked.auth_methods.status, "insufficient_evidence")
        self.assertEqual(checked.verdict.status, "insufficient_evidence")

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
        with patch.dict("os.environ", {"LLM_PROVIDER": "openrouter", "OPENROUTER_API_KEY": "fake-key"}):
            provider, endpoint, key, model = provider_config("gpt-4.1-mini")
        self.assertEqual(provider, "openrouter")
        self.assertEqual(model, "openai/gpt-4.1-mini")
        self.assertEqual(key, "fake-key")
        self.assertTrue(endpoint.endswith("/chat/completions"))

    def test_gemini_selection_and_native_structured_request(self):
        class GeminiClient:
            async def post(self, url, **kwargs):
                self.url, self.kwargs = url, kwargs
                return FakeResponse({"candidates": [{"finishReason": "STOP", "content": {
                    "parts": [{"text": '{"status":"supported","reason":"verified"}'}]}}],
                    "usageMetadata": {"totalTokenCount": 17}})

        async def work():
            client = GeminiClient()
            with tempfile.TemporaryDirectory() as directory:
                (Path(directory) / "logs").mkdir()
                with patch("pipeline.llm.ROOT", Path(directory)), patch.dict("os.environ", {
                        "LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "fake-gemini-key",
                        "OPENROUTER_API_KEY": "unused-router-key", "LLM_MODEL": "gemini-3.5-flash-lite",
                        "LLM_VERIFY_MODEL": "gemini-3.8-flash"}):
                    self.assertEqual(model_for(verify=True), "gemini-3.8-flash")
                    answer, usage = await structured_call(client, model_for(verify=True),
                                                          "Check one claim", Check, "test:gemini")
            return client, answer, usage

        client, answer, usage = asyncio.run(work())
        self.assertEqual(answer.status, "supported")
        self.assertEqual(usage["totalTokenCount"], 17)
        self.assertIn("gemini-3.8-flash:generateContent", client.url)
        self.assertEqual(client.kwargs["headers"], {"x-goog-api-key": "fake-gemini-key"})
        self.assertEqual(client.kwargs["json"]["generationConfig"]["responseMimeType"],
                         "application/json")

    def test_mixed_no_auth_sentinel_is_removed_for_hosted_api(self):
        payload = unknown_result(self.app, "test").model_dump(mode="json")
        payload["auth_methods"] = ["none", "api_key", "oauth2"]
        changes = normalise_app_result_payload(payload)
        self.assertEqual(payload["auth_methods"], ["api_key", "oauth2"])
        self.assertTrue(changes)
        self.assertEqual([str(x) for x in AppResult.model_validate(payload).auth_methods],
                         ["api_key", "oauth2"])

    def test_quote_ids_resolve_to_fetched_verbatim_text(self):
        url = "https://docs.example.com/auth"
        other = "https://docs.example.com/pricing"
        page = "The API uses an API key to authenticate every request.\n"
        bank, lookup = quote_bank({url: page, other: "A free trial offers API credentials.\n"})
        self.assertIn("Q1:", bank)
        self.assertIn("Q2:", bank)
        evidence = [Evidence(field="auth_methods", url=url, snippet="Q1")]
        resolve_quote_ids(evidence, lookup)
        self.assertEqual(evidence[0].snippet, page.strip())
        result = unknown_result(self.app, "test")
        result.auth_methods = ["api_key"]
        result.evidence = evidence
        checked, invalid = validate_evidence(result, {url: page})
        self.assertEqual(invalid, [])
        self.assertEqual(checked.evidence[0].snippet, page.strip())
        second = [Evidence(field="self_serve", url=url, snippet="Q2")]
        resolve_quote_ids(second, lookup)
        self.assertEqual(second[0].url, other)


if __name__ == "__main__":
    unittest.main()
