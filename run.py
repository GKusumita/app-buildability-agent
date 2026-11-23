"""Single-app trigger: baseline, grounded research, then independent verification."""
from __future__ import annotations

import argparse
import asyncio
import sys

from pipeline import pass1_baseline, pass2_research, pass3_verify
from pipeline.common import path_for
from schema import load_apps


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True, help="Exact app name from apps.csv")
    args = parser.parse_args()
    matches = [app for app in load_apps() if app.name.casefold() == args.app.casefold()]
    if len(matches) != 1:
        raise SystemExit(f"Unknown app: {args.app}")
    app = matches[0]
    sys.argv = ["run.py", "--app", app.name]
    for stage, runner in (("pass1", pass1_baseline.run), ("pass2", pass2_research.run),
                          ("pass3", pass3_verify.run)):
        if path_for(stage, False, app).exists():
            print(f"Keeping existing immutable {stage} output for {app.name}")
        else:
            asyncio.run(runner())
    print(f"Done: data/pass3_app_{app.id}.json")


if __name__ == "__main__":
    main()
