#!/usr/bin/env python3
"""
Verification and sampling script for the app audit results.

Workflow (matches the assignment's "verify your accuracy" requirement):

  1. sample   - pick N apps at random (fixed seed, reproducible) from
                output/results.json and write a review template with the
                agent's claimed fields + evidence_url, and blank verdict
                slots for a human to fill in after checking the real docs.
  2. score    - read a filled-in template and compute pass accuracy:
                per-field correct/incorrect/unsure, overall %, and a list
                of misses (shown honestly, per the assignment).
  3. compare  - diff a pass-1 scored file against a pass-2 scored file and
                report the accuracy delta plus which apps improved.

Usage:
  python3 verify.py sample  --n 20 --seed 42 \
      --out output/verification_pass1_template.json

  # ... hand-fill the "verdict" block for each app against real docs ...

  python3 verify.py score   --in output/verification_pass1_template.json \
      --out output/verification_pass1_scored.json

  # ... fix the failure modes the sample surfaced in research.py, rerun
  #     just those apps, then re-sample the same apps for pass 2 ...

  python3 verify.py sample  --n 20 --seed 42 --ids-from output/verification_pass1_scored.json \
      --out output/verification_pass2_template.json

  # ... hand-fill pass 2 the same way ...

  python3 verify.py score   --in output/verification_pass2_template.json \
      --out output/verification_pass2_scored.json

  python3 verify.py compare --pass1 output/verification_pass1_scored.json \
      --pass2 output/verification_pass2_scored.json
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

# The fields we actually claim to have researched, and therefore the ones
# a human needs to check against the real docs. Kept in sync with
# RESEARCH_FIELDS in research.py, minus confidence (that's the agent's own
# self-rating, not a checkable fact) plus evidence_url (which is checkable:
# does the link actually go to a real, relevant page).
CHECKABLE_FIELDS = (
    "auth_method",
    "self_serve_or_gated",
    "api_surface",
    "has_mcp",
    "buildability_verdict",
    "blocker",
    "evidence_url",
)

VERDICT_VALUES = ("correct", "incorrect", "unsure")


def load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: str | Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


# ---------------------------------------------------------------------------
# sample
# ---------------------------------------------------------------------------

def cmd_sample(args: argparse.Namespace) -> None:
    results: list[dict[str, Any]] = load_json(args.results)
    if not isinstance(results, list):
        raise SystemExit(
            f"{args.results} is not a flat list of app rows — "
            "verify.py expects the same shape research.py writes."
        )

    if args.ids_from:
        # Pass 2+: reuse the exact same apps as a prior pass so the
        # accuracy delta is a real apples-to-apples comparison, not just
        # a different random sample. Accepts either a scored file
        # (key "per_app", written by `score`) or a raw template
        # (key "apps", written by `sample`).
        prior = load_json(args.ids_from)
        prior_rows = prior.get("per_app") or prior.get("apps") or []
        wanted_ids = {row["id"] for row in prior_rows}
        chosen = [row for row in results if row["id"] in wanted_ids]
        missing = wanted_ids - {row["id"] for row in chosen}
        if missing:
            print(f"Warning: {len(missing)} ids from {args.ids_from} not found in {args.results}: {sorted(missing)}")
    else:
        rng = random.Random(args.seed)
        chosen = rng.sample(results, k=min(args.n, len(results)))
        chosen.sort(key=lambda row: row["id"])

    template = {
        "_instructions": (
            "For each app, open evidence_url (or search for the real docs "
            "if it's missing/broken) and fill in verdict.<field> with one "
            f"of {VERDICT_VALUES}. Add a one-line correction in "
            "verdict_notes.<field> when marking incorrect. Leave a field's "
            "verdict as null if you skip it (it will be excluded from "
            "scoring, not counted as wrong)."
        ),
        "checkable_fields": list(CHECKABLE_FIELDS),
        "apps": [],
    }

    for row in chosen:
        template["apps"].append({
            "id": row["id"],
            "name": row["name"],
            "category": row.get("category"),
            "researched_via": row.get("researched_via", "seed"),
            "claimed": {field: row.get(field) for field in CHECKABLE_FIELDS},
            "verdict": {field: None for field in CHECKABLE_FIELDS},
            "verdict_notes": {field: "" for field in CHECKABLE_FIELDS},
        })

    save_json(args.out, template)
    print(f"Wrote {len(chosen)} apps to {args.out} for manual review.")
    print("Open each evidence_url and fill in the verdict block, then run:")
    print(f"  python3 verify.py score --in {args.out} --out <scored_file>.json")


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------

def cmd_score(args: argparse.Namespace) -> None:
    template: dict[str, Any] = load_json(args.inp)
    apps = template.get("apps", [])
    if not apps:
        raise SystemExit(f"No apps found in {args.inp} — did you run 'sample' first?")

    per_app_rows = []
    field_totals: dict[str, dict[str, int]] = {
        field: {"correct": 0, "incorrect": 0, "unsure": 0, "unscored": 0}
        for field in CHECKABLE_FIELDS
    }
    misses = []

    for app in apps:
        verdicts = app.get("verdict", {})
        notes = app.get("verdict_notes", {})
        scored_fields = 0
        correct_fields = 0

        for field in CHECKABLE_FIELDS:
            v = verdicts.get(field)
            if v is None:
                field_totals[field]["unscored"] += 1
                continue
            if v not in VERDICT_VALUES:
                raise SystemExit(
                    f"App {app['id']} field '{field}' has invalid verdict "
                    f"{v!r}; must be one of {VERDICT_VALUES} or null."
                )
            field_totals[field][v] += 1
            scored_fields += 1
            if v == "correct":
                correct_fields += 1
            else:
                misses.append({
                    "id": app["id"],
                    "name": app["name"],
                    "field": field,
                    "verdict": v,
                    "claimed": app["claimed"].get(field),
                    "note": notes.get(field, ""),
                })

        app_accuracy = (correct_fields / scored_fields) if scored_fields else None
        per_app_rows.append({
            "id": app["id"],
            "name": app["name"],
            "researched_via": app.get("researched_via"),
            "fields_scored": scored_fields,
            "fields_correct": correct_fields,
            "accuracy": round(app_accuracy, 3) if app_accuracy is not None else None,
        })

        if scored_fields == 0:
            print(f"Warning: app {app['id']} ({app['name']}) has no filled-in verdicts — "
                  "did you forget to review it?")

    total_scored = sum(t["correct"] + t["incorrect"] + t["unsure"] for t in field_totals.values())
    total_correct = sum(t["correct"] for t in field_totals.values())
    total_unsure = sum(t["unsure"] for t in field_totals.values())

    strict_accuracy = (total_correct / total_scored) if total_scored else None
    # "Lenient" excludes unsure from the denominator entirely, since those
    # weren't confidently judged either way.
    lenient_denom = total_scored - total_unsure
    lenient_accuracy = (total_correct / lenient_denom) if lenient_denom else None

    summary = {
        "source_template": str(args.inp),
        "apps_reviewed": len(apps),
        "fields_scored_total": total_scored,
        "fields_correct_total": total_correct,
        "fields_unsure_total": total_unsure,
        "accuracy_strict_unsure_as_wrong": round(strict_accuracy, 4) if strict_accuracy is not None else None,
        "accuracy_excluding_unsure": round(lenient_accuracy, 4) if lenient_accuracy is not None else None,
        "by_field": field_totals,
        "per_app": per_app_rows,
        "misses": misses,
    }

    save_json(args.out, summary)

    print(f"\nReviewed {len(apps)} apps, {total_scored} fields scored.")
    if strict_accuracy is not None:
        print(f"Accuracy (unsure = wrong): {strict_accuracy:.1%}")
    if lenient_accuracy is not None:
        print(f"Accuracy (excluding unsure): {lenient_accuracy:.1%}")
    print(f"Misses: {len(misses)} — see {args.out} for the full honest list.")
    print("\nWorst fields:")
    ranked = sorted(
        field_totals.items(),
        key=lambda kv: kv[1]["incorrect"] + kv[1]["unsure"],
        reverse=True,
    )
    for field, counts in ranked[:5]:
        wrong = counts["incorrect"] + counts["unsure"]
        if wrong:
            print(f"  {field}: {wrong} wrong/unsure out of "
                  f"{counts['correct'] + counts['incorrect'] + counts['unsure']} scored")


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------

def cmd_compare(args: argparse.Namespace) -> None:
    pass1 = load_json(args.pass1)
    pass2 = load_json(args.pass2)

    a1 = pass1.get("accuracy_strict_unsure_as_wrong")
    a2 = pass2.get("accuracy_strict_unsure_as_wrong")
    print(f"Pass 1 accuracy (strict): {a1:.1%}" if a1 is not None else "Pass 1: no data")
    print(f"Pass 2 accuracy (strict): {a2:.1%}" if a2 is not None else "Pass 2: no data")
    if a1 is not None and a2 is not None:
        delta = a2 - a1
        print(f"Delta: {delta:+.1%}")

    p1_by_app = {row["id"]: row for row in pass1.get("per_app", [])}
    p2_by_app = {row["id"]: row for row in pass2.get("per_app", [])}
    common_ids = sorted(set(p1_by_app) & set(p2_by_app))

    print(f"\n{len(common_ids)} apps present in both passes:")
    improved, regressed, unchanged = [], [], []
    for app_id in common_ids:
        acc1 = p1_by_app[app_id]["accuracy"]
        acc2 = p2_by_app[app_id]["accuracy"]
        name = p2_by_app[app_id]["name"]
        if acc1 is None or acc2 is None:
            continue
        if acc2 > acc1:
            improved.append((name, acc1, acc2))
        elif acc2 < acc1:
            regressed.append((name, acc1, acc2))
        else:
            unchanged.append(name)

    print(f"  Improved: {len(improved)}")
    for name, a1v, a2v in improved:
        print(f"    {name}: {a1v:.0%} -> {a2v:.0%}")
    print(f"  Regressed: {len(regressed)}")
    for name, a1v, a2v in regressed:
        print(f"    {name}: {a1v:.0%} -> {a2v:.0%}")
    print(f"  Unchanged: {len(unchanged)}")

    combined = {
        "pass1_accuracy": a1,
        "pass2_accuracy": a2,
        "delta": (a2 - a1) if (a1 is not None and a2 is not None) else None,
        "improved": [{"name": n, "pass1": p1v, "pass2": p2v} for n, p1v, p2v in improved],
        "regressed": [{"name": n, "pass1": p1v, "pass2": p2v} for n, p1v, p2v in regressed],
        "unchanged": unchanged,
    }
    if args.out:
        save_json(args.out, combined)
        print(f"\nWrote comparison to {args.out}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_sample = sub.add_parser("sample", help="Pick a random sample of apps for manual review")
    p_sample.add_argument("--results", default="output/results.json")
    p_sample.add_argument("--n", type=int, default=18)
    p_sample.add_argument("--seed", type=int, default=42)
    p_sample.add_argument("--ids-from", default=None, help="Reuse the app ids from a prior scored file (for pass 2+)")
    p_sample.add_argument("--out", required=True)
    p_sample.set_defaults(func=cmd_sample)

    p_score = sub.add_parser("score", help="Score a hand-filled review template")
    p_score.add_argument("--in", dest="inp", required=True)
    p_score.add_argument("--out", required=True)
    p_score.set_defaults(func=cmd_score)

    p_compare = sub.add_parser("compare", help="Compare two scored passes")
    p_compare.add_argument("--pass1", required=True)
    p_compare.add_argument("--pass2", required=True)
    p_compare.add_argument("--out", default=None)
    p_compare.set_defaults(func=cmd_compare)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())