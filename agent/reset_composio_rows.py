#!/usr/bin/env python3
"""
One-off migration: reset every Composio-sourced row in output/results.json
so the next research.py run re-fetches it with the evidence_url /
0-tools-contradiction fix applied. Composio lookups don't hit the LLM, so
re-running all ~47 of these is fast and cheap.

Usage: python3 agent/reset_composio_rows.py
"""
import json
from pathlib import Path

RESULTS_PATH = Path(__file__).resolve().parent.parent / "output" / "results.json"

results = json.loads(RESULTS_PATH.read_text())
reset_count = 0

RESEARCH_FIELDS = (
    "auth_method", "self_serve_or_gated", "api_surface", "has_mcp",
    "buildability_verdict", "blocker", "evidence_url", "confidence",
)

for row in results:
    if row.get("researched_via") == "composio":
        for field in RESEARCH_FIELDS:
            row[field] = None
        reset_count += 1

RESULTS_PATH.write_text(json.dumps(results, indent=2) + "\n")
print(f"Reset {reset_count} Composio-sourced rows. Re-run research.py to backfill them with the fix.")