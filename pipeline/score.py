"""Score immutable passes against human-authored gold.csv only."""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

from schema import APIType, AppResult, Auth, Blocker, ROOT, SelfServe, Tri, Verdict
from pipeline.common import read_pass, write_immutable

FIELDS = ["auth_methods", "self_serve", "app_review_required", "api_type",
          "official_mcp", "verdict", "blocker"]
TUNED_APPS = frozenset({"DealCloud", "Sherlock", "Vercel", "Notion", "Stripe", "Meta Ads"})
PASSES = {"pass1": "pass1.json", "pass2": "pass2.json",
          "pass3": "pass3_final.json", "pass3_v2": "pass3_final_v2.json"}
ALLOWED = {
    "auth_methods": {item.value for item in Auth},
    "self_serve": {item.value for item in SelfServe},
    "app_review_required": {item.value for item in Tri},
    "api_type": {item.value for item in APIType},
    "official_mcp": {"exists", "not_exists", "unknown"},
    "verdict": {item.value for item in Verdict},
    "blocker": {item.value for item in Blocker},
}


def label_issues(rows: list[dict], *, allow_blank: bool = False) -> list[str]:
    """Report invalid human labels; optionally leave blank fields unscored."""
    issues = []
    for row in rows:
        for field in FIELDS:
            value = (row.get(field) or "").strip()
            if not value:
                if not allow_blank:
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
        if value in {"unknown", "unconfirmed"}:
            return "unconfirmed"
        if value in {"none", "exists", "not_exists"}:
            return value
        return "exists"
    return str(value)


def exclude_tuned(rows: list[dict]) -> list[dict]:
    tuned = {name.casefold() for name in TUNED_APPS}
    return [row for row in rows if row["name"].casefold() not in tuned]


def valid_label(field: str, value: str) -> bool:
    parts = [part.strip() for part in value.split("|")] if field in {"auth_methods", "api_type"} else [value]
    return bool(value) and all(part in ALLOWED[field] for part in parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", type=Path, default=ROOT / "gold" / "gold.csv")
    args = parser.parse_args()
    gold_path = args.gold
    if not gold_path.exists():
        raise SystemExit(f"Human gold labels are absent: {gold_path}")
    with gold_path.open(newline="", encoding="utf-8-sig") as handle:
        gold = list(csv.DictReader(handle))
    if not 1 <= len(gold) <= 25 or len({row["id"] for row in gold}) != len(gold):
        raise SystemExit("gold.csv must contain 1 to 25 unique apps")
    gold = exclude_tuned(gold)
    gold = [row for row in gold if any((row.get(field) or "").strip() for field in FIELDS)]
    if not gold:
        raise SystemExit("Gold file has no eligible filled labels to score")
    skipped_invalid = {field: sum(bool((row.get(field) or "").strip())
                                  and not valid_label(field, (row.get(field) or "").strip())
                                  for row in gold) for field in FIELDS}
    metrics = {}
    misses = []
    for stage, filename in PASSES.items():
        path = ROOT / "data" / filename
        if not path.exists():
            raise SystemExit(f"Missing full-run output: {path}")
        records = {str(record["result"]["id"]): AppResult.model_validate(record["result"])
                   for record in read_pass(path)["records"]}
        counts = Counter()
        field_totals = Counter()
        matrix: dict[str, Counter] = defaultdict(Counter)
        hits = []
        for truth in gold:
            if truth["id"] not in records:
                raise SystemExit(f"{stage} is missing gold app {truth['id']}")
            prediction = records[truth["id"]]
            app_correct = all(valid_label(field, (truth.get(field) or "").strip()) for field in FIELDS)
            for field in FIELDS:
                if not valid_label(field, (truth.get(field) or "").strip()):
                    continue
                if field == "official_mcp" and (
                        truth[field] not in {"exists", "not_exists"}
                        or normalize(field, prediction.official_mcp) == "none"):
                    app_correct = False
                    continue
                actual = normalize(field, truth[field])
                predicted = normalize(field, getattr(prediction, field))
                correct = actual == predicted
                app_correct &= correct
                field_totals[field] += 1
                counts[field] += int(correct)
                if not correct:
                    misses.append({"pass": stage, "id": truth["id"], "name": truth["name"],
                                   "field": field, "gold": "|".join(sorted(actual)) if isinstance(actual, frozenset) else actual,
                                   "prediction": "|".join(sorted(predicted)) if isinstance(predicted, frozenset) else predicted,
                                   "cause": ""})
            if valid_label("verdict", (truth.get("verdict") or "").strip()):
                matrix[str(truth["verdict"])][prediction.verdict.value] += 1
            if app_correct:
                hits.append(truth["name"])
        total_labels = sum(field_totals.values())
        metrics[stage] = {
            "n": len(gold), "per_field": {field: {"correct": counts[field], "total": field_totals[field],
                                           "percent": round(100 * counts[field] / field_totals[field], 1)
                                           if field_totals[field] else None} for field in FIELDS},
            "overall": {"correct": sum(counts.values()), "total": total_labels,
                        "percent": round(100 * sum(counts.values()) / total_labels, 1)
                        if total_labels else None},
            "verdict_accuracy": {"correct": counts["verdict"], "total": field_totals["verdict"],
                                 "percent": round(100 * counts["verdict"] / field_totals["verdict"], 1)
                                 if field_totals["verdict"] else None},
            "verdict_confusion": {key: dict(value) for key, value in matrix.items()},
            "all_fields_correct_apps": hits,
        }
    output = ROOT / "data" / "accuracy.json"
    errors_path = ROOT / "data" / "errors.csv"
    if errors_path.exists():
        raise SystemExit("Refusing to overwrite human error causes in data/errors.csv")
    write_immutable(output, {"gold_n": len(gold), "skipped_invalid_labels": skipped_invalid,
                             "small_sample_warning": "Partially labelled gold sample; percentages are descriptive, not a population estimate.",
                             "passes": metrics})
    with errors_path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["pass", "id", "name", "field", "gold", "prediction", "cause"])
        writer.writeheader()
        writer.writerows(misses)
    print(f"Wrote accuracy for {len(gold)} eligible apps and {len(misses)} misses")
    print("Skipped invalid filled labels: " + ", ".join(f"{field}={skipped_invalid[field]}" for field in FIELDS))
    for stage, values in metrics.items():
        field_n = ", ".join(f"{field}={values['per_field'][field]['total']}" for field in FIELDS)
        print(f"{stage} field n: {field_n}")


if __name__ == "__main__":
    main()
