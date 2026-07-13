# composio_assignment

This repository contains the Composio audit tooling used to research 100 apps, analyze patterns, and run a two-pass verification workflow.

## Quick Start

- Run research to populate `output/results.json` from `data/apps.json`.
- Create a human review using `verify.py sample`, hand-fill verdicts, then `verify.py score` to compute accuracy.

**Models & tools used during development**: Claude Code Sonnet 5 (medium), ChatGPT Codex, Composio MCP server. Editor: VS Code.

---

## Pipeline Architecture

The audit pipeline follows a **two-pass dual-source research strategy** with built-in verification:

```
[ Start: 100 Target Apps ]
           │
           ▼
[ Is App in Composio SDK Catalog? ]
      │                   │
      ├─ YES ─────────────┼─ NO ─────────────┐
      │                   │                  │
[ Native Extraction ]     │      [ Web Search Fallback ]
- Auth Method             │      - DuckDuckGo Search
- MCP Status              │      - Scrape API Docs
- Tool Count              │      - LLM (gpt-4o-mini) Extraction
      │                   │                  │
      └─────────┬─────────┴──────────────────┘
                │
                ▼
[ Merge to Output: results.json ]
                │
                ▼
[ Verification Pass 1 ]
- Draw random sample (seed=42)
- Human cross-checks live docs
- Calculate Strict Accuracy
                │
                ▼
[ Pattern Analysis: patterns.py ]
- Cluster Auth models
- Map Gated vs. Self-serve
- Identify Blockers
- Flag Easy Wins vs Outreach
                │
                ▼
[ Verification Pass 2 (Optional) ]
- Re-sample same apps
- Measure accuracy delta
- Report improvement
                │
                ▼
[ Output: Detailed HTML Dashboard ]
```

### Pipeline Strategy

**Phase 1: Research (`research.py`)**
- **Composio-First**: For each app, query the Composio SDK catalog by slug and name variants
- **Fallback to Web**: If not in Composio, search for API docs and extract via LLM
- **Incremental Progress**: Results flushed after every app so crashes don't lose progress
- **Output**: `results.json` with research fields: `auth_method`, `self_serve_or_gated`, `api_surface`, `has_mcp`, `buildability_verdict`, `blocker`, `evidence_url`, `confidence`

**Phase 2: Verification (`verify.py`)**
- **Sampling**: Reproducible random sample (seed=42) of N apps from results
- **Human Review**: Open evidence URLs, cross-check against real documentation
- **Scoring**: Compute strict accuracy (unsure = wrong) and lenient accuracy (exclude unsure)
- **Delta Analysis**: Compare pass-1 vs pass-2 to measure research pipeline improvement

**Phase 3: Analysis (`pattern.py`)**
- **Auth Distribution**: Normalize and cluster authentication methods (OAuth2, API Key, etc.)
- **Access Models**: Categorize by self-serve vs gated + measure by app category
- **Blockers**: Identify most common obstacles to integration
- **Easy Wins**: Flag apps that are self-serve, MCP-enabled, and unblocked
- **Needs Outreach**: Flag gated/blocked apps that need business negotiation

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
- `requests` — HTTP calls to Composio catalog and web pages
- `python-dotenv` — load `.env` credentials
- `beautifulsoup4` — HTML parsing for API docs extraction
- `openai` — LLM client (gpt-4.1-mini) used by research pipeline
- `ddgs` or `duckduckgo_search` — lightweight web search fallback for research
- `lxml` — faster HTML parsing (optional but recommended)
- `rich` — enhanced CLI output (optional)

## Environment (.env)

Create a `.env` file in the repository root (do NOT commit secrets). Use `.env.example` as a starting point.

- `COMPOSIO_API_KEY` — API key to query the Composio toolkit catalog (required by `research.py`)
- `OPENAI_API_KEY` — API key for OpenAI-compatible client used by the pipeline (required by `research.py`)
- `OPENAI_MODEL` — optional: model to use (default in code: `gpt-4.1-mini`)
- `GITHUB_TOKEN` — optional token if you want to push from CI or script

Example `.env` (see `.env.example`):

```
COMPOSIO_API_KEY=sk_...
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1-mini
GITHUB_TOKEN=
```

> **Note**: The repo code expects `COMPOSIO_API_KEY` and `OPENAI_API_KEY` to be present when running `research.py`.

## File Structure

- `agent/` — Core Python agents and pipeline scripts
  - `agent/research.py` — Main research pipeline (Composio catalog + web search fallback → `output/results.json`)
  - `agent/verify.py` — Sampling and scoring CLI (sample → score → compare)
  - `agent/pattern.py` — Pattern analysis utilities (auth distribution, blockers, easy wins)
  - `agent/check.py` — Lightweight consistency checks (development utility)
- `data/` — Input app list and initial seeds
  - `data/apps.json` — 100-app list used as input for research
- `output/` — Generated outputs and report artifacts
  - `output/results_seed.json` — Starting seed claims (optional pre-population)
  - `output/results.json` — Research pipeline output (all 100 apps + research fields)
  - `output/patterns.json` — Pattern analysis results
  - `output/verification_pass1_template.json` — Human review template (before filling)
  - `output/verification_pass1_scored.json` — Scored verification results + accuracy
  - `output/verification_pass2_template.json` — Optional second pass template
  - `output/verification_pass2_scored.json` — Optional second pass scores + delta
  - `output/comparison_pass1_vs_pass2.json` — Improvement metrics (if two passes run)
  - `index.html` — HTML dashboard (generated from analysis)

---

## How to Run (Recommended Order)

### 1. Setup
```bash
# Activate your Python environment and install requirements
cd composio-audit
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Create .env with required keys
# COMPOSIO_API_KEY=...
# OPENAI_API_KEY=...
```

### 2. Research Phase
```bash
# Populate output/results.json (reads data/apps.json and output/results_seed.json)
python3 agent/research.py
# Output: 100 apps researched via Composio catalog or web search
# Progress shown every 10 apps with source breakdown (Composio vs web)
```

### 3. Pattern Analysis (Optional but Recommended)
```bash
# Generate insights from raw results
python3 agent/pattern.py
# Output: output/patterns.json with auth distribution, blockers, easy wins, etc.
```

### 4. Verification Pass 1
```bash
# Sample 18 apps at random (seed=42, reproducible)
python3 agent/verify.py sample --out output/verification_pass1_template.json --n 18 --seed 42

# Manually open each evidence_url and fill in verdict blocks:
# - For each field (auth_method, self_serve_or_gated, api_surface, has_mcp, buildability_verdict, blocker, evidence_url)
# - Mark verdict as: "correct", "incorrect", or "unsure"
# - Add one-line correction notes in verdict_notes when marking incorrect
# Output: output/verification_pass1_template.json (hand-filled)

# Score the filled template
python3 agent/verify.py score --in output/verification_pass1_template.json --out output/verification_pass1_scored.json
# Output: accuracy metrics (strict + lenient), per-app scores, and list of misses
```

### 5. Optional: Verification Pass 2 (Measure Improvement)
```bash
# Re-sample the same 18 app IDs for a second pass
python3 agent/verify.py sample --n 18 --seed 42 --ids-from output/verification_pass1_scored.json \
    --out output/verification_pass2_template.json

# Hand-fill pass 2 template (same process as pass 1)

# Score pass 2
python3 agent/verify.py score --in output/verification_pass2_template.json \
    --out output/verification_pass2_scored.json

# Compare pass 1 vs pass 2
python3 agent/verify.py compare --pass1 output/verification_pass1_scored.json \
    --pass2 output/verification_pass2_scored.json --out output/comparison_pass1_vs_pass2.json
# Output: accuracy delta, improved/regressed/unchanged app list
```

---

## Pipeline Quality Checks

### ✅ Data Integrity
- **Atomic JSON writes**: All JSON outputs use atomic file operations (temp file → rename) to prevent data loss on crash
- **Incremental progress**: `research.py` saves after each app, so re-running resumes where it left off
- **Null field tracking**: Research fields are explicitly tracked; null = "not yet researched"

### ✅ Research Accuracy
- **Dual sourcing**: Composio catalog (ground truth) checked first; web search only as fallback
- **LLM-assisted extraction**: Web pages extracted via gpt-4.1-mini with structured JSON schema
- **Confidence rating**: Each row includes confidence (high/medium/low) based on evidence quality
- **Error tracking**: Research errors logged and distinguish from app-side blockers

### ✅ Verification Rigor
- **Reproducible sampling**: Fixed seed (42) ensures same apps for pass 1 and pass 2
- **Honest scoring**: All misses recorded honestly; unsure is distinct from incorrect
- **Dual metrics**: Strict accuracy (unsure = wrong) + lenient (exclude unsure) both reported
- **Per-field analysis**: Worst-performing fields highlighted so research focus can be targeted

### ✅ Pattern Analysis
- **Category breakdown**: Auth and gating distributions computed per app category
- **Normalization**: Auth methods collapsed into comparable buckets (OAuth2, API Key, etc.)
- **Actionable insights**: "Easy wins" (ready to integrate) vs "needs outreach" (gated) clearly listed
- **Data quality caveats**: Errored and low-confidence rows excluded from pattern stats and noted separately

---

## Notes & Troubleshooting

### DuckDuckGo Search Package
If `research.py` raises a `RuntimeError` about missing DuckDuckGo search packages:

```bash
pip install ddgs
# or (older frozen package)
pip install duckduckgo_search
```

### OpenAI API Issues
- Check `OPENAI_API_KEY` and `OPENAI_MODEL` in `.env`
- Verify the model name is valid (e.g., `gpt-4.1-mini` or `gpt-4o-mini`)
- Check OpenAI account has quota remaining

### Composio Catalog Lookups
- The research pipeline generates multiple slug candidates (compact, underscored, dashed) to improve matching
- If an app isn't found, it falls back to web search (no error)
- The Composio catalog is treated as ground truth when present (MCP = managed integration already live)

### Re-running Research
- Safe to re-run `research.py` — it skips apps with all required fields already populated
- To force a re-research, delete the corresponding row from `output/results.json` or clear a specific field to `null`

### Verification Workflow
- The `sample` command is deterministic (seed=42) — multiple runs produce the same sample
- Use `--ids-from` to re-sample the same apps in pass 2 for meaningful accuracy comparison
- If you skip scoring a field, it's excluded from accuracy (not counted as wrong)

---

## Architecture Highlights

### Clean Separation of Concerns
1. **Research** (`research.py`): Discovers and extracts facts from two sources (Composio + web)
2. **Verification** (`verify.py`): Samples, scores, and compares against human ground truth
3. **Analysis** (`pattern.py`): Clusters results for insights (auth, access models, blockers)

### Robust Error Handling
- Research errors explicitly logged and distinguished from app-side blockers
- Low-confidence rows tracked separately and excluded from pattern stats
- Atomic file writes prevent corruption on failure

### Reproducibility
- Random sampling uses fixed seed (42) for deterministic results
- All research artifacts timestamped and include `researched_via` field (composio|web)
- Comparison workflow enables two-pass accuracy measurement on identical samples

---

## Attribution

This repository was authored for the Composio 100-app audit assignment. The pipeline demonstrates:
- **Dual-source research**: Composio SDK catalog (ground truth) + web search (fallback)
- **LLM-assisted extraction**: Structured document understanding via gpt-4.1-mini
- **Rigorous verification**: Human-in-the-loop sampling and accuracy scoring
- **Pattern discovery**: Auth clustering, access model categorization, and blocker identification

For questions, open an issue or contact the repo owner.
