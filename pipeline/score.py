"""Score immutable passes against human-authored gold.csv only."""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

from schema import AppResult, ROOT
from pipeline.common import read_pass, write_immutable

FIELDS = ["auth_methods", "self_serve", "app_review_required", "api_type",
          "official_mcp", "verdict", "blocker"]


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
    for row in gold:
        if any(not row.get(field, "").strip() for field in FIELDS):
            raise SystemExit(f"gold.csv has an unlabelled field for {row['name']}")
    metrics = {}
    misses = []
    for stage in ("pass1", "pass2", "pass3"):
        path = ROOT / "data" / f"{stage}.json"
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
