"""Create the blind human-label template; never creates gold.csv."""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schema import load_apps  # noqa: E402

# Original proposed set needed two swaps to get >=2 apps in each category.
# Replace Otter AI with Intercom and Plaid with Vercel.
NAMES = [
    "Meta Ads", "Google Ads", "Amazon Selling Partner", "LinkedIn Ads",
    "Threads (Meta)", "WhatsApp Business", "PitchBook", "DealCloud",
    "NotebookLM", "iPayX", "fanbasis", "Salesforce", "Zendesk", "Slack",
    "Twilio", "Shopify", "Ahrefs", "Sherlock", "GitHub", "Stripe",
    "Notion", "Linear", "Intercom", "Vercel", "Grain",
]
FIELDS = ["id", "name", "category", "auth_methods", "self_serve",
          "app_review_required", "api_type", "official_mcp", "verdict", "blocker"]


def main() -> None:
    by_name = {app.name: app for app in load_apps()}
    chosen = [by_name[name] for name in NAMES]
    counts = Counter(app.category for app in chosen)
    if len(chosen) != 25 or len(counts) != 10 or min(counts.values()) < 2:
        raise ValueError("Gold set must have 25 apps and >=2 from each category")
    output = Path(__file__).with_name("gold_template.csv")
    with output.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for app in chosen:
            writer.writerow({"id": app.id, "name": app.name, "category": app.category.value})
    print(f"Created {output}; all 10 categories have at least two apps")


if __name__ == "__main__":
    main()
