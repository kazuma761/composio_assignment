# composio_assignment

This repository contains the Composio audit tooling used to research 100 apps, analyze patterns, and run a two-pass verification workflow.

**Quick summary**
- Run research to populate `output/results.json` from `data/apps.json`.
- Create a human review using `verify.py sample`, hand-fill verdicts, then `verify.py score` to compute accuracy.

**Models & tools used during development**: Claude Code Sonnet 5 (medium),ChatGPT Codex, Composio MCP server. Editor: VS Code.

---

## Requirements / SDKs

Install Python 3.10+ (3.11 recommended). Install dependencies into a virtualenv:


```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install composio composio-openai-agents openai-agents
```

Required Python packages (see `requirements.txt`):
- `requests` — HTTP calls
- `python-dotenv` — load `.env` credentials
- `beautifulsoup4` — simple HTML extraction
- `openai` — LLM client used by the research pipeline
- `ddgs` or `duckduckgo_search` — lightweight web search fallback used by `research.py`

Optional / helpful tools:
- `lxml` — faster HTML parsing
- `rich` — nicer CLI output

## Environment (.env)

Create a `.env` file in the repository root (do NOT commit secrets). Use `.env.example` as a starting point.

- `COMPOSIO_API_KEY` — API key to query the Composio toolkit catalog (required by `research.py`).
- `OPENAI_API_KEY` — API key for the OpenAI-compatible client used by the pipeline (required by `research.py`).
- `OPENAI_MODEL` — optional: model to use (default in code: `gpt-4.1-mini`).
- `GITHUB_TOKEN` — optional token if you want to push from CI or script.

Example `.env` (see `.env.example`):

```
COMPOSIO_API_KEY=sk_...
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1-mini
GITHUB_TOKEN=
```

> Note: The repo code expects `COMPOSIO_API_KEY` and `OPENAI_API_KEY` to be present when running `research.py`.

## File structure and what each file/folder is

- `agent/` : Core Python agents and pipeline scripts.
  - `agent/research.py` : Main research pipeline. Queries Composio catalog, falls back to web search, extracts claims and writes `output/results.json`.
  - `agent/verify.py` : Sampling and scoring CLI used to create manual review templates and score hand-filled verdicts.
  - `agent/pattern.py` : Pattern analysis utilities.
  - `agent/check.py` : Lightweight consistency checks used during development.
- `data/` : Input app list and initial seeds.
  - `data/apps.json` : App list used as input for research.
- `output/` : Generated outputs and report artifacts.
  - `output/results_seed.json` : Starting seed claims.
  - `output/results.json` : Research pipeline output (claims).
  - `output/verification_*.json` : Templates and scored verification passes.
  - `output/detailed_assignment_report.html` : Human-readable executive report (this file).
- `composio-audit/` : top-level folder for the audit (this repo root).

## How to run (recommended order)

1. Activate your Python environment and install requirements (see above).

2. Create a `.env` with the keys described above.

3. Run the research pipeline (writes `output/results.json`):

```bash
cd composio-audit
python3 agent/research.py
```

It will read `data/apps.json` / `output/results_seed.json` and write incremental results to `output/results.json`. The script requires `COMPOSIO_API_KEY` and `OPENAI_API_KEY` in the environment.

4. Sample apps for manual review (pass 1):

```bash
python3 agent/verify.py sample --out output/verification_pass1_template.json --n 18 --seed 42
```

5. Manually open each `evidence_url` and fill in `verdict` fields in `output/verification_pass1_template.json`.

6. Score the filled template:

```bash
python3 agent/verify.py score --in output/verification_pass1_template.json --out output/verification_pass1_scored.json
```

7. (Optional) Re-sample the same ids for pass 2 and repeat the manual review/score cycle to measure improvement.

## Pushing this repo to GitHub

To push your local repo to `https://github.com/kazuma761/composio_assignment`:

```bash
git remote add origin https://github.com/kazuma761/composio_assignment.git
git branch -M main
git add .
git commit -m "Add research + verification pipeline and report"
# If using HTTPS -> enter username/password or use a personal access token
git push -u origin main
```

If you want to push from CI or script, set `GITHUB_TOKEN` in the environment and use `git push` with `https://$GITHUB_TOKEN@github.com/...` or use the GitHub CLI (`gh auth login`).

## Notes & troubleshooting

- If `research.py` raises a `RuntimeError` about missing DuckDuckGo search packages, install one of:

```bash
pip install ddgs
# or
pip install duckduckgo_search
```

- If OpenAI calls fail, check `OPENAI_API_KEY` and `OPENAI_MODEL` in `.env`.
- `research.py` saves progress after each app so you can re-run it safely.

## Attribution

This repository was authored for the Composio 100-app audit assignment. For questions, open an issue or contact the repo owner.

# composio-audit

Audit tooling for validating Composio app configurations.

## Structure

```
composio-audit/
  data/apps.json        # the 100 apps input
  agent/research.py     # the pipeline
  agent/verify.py       # verification/sampling script
  output/results.json   # raw findings
  output/report.html    # final deliverable
  README.md
```

## Usage

```bash
python agent/research.py
python agent/verify.py
```
