"""Create an immutable, rubric-derived v2 from saved verifier decisions."""
from __future__ import annotations

import re

from schema import AppResult, ROOT, Verdict
from pipeline.common import pass_payload, read_pass, write_immutable


DERIVED = {
    ("buildable_with_outreach", "app_review"): "G-REVIEW",
    ("buildable_now", "none"): "G-NOW",
    ("blocked", "no_public_api"): "G-NOAPI",
}


def decision_status(log: dict, field: str) -> str:
    decision = next(item for item in log["decisions"] if item["field"] == field)
    return (decision["retry"] or decision["initial"])["status"]


def reason_code(log: dict, record: dict) -> str:
    issue = log.get("consistency") or ""
    if "invalid while self_serve or auth_methods is unknown" in issue:
        return "G-UNKNOWN"
    if "lacks known public API, self-serve access, and review status" in issue:
        return "G-INPUT"
    if any("503 Service Unavailable" in error or "429 Too Many Requests" in error
           for error in record.get("errors", [])):
        return "V-PROVIDER"
    for field, code in (("auth_methods", "V-AUTH"), ("self_serve", "V-ACCESS"),
                        ("api_type", "V-API")):
        if decision_status(log, field) != "supported":
            return code
    if decision_status(log, "app_review_required") != "supported":
        return "V-REVIEW"
    return "V-VERDICT"


def revise(records: list[dict], logs: dict[int, dict], retry: dict, retry_log: dict) -> list[dict]:
    updated = []
    for source in records:
        app_id = source["result"]["id"]
        row = (retry if app_id == 57 else source).copy()
        row["result"] = row["result"].copy()
        result = row["result"]
        if result["official_mcp"] == "unknown":
            result["official_mcp"] = "unconfirmed"
        if source["result"]["verdict"] == Verdict.UNIDENTIFIED.value:
            log = retry_log if app_id == 57 else logs[app_id]
            match = re.search(r"Rubric derives ([a-z_]+)/([a-z_]+) from other fields", log.get("consistency") or "")
            derived = (match.group(1), match.group(2)) if match else None
            supported = all(decision_status(log, field) == "supported"
                            for field in ("auth_methods", "self_serve", "api_type"))
            if derived in DERIVED and supported:
                result["verdict"], result["blocker"] = derived
                result["blocker_note"] = ("" if derived[1] == "none" else
                                          "Rubric-derived from verifier-supported fields; review queued.")
                row["reason_code"] = DERIVED[derived]
            elif result["verdict"] == Verdict.UNIDENTIFIED.value:
                result["verdict"] = Verdict.UNRESOLVED.value
                result["blocker"] = "none"
                result["blocker_note"] = ""
                row["reason_code"] = reason_code(log, row)
            else:
                row["reason_code"] = "BRIGHT57-RETRY"
        AppResult.model_validate(result)
        updated.append(row)
    return updated


def main() -> None:
    data = ROOT / "data"
    source = read_pass(data / "pass3_final.json")
    logs = {item["app_id"]: item for item in read_pass(data / "verifier_log_final.json")["decisions"]}
    retry_rows = read_pass(data / "pass3_app_57_bright57_v2.json")["records"]
    retry_logs = read_pass(data / "verifier_log_app_57_bright57_v2.json")["decisions"]
    if len(source["records"]) != 100 or len(retry_rows) != 1 or len(retry_logs) != 1 \
            or retry_rows[0]["result"]["id"] != 57 or retry_logs[0]["app_id"] != 57:
        raise SystemExit("Full pass or Bright Data retry is incomplete")
    records = revise(source["records"], logs, retry_rows[0], retry_logs[0])
    output = pass_payload("pass3_final_v2", records)
    output["derived_from"] = "data/pass3_final.json"
    output["bright_data_retry"] = "data/pass3_app_57_bright57_v2.json"
    write_immutable(data / "pass3_final_v2.json", output)
    print(f"Wrote {len(records)} v2 rows")


if __name__ == "__main__":
    main()
