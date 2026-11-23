"""Paths, immutable outputs, and command-line selection."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from schema import AppInput, AppResult, ROOT, load_apps

load_dotenv(ROOT / ".env")
SAMPLE_NAMES = {"Stripe", "Meta Ads", "Sherlock", "DealCloud", "Notion"}


def select_apps(argv: list[str] | None = None) -> tuple[list[AppInput], bool]:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sample", action="store_true", help="Five required checkpoint apps")
    group.add_argument("--app", help="One exact app name")
    args = parser.parse_args(argv)
    apps = load_apps()
    if args.sample:
        apps = [app for app in apps if app.name in SAMPLE_NAMES]
        assert len(apps) == 5
    elif args.app:
        apps = [app for app in apps if app.name.casefold() == args.app.casefold()]
        if len(apps) != 1:
            raise SystemExit(f"App not found: {args.app}")
    return apps, args.sample


def require_env(*names: str) -> None:
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        raise SystemExit("Missing .env values: " + ", ".join(missing))


def write_immutable(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError:
        raise SystemExit(f"Refusing to overwrite immutable output: {path}")


def read_pass(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def pass_payload(stage: str, records: list[dict]) -> dict:
    return {"stage": stage, "created_at": datetime.now(timezone.utc).isoformat(), "records": records}


def result_record(result: AppResult, **metadata: object) -> dict:
    return {"result": result.model_dump(mode="json"), "queries": [], "pages": [],
            "usage": {}, "errors": [], "evidence_invalid": [], **metadata}


def path_for(stage: str, sample: bool, app: AppInput | None = None) -> Path:
    suffix = "_sample" if sample else f"_app_{app.id}" if app else ""
    return ROOT / "data" / f"{stage}{suffix}.json"
