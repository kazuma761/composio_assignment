#!/usr/bin/env python3
"""
Pattern analysis over output/results.json.

The assignment is explicit that raw rows are not the point — clustering and
insight are. This script produces output/patterns.json with:

  - auth method distribution (overall + by category)
  - self-serve vs gated distribution (overall + by category)
  - most common blockers, ranked
  - "easy wins" (self-serve + has_mcp + no blocker) vs "needs outreach"
    (gated or blocked) app lists
  - data quality notes (errored rows, low-confidence rows) so the patterns
    are read with the right caveats attached

Usage: python3 agent/patterns.py
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = ROOT / "output" / "results.json"
PATTERNS_PATH = ROOT / "output" / "patterns.json"


def normalize_auth(auth_method: str | None) -> str:
    """Collapse verbose auth strings ('Attio Oauth', 'Klaviyo Oauth (also API key)')
    into a small set of comparable buckets for clustering."""
    if not auth_method:
        return "unknown"
    a = auth_method.lower()
    has_oauth = "oauth" in a
    has_key = "api key" in a or "api token" in a or "token" in a and "oauth" not in a
    has_basic = "basic" in a
    if has_oauth and (has_key or "also" in a):
        return "OAuth2 + API key"
    if has_oauth:
        return "OAuth2"
    if has_key:
        return "API key / token"
    if has_basic:
        return "Basic auth"
    if a in ("none", "no auth", "no_auth"):
        return "none"
    return "other"


def is_gated(row: dict) -> bool:
    val = (row.get("self_serve_or_gated") or "").lower()
    return "gated" in val


def is_self_serve(row: dict) -> bool:
    val = (row.get("self_serve_or_gated") or "").lower()
    return "self-serve" in val or "self serve" in val


def main() -> None:
    results = json.loads(RESULTS_PATH.read_text())

    errored = [r["name"] for r in results if r.get("research_error")]
    low_confidence = [r["name"] for r in results if r.get("confidence") == "low"]
    clean = [r for r in results if not r.get("research_error")]

    # --- auth method distribution -----------------------------------------
    auth_counts = Counter(normalize_auth(r.get("auth_method")) for r in clean)
    auth_by_category: dict[str, Counter] = defaultdict(Counter)
    for r in clean:
        auth_by_category[r["category"]][normalize_auth(r.get("auth_method"))] += 1

    # --- self-serve vs gated ------------------------------------------------
    gated_apps = [r["name"] for r in clean if is_gated(r)]
    self_serve_apps = [r["name"] for r in clean if is_self_serve(r)]
    unknown_gating = [r["name"] for r in clean if not is_gated(r) and not is_self_serve(r)]

    gating_by_category: dict[str, dict[str, int]] = {}
    for category in sorted(set(r["category"] for r in clean)):
        rows = [r for r in clean if r["category"] == category]
        gating_by_category[category] = {
            "self_serve": sum(1 for r in rows if is_self_serve(r)),
            "gated": sum(1 for r in rows if is_gated(r)),
            "unknown": sum(1 for r in rows if not is_gated(r) and not is_self_serve(r)),
            "total": len(rows),
        }

    # --- blockers -------------------------------------------------------
    blocker_counts = Counter()
    for r in clean:
        b = (r.get("blocker") or "").strip().lower()
        if not b or b == "none":
            continue
        blocker_counts[r.get("blocker")] += 1
    for name in errored:
        blocker_counts["research failed (search/fetch error, not an app-side blocker)"] += 1

    # --- easy wins vs needs outreach -----------------------------------
    easy_wins = [
        r["name"] for r in clean
        if is_self_serve(r) and r.get("has_mcp") and (not r.get("blocker") or r.get("blocker") == "none")
    ]
    needs_outreach = [r["name"] for r in clean if is_gated(r)]
    needs_more_research = errored + [r["name"] for r in clean if r.get("confidence") == "low"]

    patterns = {
        "summary": {
            "total_apps": len(results),
            "clean_rows": len(clean),
            "errored_rows": len(errored),
            "low_confidence_rows": len(low_confidence),
        },
        "auth_method_distribution": dict(auth_counts.most_common()),
        "auth_method_by_category": {
            cat: dict(counter.most_common()) for cat, counter in auth_by_category.items()
        },
        "self_serve_vs_gated": {
            "self_serve_count": len(self_serve_apps),
            "gated_count": len(gated_apps),
            "unknown_count": len(unknown_gating),
            "gated_apps": sorted(gated_apps),
        },
        "self_serve_vs_gated_by_category": gating_by_category,
        "most_common_blockers": blocker_counts.most_common(10),
        "easy_wins": sorted(easy_wins),
        "needs_outreach": sorted(needs_outreach),
        "needs_more_research": sorted(needs_more_research),
        "data_quality": {
            "errored_apps": errored,
            "low_confidence_apps": low_confidence,
        },
    }

    PATTERNS_PATH.write_text(json.dumps(patterns, indent=2) + "\n")

    print(f"Analyzed {len(clean)}/{len(results)} clean rows ({len(errored)} errored, excluded from pattern stats)\n")
    print("Auth method distribution:")
    for method, count in auth_counts.most_common():
        pct = 100 * count / len(clean)
        print(f"  {method}: {count} ({pct:.0f}%)")
    print(f"\nSelf-serve vs gated: {len(self_serve_apps)} self-serve, {len(gated_apps)} gated, {len(unknown_gating)} unclear")
    print(f"\nTop blockers:")
    for blocker, count in blocker_counts.most_common(5):
        print(f"  [{count}] {blocker}")
    print(f"\nEasy wins ({len(easy_wins)}): {', '.join(easy_wins[:12])}{'...' if len(easy_wins) > 12 else ''}")
    print(f"Needs outreach ({len(needs_outreach)}): {', '.join(needs_outreach)}")
    print(f"\nWrote full breakdown to {PATTERNS_PATH}")


if __name__ == "__main__":
    main()