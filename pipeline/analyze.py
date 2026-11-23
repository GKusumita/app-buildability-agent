"""Compute site patterns from final pass3 rows, never from prose."""
from __future__ import annotations

from collections import Counter, defaultdict

from schema import AppResult, ROOT
from pipeline.common import read_pass, write_immutable


def compute(results: list[AppResult]) -> dict:
    total = len(results)
    auth = Counter(method.value for result in results for method in result.auth_methods)
    self_serve = Counter(result.self_serve.value for result in results)
    verdicts = Counter(result.verdict.value for result in results)
    blockers = Counter(result.blocker.value for result in results if result.blocker.value != "none")
    by_category = {}
    for category in sorted({result.category.value for result in results}):
        subset = [result for result in results if result.category.value == category]
        by_category[category] = {
            "total": len(subset),
            "self_serve": dict(Counter(row.self_serve.value for row in subset)),
            "blockers": dict(Counter(row.blocker.value for row in subset if row.blocker.value != "none")),
        }
    oauth = {row.id for row in results if "oauth2" in [method.value for method in row.auth_methods]}
    api_key = {row.id for row in results if "api_key" in [method.value for method in row.auth_methods]}
    easy = [row.name for row in results if row.verdict.value == "buildable_now"
            and row.id in oauth | api_key and row.api_breadth.value in {"broad", "moderate"}]
    outreach: dict[str, list[str]] = defaultdict(list)
    for row in results:
        if row.verdict.value == "buildable_with_outreach":
            outreach[row.blocker.value].append(row.name)
    mcp = [{"name": row.name, "url": row.official_mcp} for row in results
           if row.official_mcp not in {"none", "unknown"}]
    return {
        "total": total, "auth_distribution": dict(auth),
        "oauth2": len(oauth), "api_key": len(api_key), "both": len(oauth & api_key),
        "self_serve": dict(self_serve), "verdicts": dict(verdicts),
        "blockers": dict(blockers), "by_category": by_category,
        "easy_wins": easy, "outreach": dict(outreach), "official_mcp": mcp,
        "unknown_counts": {
            "auth_methods": auth["unknown"],
            "self_serve": self_serve["unknown"],
            "api_type": sum("unknown" in [method.value for method in row.api_type] for row in results),
            "could_not_identify": verdicts["could_not_identify"],
            "not_applicable": verdicts["not_applicable"],
        },
    }


def main() -> None:
    source = ROOT / "data" / "pass3.json"
    if not source.exists():
        raise SystemExit("Run full pass3 first")
    results = [AppResult.model_validate(row["result"]) for row in read_pass(source)["records"]]
    write_immutable(ROOT / "data" / "patterns.json", compute(results))
    print(f"Computed patterns from {len(results)} final rows")


if __name__ == "__main__":
    main()
