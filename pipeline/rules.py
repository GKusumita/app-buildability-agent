"""Deterministic rubric checks applied after model outputs."""
from __future__ import annotations

import re

from schema import APIType, AppInput, AppResult, Auth, Blocker, Evidence, SelfServe, Verdict


def apply_rule2(app: AppInput, result: AppResult, pages: dict[str, str]) -> tuple[AppResult, str | None]:
    """Identify a local open-source CLI from its official repo, not an MCP wrapper."""
    hint = app.hint.split()[0].lower()
    if not hint.startswith("github.com/"):
        return result, None
    repo = hint.removeprefix("github.com/").rstrip("/")
    official = [(url, raw) for url, raw in pages.items()
                if url.lower().startswith("https://github.com/" + repo) and raw.strip()]
    if not official:
        return result, None
    local_cli = app.name.casefold().endswith(" cli") or (
        APIType.CLI in result.api_type and not {APIType.REST, APIType.GRAPHQL} & set(result.api_type))
    if not local_cli:
        return result, None
    proof = None
    for url, raw in official:
        if not re.search(r"\b(?:MIT|Apache|BSD|GPL|ISC) license\b", raw, re.IGNORECASE):
            continue
        for line in raw.splitlines():
            stripped = line.strip()
            if (25 <= len(stripped) <= 300 and
                    not stripped.startswith("[") and
                    re.search(r"\b(?:cli|command.line|command line)\b", stripped, re.IGNORECASE) and
                    re.search(r"\b(?:generat\w*|convert\w*|render\w*|compile\w*|format\w*)\b", stripped, re.IGNORECASE) and
                    not re.search(r"(api key|oauth|access token) required", stripped, re.IGNORECASE)):
                proof = (url, stripped)
                break
        if proof:
            break
    if not proof:
        return result, None
    copy = result.model_copy(deep=True)
    copy.auth_methods = [Auth.NONE]
    copy.self_serve = SelfServe.NA
    copy.api_type = [APIType.CLI]
    copy.verdict = Verdict.NA
    copy.blocker = Blocker.NONE
    copy.blocker_note = ""
    copy.evidence = [entry for entry in copy.evidence
                     if entry.field.value not in {"auth_methods", "self_serve", "api_type", "verdict"}]
    copy.evidence.extend(Evidence(field=field, url=proof[0], snippet=proof[1])
                         for field in ("auth_methods", "self_serve", "api_type", "verdict"))
    return copy, "rubric_rule_2: official repository documents a local CLI; no hosted credentials apply"
