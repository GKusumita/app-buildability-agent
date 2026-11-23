"""Score immutable passes against human-authored gold.csv only."""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

from schema import APIType, AppResult, Auth, Blocker, ROOT, SelfServe, Tri, Verdict
from pipeline.common import read_pass, write_immutable

FIELDS = ["auth_methods", "self_serve", "app_review_required", "api_type",
          "official_mcp", "verdict", "blocker"]
ALLOWED = {
    "auth_methods": {item.value for item in Auth},
    "self_serve": {item.value for item in SelfServe},
    "app_review_required": {item.value for item in Tri},
    "api_type": {item.value for item in APIType},
    "official_mcp": {"exists", "not_exists", "unknown"},
    "verdict": {item.value for item in Verdict},
    "blocker": {item.value for item in Blocker},
}


def label_issues(rows: list[dict]) -> list[str]:
    """Reject incomplete or out-of-schema human labels before scoring."""
    issues = []
    for row in rows:
        for field in FIELDS:
            value = (row.get(field) or "").strip()
            if not value:
                issues.append(f"{row['name']}: {field} is blank")
                continue
            values = [part.strip() for part in value.split("|")] if field in {"auth_methods", "api_type"} else [value]
            if any(part not in ALLOWED[field] for part in values):
                issues.append(f"{row['name']}: {field} is outside its closed values")
    return issues


def normalize(field: str, value: object) -> object:
    if field in {"auth_methods", "api_type"}:
        if isinstance(value, list):
            return frozenset(str(item) for item in value)
        return frozenset(part.strip() for part in str(value).split("|") if part.strip())
    if field == "official_mcp":
        if value in {"none", "not_exists", "no"}:
            return "not_exists"
        if value == "unknown":
            return "unknown"
        return "exists"
    return str(value)


def main() -> None:
    gold_path = ROOT / "gold" / "gold.csv"
    if not gold_path.exists():
        raise SystemExit("gold/gold.csv is absent. A human must fill it blind before scoring.")
    with gold_path.open(newline="", encoding="utf-8-sig") as handle:
        gold = list(csv.DictReader(handle))
    if len(gold) != 25 or len({row["id"] for row in gold}) != 25:
        raise SystemExit("gold.csv must contain 25 unique labelled apps")
    issues = label_issues(gold)
    if issues:
        raise SystemExit("gold.csv needs human correction before scoring:\n" + "\n".join(issues[:25]))
    metrics = {}
    misses = []
    for stage in ("pass1", "pass2", "pass3"):
        final = ROOT / "data" / "pass3_final.json"
        path = final if stage == "pass3" and final.exists() else ROOT / "data" / f"{stage}.json"
        if not path.exists():
            raise SystemExit(f"Missing full-run output: {path}")
        records = {str(record["result"]["id"]): AppResult.model_validate(record["result"])
                   for record in read_pass(path)["records"]}
        counts = Counter()
        matrix: dict[str, Counter] = defaultdict(Counter)
        hits = []
        for truth in gold:
            if truth["id"] not in records:
                raise SystemExit(f"{stage} is missing gold app {truth['id']}")
            prediction = records[truth["id"]]
            app_correct = True
            for field in FIELDS:
                actual = normalize(field, truth[field])
                predicted = normalize(field, getattr(prediction, field))
                correct = actual == predicted
                app_correct &= correct
                counts[field] += int(correct)
                if not correct:
                    misses.append({"pass": stage, "id": truth["id"], "name": truth["name"],
                                   "field": field, "gold": "|".join(sorted(actual)) if isinstance(actual, frozenset) else actual,
                                   "prediction": "|".join(sorted(predicted)) if isinstance(predicted, frozenset) else predicted,
                                   "cause": ""})
            matrix[str(truth["verdict"])][prediction.verdict.value] += 1
            if app_correct:
                hits.append(truth["name"])
        metrics[stage] = {
            "n": len(gold), "per_field": {field: {"correct": counts[field], "total": len(gold),
                                           "percent": round(100 * counts[field] / len(gold), 1)} for field in FIELDS},
            "overall": {"correct": sum(counts.values()), "total": len(gold) * len(FIELDS),
                        "percent": round(100 * sum(counts.values()) / (len(gold) * len(FIELDS)), 1)},
            "verdict_accuracy": {"correct": counts["verdict"], "total": len(gold),
                                 "percent": round(100 * counts["verdict"] / len(gold), 1)},
            "verdict_confusion": {key: dict(value) for key, value in matrix.items()},
            "all_fields_correct_apps": hits,
        }
    output = ROOT / "data" / "accuracy.json"
    errors_path = ROOT / "data" / "errors.csv"
    if errors_path.exists():
        raise SystemExit("Refusing to overwrite human error causes in data/errors.csv")
    write_immutable(output, {"gold_n": len(gold), "small_sample_warning": "25 human-labelled apps; percentages are descriptive, not a population estimate.",
                             "passes": metrics})
    with errors_path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["pass", "id", "name", "field", "gold", "prediction", "cause"])
        writer.writeheader()
        writer.writerows(misses)
    print(f"Wrote accuracy for 25 human-labelled apps and {len(misses)} misses with blank human cause fields")


if __name__ == "__main__":
    main()
