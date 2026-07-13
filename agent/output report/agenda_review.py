#!/usr/bin/env python3
"""
Agenda alignment report for the take-home assignment.

Reads:
  - data/apps.json         (the 100-app input with hints)
  - output/results.json    (pipeline output)

Writes:
  - output/agenda_alignment_report.json

This report does NOT verify facts against the web; it only checks:
  - coverage vs assignment agenda (ids 1..90)
  - completeness of the 7 checkable fields
  - evidence_url hygiene (trackers, Composio docs, docs-likeness heuristics)
  - hint-domain vs evidence_url-domain mismatch (heuristic)
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
APPS_PATH = ROOT / "data" / "apps.json"
RESULTS_PATH = ROOT / "output" / "results.json"
OUT_PATH = ROOT / "output" / "agenda_alignment_report.json"

CHECKABLE_FIELDS = (
    "auth_method",
    "self_serve_or_gated",
    "api_surface",
    "has_mcp",
    "buildability_verdict",
    "blocker",
    "evidence_url",
)

ASSIGNMENT_AGENDA_IDS = set(range(1, 91))

TRACKER_SUBSTRINGS = (
    "bing.com/aclick",
    "doubleclick.net",
    "googleadservices.com",
    "googlesyndication.com",
    "ad.doubleclick.net",
)

COMPOSIO_DOCS_DOMAIN = "docs.composio.dev"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def extract_hint_domain(hint: str | None) -> str | None:
    if not hint:
        return None
    cleaned = re.sub(r"\s*\([^)]*\)", "", hint).strip()
    cleaned = cleaned.split()[0].strip()
    cleaned = cleaned.replace("https://", "").replace("http://", "")
    cleaned = cleaned.split("/")[0].strip().lower()
    return cleaned or None


def parse_url_host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlparse(url).netloc.lower()
        return host or None
    except Exception:
        return None


def is_docs_like(url: str | None) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    return (
        host.startswith("docs.")
        or host.startswith("developer.")
        or host.startswith("developers.")
        or "/docs" in path
        or "/developer" in path
        or "/developers" in path
        or "/api" in path
        or "api-reference" in path
        or "api-references" in path
    )


def hint_matches_host(hint_domain: str | None, host: str | None) -> bool | None:
    if not hint_domain or not host:
        return None
    if host == hint_domain:
        return True
    if host.endswith("." + hint_domain):
        return True
    if hint_domain.endswith("." + host):
        return True
    return False


@dataclass(frozen=True)
class EvidenceUrlAnalysis:
    url: str | None
    host: str | None
    is_tracker_or_ad_redirect: bool
    is_composio_docs: bool
    is_docs_like_heuristic: bool
    hint_domain: str | None
    hint_domain_matches_host: bool | None


def analyze_evidence_url(url: str | None, hint: str | None) -> EvidenceUrlAnalysis:
    host = parse_url_host(url)
    hint_domain = extract_hint_domain(hint)
    return EvidenceUrlAnalysis(
        url=url,
        host=host,
        is_tracker_or_ad_redirect=bool(url and any(s in url for s in TRACKER_SUBSTRINGS)),
        is_composio_docs=host == COMPOSIO_DOCS_DOMAIN,
        is_docs_like_heuristic=is_docs_like(url),
        hint_domain=hint_domain,
        hint_domain_matches_host=hint_matches_host(hint_domain, host),
    )


def main() -> None:
    apps: list[dict[str, Any]] = load_json(APPS_PATH)
    results: list[dict[str, Any]] = load_json(RESULTS_PATH)

    apps_by_id = {a["id"]: a for a in apps}
    results_by_id = {r["id"]: r for r in results}

    all_result_ids = set(results_by_id.keys())
    agenda_missing_ids = sorted(ASSIGNMENT_AGENDA_IDS - all_result_ids)
    agenda_extra_ids = sorted(all_result_ids - ASSIGNMENT_AGENDA_IDS)

    agenda_rows = [results_by_id[i] for i in sorted(ASSIGNMENT_AGENDA_IDS) if i in results_by_id]
    agenda_complete = 0
    missing_field_counts = {field: 0 for field in CHECKABLE_FIELDS}

    per_app: list[dict[str, Any]] = []

    issue_ids_tracker = []
    issue_ids_not_docs_like = []
    issue_ids_composio_docs_evidence = []
    issue_ids_hint_mismatch = []
    issue_ids_missing_any_field = []
    issue_ids_missing_auth_surface = []
    issue_ids_missing_mcp = []
    issue_ids_missing_blocker = []

    for app_id in sorted(all_result_ids):
        row = results_by_id[app_id]
        hint = (apps_by_id.get(app_id) or {}).get("hint")
        evidence = analyze_evidence_url(row.get("evidence_url"), hint)

        missing_fields = [f for f in CHECKABLE_FIELDS if row.get(f) is None]
        has_all_fields = len(missing_fields) == 0
        in_agenda = app_id in ASSIGNMENT_AGENDA_IDS

        if in_agenda and has_all_fields:
            agenda_complete += 1
        if in_agenda:
            for f in missing_fields:
                missing_field_counts[f] += 1

        if in_agenda and missing_fields:
            issue_ids_missing_any_field.append(app_id)
        if in_agenda and any(f in missing_fields for f in ("auth_method", "self_serve_or_gated", "api_surface")):
            issue_ids_missing_auth_surface.append(app_id)
        if in_agenda and "has_mcp" in missing_fields:
            issue_ids_missing_mcp.append(app_id)
        if in_agenda and "blocker" in missing_fields:
            issue_ids_missing_blocker.append(app_id)

        if in_agenda and evidence.is_tracker_or_ad_redirect:
            issue_ids_tracker.append(app_id)
        if in_agenda and (evidence.url is not None) and not evidence.is_docs_like_heuristic:
            issue_ids_not_docs_like.append(app_id)
        if in_agenda and evidence.is_composio_docs:
            issue_ids_composio_docs_evidence.append(app_id)
        if in_agenda and evidence.hint_domain_matches_host is False:
            issue_ids_hint_mismatch.append(app_id)

        per_app.append(
            {
                "id": app_id,
                "name": row.get("name"),
                "category": row.get("category"),
                "researched_via": row.get("researched_via") or "seed",
                "in_assignment_agenda_ids_1_to_90": in_agenda,
                "checkable_fields": {f: row.get(f) for f in CHECKABLE_FIELDS},
                "missing_checkable_fields": missing_fields,
                "has_all_7_checkable_fields": has_all_fields,
                "evidence_url_analysis": asdict(evidence),
            }
        )

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "assignment_agenda_ids": {"min": 1, "max": 90, "count": 90},
        "inputs": {
            "apps_path": str(APPS_PATH.relative_to(ROOT)),
            "results_path": str(RESULTS_PATH.relative_to(ROOT)),
            "apps_count": len(apps),
            "results_count": len(results),
        },
        "coverage": {
            "agenda_missing_ids": agenda_missing_ids,
            "extra_ids_not_in_agenda": agenda_extra_ids,
        },
        "agenda_field_completeness": {
            "agenda_apps_present": len(agenda_rows),
            "agenda_apps_with_all_7_fields": agenda_complete,
            "agenda_apps_missing_any_field": len(agenda_rows) - agenda_complete,
            "missing_field_counts": missing_field_counts,
        },
        "agenda_evidence_url_hygiene": {
            "tracker_or_ad_redirect_ids": issue_ids_tracker,
            "not_docs_like_heuristic_ids": issue_ids_not_docs_like,
            "composio_docs_evidence_ids": issue_ids_composio_docs_evidence,
            "hint_domain_mismatch_ids": issue_ids_hint_mismatch,
        },
        "agenda_missing_fields": {
            "missing_any_field_ids": issue_ids_missing_any_field,
            "missing_auth_or_surface_ids": issue_ids_missing_auth_surface,
            "missing_has_mcp_ids": issue_ids_missing_mcp,
            "missing_blocker_ids": issue_ids_missing_blocker,
        },
        "apps": per_app,
    }

    save_json(OUT_PATH, report)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()

