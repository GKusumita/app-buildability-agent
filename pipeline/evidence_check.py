"""Check that cited quotes are contained in fetched text; fail closed."""
from __future__ import annotations

import re
from collections import defaultdict

from schema import APIType, AppResult, Auth, Blocker, Confidence, EvidenceField, SelfServe, Tri, Verdict


def normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def validate_evidence(result: AppResult, pages: dict[str, str],
                      source_urls: set[str] | None = None) -> tuple[AppResult, list[str]]:
    """Only exact fetched URLs and whitespace-normalised verbatim substrings count."""
    result = result.model_copy(deep=True)
    invalid: list[str] = []
    valid = []
    for entry in result.evidence:
        if (entry.url not in pages or not entry.snippet.strip()
                or normalise(entry.snippet) not in normalise(pages[entry.url])):
            invalid.append(f"{entry.field.value}: evidence_invalid: {entry.url}")
        else:
            valid.append(entry)
    result.evidence = valid
    fields = defaultdict(list)
    for entry in valid:
        fields[entry.field.value].append(entry)
    claims = {
        "auth_methods": result.auth_methods != [Auth.UNKNOWN],
        "self_serve": result.self_serve != SelfServe.UNKNOWN,
        "api_type": result.api_type != [APIType.UNKNOWN],
        "verdict": result.verdict != Verdict.UNIDENTIFIED,
    }
    for field, claimed in claims.items():
        if claimed and not fields[field]:
            invalid.append(f"{field}: evidence_invalid: no valid citation")
            set_unknown(result, field)
    if source_urls is not None and result.official_mcp not in {"none", "unknown"}:
        if result.official_mcp not in source_urls and not any(result.official_mcp in page for page in pages.values()):
            invalid.append("official_mcp: URL was not returned by search/extract")
            result.official_mcp = "unknown"
    if invalid:
        result.confidence = Confidence.LOW
    return result, invalid


def set_unknown(result: AppResult, field: str) -> None:
    result.confidence = Confidence.LOW
    if field == "auth_methods":
        result.auth_methods = [Auth.UNKNOWN]
    elif field == "self_serve":
        result.self_serve = SelfServe.UNKNOWN
    elif field == "api_type":
        result.api_type = [APIType.UNKNOWN]
    elif field == "verdict":
        result.verdict = Verdict.UNIDENTIFIED
        result.blocker = Blocker.NONE
        result.blocker_note = ""
    elif field == "app_review_required":
        result.app_review_required = Tri.UNKNOWN
    else:
        raise ValueError(field)
    result.evidence = [entry for entry in result.evidence if entry.field.value != field]
