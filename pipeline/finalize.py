"""Merge isolated verifier recoveries and apply final deterministic checks."""
from __future__ import annotations

import argparse

from schema import AppResult, Confidence, ROOT, load_apps
from pipeline.common import pass_payload, read_pass, write_immutable
from pipeline.pass3_verify import compute_confidence, unknown_fields
from pipeline.rules import constrain_official_mcp


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replace-app-id", type=int, action="append", default=[],
                        help="Merge an isolated pass3_app_ID.json verifier recovery")
    args = parser.parse_args()
    if len(args.replace_app_id) != len(set(args.replace_app_id)):
        raise SystemExit("Each replacement app ID may appear only once")
    outputs = [ROOT / "data" / name for name in
               ("pass3_final.json", "verifier_log_final.json", "human_queue_final.json")]
    if any(path.exists() for path in outputs):
        raise SystemExit("Refusing to overwrite immutable finalization outputs")

    apps = {app.id: app for app in load_apps()}
    rows = {record["result"]["id"]: record for record in read_pass(ROOT / "data" / "pass3.json")["records"]}
    logs = {item["app_id"]: item for item in read_pass(ROOT / "data" / "verifier_log.json")["decisions"]}
    queue = {item["id"]: item for item in read_pass(ROOT / "data" / "human_queue.json")["apps"]}
    if set(rows) != set(apps) or set(logs) != set(apps):
        raise SystemExit("Full pass3 records or verifier logs do not match apps.csv")

    for app_id in args.replace_app_id:
        if app_id not in apps:
            raise SystemExit(f"Unknown replacement app ID: {app_id}")
        replacement = read_pass(ROOT / "data" / f"pass3_app_{app_id}.json")["records"]
        decisions = read_pass(ROOT / "data" / f"verifier_log_app_{app_id}.json")["decisions"]
        human = read_pass(ROOT / "data" / f"human_queue_app_{app_id}.json")["apps"]
        if len(replacement) != 1 or replacement[0]["result"]["id"] != app_id \
                or len(decisions) != 1 or decisions[0]["app_id"] != app_id \
                or len(human) > 1 or (human and human[0]["id"] != app_id):
            raise SystemExit(f"Invalid isolated verifier output for app {app_id}")
        rows[app_id] = replacement[0]
        logs[app_id] = decisions[0]
        queue.pop(app_id, None)
        if human:
            queue[app_id] = human[0]

    mcp_rejected = 0
    for app_id, app in apps.items():
        record = rows[app_id]
        result = AppResult.model_validate(record["result"])
        result, issue = constrain_official_mcp(app, result)
        if issue:
            mcp_rejected += 1
            record.setdefault("deterministic_rules", []).append(issue)
        reasons = queue.get(app_id, {})
        research = list(reasons.get("research_failures", []))
        verifier = list(reasons.get("verifier_rejections", []))
        confidence = compute_confidence(result, logs[app_id]["decisions"], research, verifier)
        result.confidence = confidence
        unknown = unknown_fields(result)
        if confidence == Confidence.LOW and not (research or verifier):
            research.append("too many unknown fields or too few supported checks: " + ", ".join(unknown))
        if research or verifier:
            queue[app_id] = {"id": app_id, "name": app.name,
                             "research_failures": research, "verifier_rejections": verifier,
                             "unknown_fields": unknown, "confidence": confidence.value}
        else:
            queue.pop(app_id, None)
        record["result"] = result.model_dump(mode="json")
        record["errors"] = research + verifier
        logs[app_id]["computed_confidence"] = confidence.value
        logs[app_id]["unknown_fields"] = unknown
        if issue:
            logs[app_id]["official_mcp_rule"] = issue

    ordered = list(apps)
    final = pass_payload("pass3_final", [rows[app_id] for app_id in ordered])
    final["derived_from"] = "data/pass3.json"
    final["replaced_app_ids"] = args.replace_app_id
    write_immutable(outputs[0], final)
    write_immutable(outputs[1], {"decisions": [logs[app_id] for app_id in ordered]})
    write_immutable(outputs[2], {"sample_size": len(apps), "queued_count": len(queue),
                                 "queue_rate": round(len(queue) / len(apps), 3),
                                 "apps": [queue[app_id] for app_id in ordered if app_id in queue]})
    print(f"Finalized {len(apps)} rows; {mcp_rejected} MCP candidates rejected; "
          f"{len(queue)} queued for human review")


if __name__ == "__main__":
    main()
