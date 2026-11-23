"""Optional final delivery: write verified rows to a connected Google Sheet."""
from __future__ import annotations

import json
import os
from urllib.parse import quote

from schema import AppResult, ROOT
from pipeline.common import read_pass, require_env, write_immutable

FIELDS = ["id", "name", "category", "one_liner", "auth_methods", "self_serve",
          "app_review_required", "api_type", "api_breadth", "official_mcp",
          "webhooks", "rate_limits", "verdict", "blocker", "blocker_note",
          "confidence", "evidence"]


def main() -> None:
    require_env("COMPOSIO_API_KEY", "COMPOSIO_CONNECTED_ACCOUNT_ID", "COMPOSIO_SHEET_ID")
    source = ROOT / "data" / "pass3.json"
    if not source.exists():
        raise SystemExit("Run the full verified pass before delivery")
    results = [AppResult.model_validate(record["result"]) for record in read_pass(source)["records"]]
    if len(results) != 100:
        raise SystemExit("Delivery requires 100 verified pass3 rows")
    try:
        from composio import Composio
    except ImportError as exc:
        raise SystemExit("Install optional Composio SDK: pip install -r requirements-composio.txt") from exc

    values = [FIELDS]
    for result in results:
        data = result.model_dump(mode="json")
        values.append([json.dumps(data[field], ensure_ascii=False) if isinstance(data[field], list)
                       else str(data[field]) for field in FIELDS])
    sheet_id = os.environ["COMPOSIO_SHEET_ID"]
    endpoint = ("https://sheets.googleapis.com/v4/spreadsheets/"
                + quote(sheet_id, safe="") + "/values/A1%3AQ101?valueInputOption=RAW")
    client = Composio(api_key=os.environ["COMPOSIO_API_KEY"])
    response = client.tools.proxy(
        endpoint=endpoint, method="PUT",
        connected_account_id=os.environ["COMPOSIO_CONNECTED_ACCOUNT_ID"],
        body={"range": "A1:Q101", "majorDimension": "ROWS", "values": values},
    )
    status = getattr(response, "status", None)
    if not isinstance(status, int) or not 200 <= status < 300:
        raise RuntimeError(f"Composio Google Sheets delivery failed: status={status}, response={getattr(response, 'data', None)}")
    write_immutable(ROOT / "data" / "composio_delivery.json",
                    {"status": "delivered", "rows": len(results), "sheet_id": sheet_id,
                     "response_status": status})
    print(f"Delivered {len(results)} rows to connected Google Sheet")


if __name__ == "__main__":
    main()
