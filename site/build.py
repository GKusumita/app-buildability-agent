"""Build a single static report, showing pending stages honestly."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402
from schema import ROOT, load_apps  # noqa: E402

load_dotenv(ROOT / ".env")


def read_json(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def main() -> None:
    final = read_json(ROOT / "data" / "pass3.json")
    accuracy = read_json(ROOT / "data" / "accuracy.json")
    patterns = read_json(ROOT / "data" / "patterns.json")
    queue = read_json(ROOT / "data" / "human_queue.json")
    delivery = read_json(ROOT / "data" / "composio_delivery.json")
    apps = load_apps()
    rows = {row["result"]["id"]: row for row in final["records"]} if final else {}
    results = []
    for app in apps:
        if app.id in rows:
            results.append(rows[app.id])
        else:
            results.append({"result": {"id": app.id, "name": app.name,
                                       "category": app.category.value, "hint": app.hint,
                                       "verdict": "pending", "auth_methods": [],
                                       "evidence": [], "confidence": "pending"},
                            "queries": [], "pages": [], "errors": [], "evidence_invalid": []})
    misses = []
    errors_path = ROOT / "data" / "errors.csv"
    if errors_path.exists():
        with errors_path.open(newline="", encoding="utf-8-sig") as handle:
            misses = list(csv.DictReader(handle))
    payload = {
        "status": "complete" if final and len(rows) == len(apps) else "pending",
        "total_apps": len(apps), "verified_apps": len(rows),
        "results": results, "patterns": patterns, "accuracy": accuracy,
        "human_queue": queue["apps"] if queue else [],
        "human_queue_summary": {key: queue[key] for key in ("sample_size", "queued_count", "queue_rate")}
        if queue else None, "misses": misses,
        "repo_url": os.getenv("REPO_URL", ""), "deploy_url": os.getenv("DEPLOY_URL", ""),
        "composio_status": f"delivered {delivery['rows']} rows" if delivery else "optional delivery not run",
    }
    site = ROOT / "site"
    (site / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    encoded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    template = (site / "template.html").read_text(encoding="utf-8")
    (site / "index.html").write_text(template.replace("__DATA_JSON__", encoded), encoding="utf-8")
    print(f"Built {site / 'index.html'}: {len(rows)}/{len(apps)} verified")


if __name__ == "__main__":
    main()
