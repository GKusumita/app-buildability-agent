# App Buildability Atlas

A Python 3.11 research pipeline for the 100 apps in `apps.csv`. It separates a no-retrieval baseline, grounded research, independent verification, and blind human scoring. A static page presents the results without claiming accuracy before the gold labels exist.

## Current state

The implementation is complete locally. The live API passes, human gold labels, and Composio delivery require the configured accounts described below. The [public preview](https://gkusumita.github.io/app-buildability-agent/) currently says **0/100 verified**. Do not present that preview as a completed research result. Source is at [GKusumita/app-buildability-agent](https://github.com/GKusumita/app-buildability-agent).

## Prerequisites and setup

- Python 3.11, an OpenRouter **or** OpenAI API key, and a Tavily API key.
- Optional: a connected Google Sheets account in Composio, a target spreadsheet ID, and GitHub Pages for publication.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill `OPENROUTER_API_KEY` **or** `OPENAI_API_KEY`, plus `TAVILY_API_KEY`, in `.env`. OpenRouter takes precedence if both are present. Do not commit `.env`. The defaults use `gpt-4.1-mini` for answering and a different model, `gpt-4.1`, for verification. With OpenRouter, unprefixed `gpt-*` names are mapped to `openai/gpt-*`; other provider/model slugs are passed through. Both routes use temperature 0 and strict JSON-schema output. OpenRouter also requires a provider endpoint that supports all supplied parameters. If the defaults are unavailable, set `OPENAI_MODEL` and `OPENAI_VERIFY_MODEL` to available structured-output models. Every model call logs the prompt SHA-256, provider, model, token usage, and error to `logs/llm.jsonl`. See [OpenRouter structured outputs](https://openrouter.ai/blog/tutorials/structured-output-llm/) and the [OpenAI Responses schema guide](https://developers.openai.com/api/docs/guides/structured-outputs).

## Run the stages

Run the ten-app development checkpoint first. Its files end in `_sample_dev10.json` and never overwrite the full runs.

```powershell
python -m pipeline.pass1_baseline --sample
python -m pipeline.pass2_research --sample
python -m pipeline.pass3_verify --sample
```

Inspect `data/pass2_sample_dev10.json`, `data/pass3_sample_dev10.json`, and `data/human_queue_sample_dev10.json` for **Pipedrive, Mailchimp, Firecrawl, Vercel, Asana, Pinterest, Gladly, Mermaid CLI, Airtable, and Brex**. The queue reports research failures and verifier rejections separately, with the sample queue rate. Pass 3 computes confidence from verifier results and unknown-field counts. The rubric's no-auth open-source CLI rule is applied in code, and a buildable-now verdict is rejected if auth or self-serve access is unknown. Review the checkpoint before starting the full run.

The latest local checkpoint and its two review reasons are summarized in [SAMPLE_REVIEW.md](SAMPLE_REVIEW.md). Its immutable files use the `dev10_retry2` tag; sample JSON is intentionally ignored by Git because it includes full research traces.

```powershell
python -m pipeline.pass1_baseline
python -m pipeline.pass2_research
python -m pipeline.pass3_verify
python -m pipeline.analyze
python site/build.py
```

Optional delivery after pass 3: install `requirements-composio.txt`, connect a Google Sheets account in Composio, set `COMPOSIO_API_KEY`, `COMPOSIO_CONNECTED_ACCOUNT_ID`, and `COMPOSIO_SHEET_ID` in `.env`, then run `python -m pipeline.deliver_composio`. This uses the documented [Composio Python SDK proxy](https://docs.composio.dev/reference/sdk-reference/python/tools) to call the [Google Sheets values update API](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/update). It writes A1:Q101 on the spreadsheet's first tab, so use a dedicated sheet. This optional path has not been live-tested without a connected account.

Each pass output is immutable. The program refuses to overwrite `data/pass1.json`, `data/pass2.json`, or `data/pass3.json`. Back up and deliberately remove a pass file if a new run is intended; keep the original for the improvement comparison. Cached Tavily searches and extracts live under `cache/`, with extracted pages keyed by URL hash. A rerun reuses those results. Pass 2 stores queries, fetched URLs, token usage, and errors per app. Pass 3 adds `data/verifier_log.json` and `data/human_queue.json`.

To rerun the ten-app checkpoint without overwriting its first result, set `APP_RESEARCH_RUN_TAG=dev10_retry1` for each command. The output becomes, for example, `data/pass1_sample_dev10_retry1.json`.
For a new verifier revision against unchanged research output, set `APP_RESEARCH_SOURCE_TAG=dev10` and a new `APP_RESEARCH_RUN_TAG=dev10_verify2` while running pass 3.

Run a single app through all three passes with:

```powershell
python run.py --app "Pipedrive"
```

The single-app outputs use that app's ID in the filenames; existing files are preserved.

## Blind gold scoring

`gold/gold_template.csv` contains 25 app identities and empty label fields. A human must read real docs and fill a copy named `gold/gold.csv` **before looking at the agent outputs**. Use `|` to separate multiple `auth_methods` or `api_type` values; enter `exists` or `not_exists` for `official_mcp`. This project never generates labels. Two proposed apps were swapped to meet the minimum of two per category: **Otter AI → Intercom** and **Plaid → Vercel**. All 10 categories now have at least two apps.

After the three full passes and human labels exist:

```powershell
python -m pipeline.score
```

This writes `data/accuracy.json` with raw counts, percentages, and a verdict confusion matrix. `data/errors.csv` lists every miss with an empty `cause` column for a human to classify (stale docs, ambiguous docs, model misread, wrong page, rubric edge case). Fill causes before rebuilding the site. The score command refuses to run without the human gold file.

## Site and publication

`python site/build.py` writes `site/index.html` and `site/results.json`. Open the page through a static HTTP server, for example:

```powershell
python -m http.server 8000 --directory site
```

The page embeds the same results as JSON, supports filtering and sorting, links cited evidence, and shows pending sections where inputs are missing. A GitHub Pages workflow builds and publishes `site/` on pushes to `main` or manual dispatch. Create a GitHub repository, set **Settings → Pages → Source → GitHub Actions**, and push the code plus generated final `data/*.json` and human `data/errors.csv` (without `.env`, cache, logs, or `gold.csv`). Set `REPO_URL` and `DEPLOY_URL` in `.env` for local builds if desired. Do not publish a preview as final research.

## Approximate usage, cost, and runtime

For 100 apps, the first grounded pass makes up to **400 basic searches** and **500 page extracts**. At Tavily's published rates, this is roughly **500 credits** before targeted retries; the free Researcher plan currently includes 1,000 monthly credits. Four failed claim checks per app could add up to about 800 more search/extract credits in the worst case. See [Tavily search credits](https://help.tavily.com/articles/6938147944-basic-vs-advanced-search-what-s-the-difference), [extract credits](https://help.tavily.com/articles/8721959612-what-is-the-tavily-extract-api), and [current pricing](https://www.tavily.com/pricing).

At the default models and roughly 1–10k input tokens per call, expect **a few US dollars before retries**, with a rough **$2–$12** range depending on page length and retry rate. This is an estimate, not a measured bill; inspect `logs/llm.jsonl` for actual tokens and the [current OpenRouter model prices](https://openrouter.ai/openai/gpt-4.1-mini). Eight apps run concurrently. Network latency and provider limits dominate runtime; allow **tens of minutes to a few hours** for all passes and review the ten-app checkpoint first.

## What needs a human

- Review the ten grounded sample outputs before the full research run.
- Create blind `gold/gold.csv`, classify error causes, and resolve `data/human_queue.json`.
- Supply a GitHub repository and enable Pages. Composio delivery is optional and only runs when a connected Sheet is configured.

## Checks

```powershell
python -m unittest discover -s tests -v
python -m compileall -q schema.py pipeline site
```

The tests cover the closed schema, verbatim evidence checks, rubric consistency, and Tavily cache reuse. Live provider calls are not mocked into synthetic research results.
