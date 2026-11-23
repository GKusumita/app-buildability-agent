"""No-retrieval baseline; one structured model call per app."""
from __future__ import annotations

import asyncio

import httpx

from schema import AppResult, Confidence, check_identity, unknown_result
from pipeline.common import pass_payload, path_for, require_llm_key, result_record, select_apps, write_immutable
from pipeline.llm import model_for, rubric_text, structured_call


async def run() -> None:
    apps, sample = select_apps()
    require_llm_key()
    output = path_for("pass1", sample, apps[0] if len(apps) == 1 else None)
    if output.exists():
        raise SystemExit(f"Refusing to overwrite immutable output: {output}")
    semaphore = asyncio.Semaphore(8)
    async with httpx.AsyncClient() as client:
        async def one(app):
            prompt = ("No web or tools. Give a cautious baseline from existing model knowledge. "
                      "Do not claim live verification. Leave evidence empty. Unknown is preferable to guessing. "
                      "For official_mcp use a complete https:// URL only if confident it is the official MCP; "
                      "otherwise use unknown or none. Never copy the hint as a partial URL. "
                      "Keep one_liner under 20 words and notes under 40 words.\n\n"
                      f"App: {app.model_dump_json()}\n\n{rubric_text()}")
            async with semaphore:
                try:
                    result, usage = await structured_call(client, model_for(),
                                                          prompt, AppResult, f"pass1:{app.id}")
                    check_identity(result, app)
                    result.evidence = []
                    result.confidence = Confidence.LOW  # No verifier has run.
                    return result_record(result, usage=usage)
                except Exception as exc:
                    return result_record(unknown_result(app, f"Baseline call failed: {exc}"), errors=[str(exc)])
        records = await asyncio.gather(*(one(app) for app in apps))
    write_immutable(output, pass_payload("pass1_no_retrieval", records))
    print(f"Wrote {len(records)} baseline rows to {output}")


if __name__ == "__main__":
    asyncio.run(run())
