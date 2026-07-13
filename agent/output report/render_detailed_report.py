#!/usr/bin/env python3
"""
Render an executive HTML report for the Composio audit assignment.

Inputs:
  - output/results.json
  - output/patterns.json
  - output/agenda_alignment_report.json
  - output/verification_pass1_scored_REAL.json
  - output/verification_pass2_scored.json
  - output/verification_delta.json

Output:
  - output/detailed_assignment_report.html
"""

from __future__ import annotations

import html
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"

RESULTS_PATH = OUTPUT / "results.json"
PATTERNS_PATH = OUTPUT / "patterns.json"
ALIGN_PATH = OUTPUT / "agenda_alignment_report.json"
PASS1_PATH = OUTPUT / "verification_pass1_scored_REAL.json"
PASS2_PATH = OUTPUT / "verification_pass2_scored.json"
DELTA_PATH = OUTPUT / "verification_delta.json"
OUT_HTML = OUTPUT / "detailed_assignment_report.html"

CHECKABLE_FIELDS = (
    "auth_method",
    "self_serve_or_gated",
    "api_surface",
    "has_mcp",
    "buildability_verdict",
    "blocker",
    "evidence_url",
)

AUTH_ORDER = ["OAuth2", "OAuth2 + API key", "API key / token", "Basic auth", "other", "unknown"]
ACCESS_ORDER = ["self_serve", "gated", "unknown"]
CONFIDENCE_SCORE = {"low": 0.25, "medium": 0.55, "high": 0.85}


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def pct(part: float, whole: float) -> str:
    if not whole:
        return "0.0%"
    return f"{part * 100 / whole:.1f}%"


def normalize_auth(auth_method: str | None) -> str:
    if not auth_method:
        return "unknown"
    value = auth_method.lower()
    has_oauth = "oauth" in value
    has_basic = "basic" in value
    has_key = "api key" in value or "api token" in value or ("token" in value and "oauth" not in value)
    if has_oauth and (has_key or "also" in value):
        return "OAuth2 + API key"
    if has_oauth:
        return "OAuth2"
    if has_key:
        return "API key / token"
    if has_basic:
        return "Basic auth"
    if value in {"none", "no auth", "no_auth"}:
        return "none"
    return "other"


def access_bucket(row: dict[str, Any]) -> str:
    value = (row.get("self_serve_or_gated") or "").lower()
    if "self-serve" in value or "self serve" in value:
        return "self_serve"
    if "gated" in value:
        return "gated"
    return "unknown"


def blocker_bucket(row: dict[str, Any]) -> str:
    blocker = (row.get("blocker") or "").strip().lower()
    verdict = (row.get("buildability_verdict") or "").strip().lower()
    if (not blocker or blocker == "none") and ("yes" in verdict or "suitable" in verdict or "already" in verdict):
        return "Ready"
    text = f"{blocker} {verdict}"
    if "gate" in text or "approval" in text or "sales" in text or "enterprise" in text or "account manager" in text:
        return "Sales/API gate"
    if "captcha" in text or "anti-bot" in text or "anti bot" in text:
        return "Anti-bot/Captcha"
    if "no documentation" in text or "missing docs" in text or "insufficient" in text or "no public" in text:
        return "Missing docs"
    if "0 agent-callable" in text or "no tools" in text or "no supported actions" in text:
        return "No/limited toolkit"
    if "error" in text or "failed" in text or "empty" in text or "js-rendered" in text:
        return "Research failure"
    return "Other blocker"


def api_breadth(row: dict[str, Any]) -> str:
    explicit = (row.get("api_breadth") or "").lower()
    if explicit in {"broad", "large"}:
        return "Large"
    if explicit in {"moderate", "medium"}:
        return "Medium"
    if explicit in {"narrow", "small"}:
        return "Small"
    surface = (row.get("api_surface") or "").lower()
    count_match = re.search(r"as (\d+) agent-callable", surface)
    if count_match:
        count = int(count_match.group(1))
        if count >= 100:
            return "Large"
        if count >= 25:
            return "Medium"
        if count > 0:
            return "Small"
    if "broad" in surface or "comprehensive" in surface or "rest + soap" in surface:
        return "Large"
    if "moderate" in surface or "graphql" in surface:
        return "Medium"
    if "unknown" in surface or not surface:
        return "Unknown"
    return "Small"


def confidence_bucket(row: dict[str, Any]) -> str:
    return (row.get("confidence") or "unknown").lower()


def field_completeness(row: dict[str, Any]) -> bool:
    return all(row.get(field) is not None for field in CHECKABLE_FIELDS)


def category_label(category: str) -> str:
    replacements = {
        "Developer, Infra and Data platforms": "Dev / Infra",
        "Productivity and Project Management": "Productivity",
        "Marketing, Ads, Email and Social": "Marketing",
        "Communications and Messaging": "Messaging",
        "Data, SEO and Scraping": "Data / SEO",
        "AI, Research and Media-native": "AI / Media",
        "Support and Helpdesk": "Support",
        "CRM and Sales": "CRM",
        "Finance and Fintech": "Finance",
    }
    return replacements.get(category, category)


def make_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]], limit: int | None = None) -> str:
    visible = rows if limit is None else rows[:limit]
    header = "".join(f"<th>{esc(label)}</th>" for _, label in columns)
    body = []
    for row in visible:
        cells = []
        for key, _ in columns:
            value = row.get(key)
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            cells.append(f"<td>{esc(value)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    note = ""
    if limit is not None and len(rows) > limit:
        note = f'<div class="table-note">Showing {limit} of {len(rows)} rows.</div>'
    return f'<div class="table-wrap"><table><thead><tr>{header}</tr></thead><tbody>{"".join(body)}</tbody></table></div>{note}'


def main() -> None:
    results: list[dict[str, Any]] = load_json(RESULTS_PATH, [])
    patterns = load_json(PATTERNS_PATH, {})
    align = load_json(ALIGN_PATH, {})
    pass1 = load_json(PASS1_PATH, {})
    pass2 = load_json(PASS2_PATH, {})
    delta = load_json(DELTA_PATH, {})

    total_apps = len(results)
    core_apps = [row for row in results if 1 <= row.get("id", 0) <= 90]
    extra_apps = [row for row in results if row.get("id", 0) > 90]
    complete_count = sum(1 for row in results if field_completeness(row))
    low_conf_count = sum(1 for row in results if row.get("confidence") == "low")

    category_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        category_rows[row.get("category") or "Unknown"].append(row)

    categories = sorted(category_rows, key=lambda c: category_label(c))

    access_by_category = []
    auth_by_category = []
    readiness_by_category = []
    breadth_by_mcp = defaultdict(lambda: Counter({"mcp_true": 0, "mcp_false": 0, "mcp_unknown": 0}))
    confidence_counts = Counter(confidence_bucket(row) for row in results)
    via_counts = Counter(row.get("researched_via") or "seed" for row in results)
    auth_counts = Counter(normalize_auth(row.get("auth_method")) for row in results)
    access_counts = Counter(access_bucket(row) for row in results)
    blocker_counts = Counter(blocker_bucket(row) for row in results)

    for category in categories:
        rows = category_rows[category]
        access_counts_cat = Counter(access_bucket(row) for row in rows)
        auth_counts_cat = Counter(normalize_auth(row.get("auth_method")) for row in rows)
        readiness_counts_cat = Counter(blocker_bucket(row) for row in rows)
        access_by_category.append({"category": category_label(category), **{k: access_counts_cat[k] for k in ACCESS_ORDER}})
        auth_by_category.append({"category": category_label(category), **{k: auth_counts_cat[k] for k in AUTH_ORDER}})
        readiness_by_category.append(
            {
                "category": category_label(category),
                "Ready": readiness_counts_cat["Ready"],
                "Sales/API gate": readiness_counts_cat["Sales/API gate"],
                "Anti-bot/Captcha": readiness_counts_cat["Anti-bot/Captcha"],
                "Missing docs": readiness_counts_cat["Missing docs"],
                "No/limited toolkit": readiness_counts_cat["No/limited toolkit"],
                "Research failure": readiness_counts_cat["Research failure"],
                "Other blocker": readiness_counts_cat["Other blocker"],
            }
        )

    for row in results:
        breadth = api_breadth(row)
        if row.get("has_mcp") is True:
            breadth_by_mcp[breadth]["mcp_true"] += 1
        elif row.get("has_mcp") is False:
            breadth_by_mcp[breadth]["mcp_false"] += 1
        else:
            breadth_by_mcp[breadth]["mcp_unknown"] += 1

    pass1_acc = pass1.get("accuracy_strict_unsure_as_wrong")
    pass2_acc = pass2.get("accuracy_strict_unsure_as_wrong")
    pass1_lenient = pass1.get("accuracy_excluding_unsure")
    pass2_lenient = pass2.get("accuracy_excluding_unsure")

    result_by_id = {row["id"]: row for row in results}
    pass1_apps = pass1.get("per_app", [])
    scatter_points = []
    for row in pass1_apps:
        source = result_by_id.get(row.get("id"), {})
        confidence = confidence_bucket(source)
        scatter_points.append(
            {
                "id": row.get("id"),
                "name": row.get("name"),
                "confidence": confidence,
                "x": CONFIDENCE_SCORE.get(confidence, 0.1),
                "accuracy": row.get("accuracy") or 0,
                "researched_via": row.get("researched_via") or source.get("researched_via") or "seed",
            }
        )

    human_checked = pass2.get("apps_reviewed") or pass1.get("apps_reviewed") or 0
    effort_split = [
        {"label": "Pure agent automation (seed + Composio)", "value": via_counts["seed"] + via_counts["composio"]},
        {"label": "Browser/docs fallback (web)", "value": via_counts["web"]},
        {"label": "Human quality checking sample", "value": human_checked},
    ]

    missing_any = []
    hygiene_tables = {
        "tracker_or_ad_redirect_ids": [],
        "not_docs_like_heuristic_ids": [],
        "composio_docs_evidence_ids": [],
        "hint_domain_mismatch_ids": [],
    }
    app_align = {row["id"]: row for row in align.get("apps", [])}
    for row in results:
        missing = [field for field in CHECKABLE_FIELDS if row.get(field) is None]
        if missing:
            missing_any.append({"id": row["id"], "name": row["name"], "category": category_label(row["category"]), "missing": missing})
    for key in hygiene_tables:
        for app_id in align.get("agenda_evidence_url_hygiene", {}).get(key, []):
            row = result_by_id.get(app_id, {})
            analysis = (app_align.get(app_id) or {}).get("evidence_url_analysis", {})
            hygiene_tables[key].append(
                {
                    "id": app_id,
                    "name": row.get("name"),
                    "category": category_label(row.get("category", "")),
                    "host": analysis.get("host"),
                    "evidence_url": analysis.get("url"),
                }
            )

    output_files = [
        {"file": "results_seed.json", "role": "Starting point with known or prefilled claims before the research run."},
        {"file": "results.json", "role": "Main 100-app research output. This is claim data, not final verified truth."},
        {"file": "patterns.json", "role": "Aggregated patterns: auth distribution, access gates, blockers, easy wins, and low-confidence rows."},
        {"file": "agenda_alignment_report.json", "role": "Quality-control report comparing current output to the 90-app assignment agenda."},
        {"file": "verification_pass1_template.json", "role": "Manual review template generated from a sampled set of apps."},
        {"file": "verification_pass1_filled.json", "role": "Human-filled pass 1 verdicts."},
        {"file": "verification_pass1_scored_REAL.json", "role": "Pass 1 scoring after human review. Strict accuracy: " + pct(pass1_acc or 0, 1)},
        {"file": "verification_pass2_template.json", "role": "Second-pass template using the same sampled app IDs for apples-to-apples scoring."},
        {"file": "verification_pass2_filled.json", "role": "Human/browser-assisted pass 2 verdicts."},
        {"file": "verification_pass2_scored.json", "role": "Pass 2 scoring after feedback loop. Strict accuracy: " + pct(pass2_acc or 0, 1)},
        {"file": "verification_delta.json", "role": "Accuracy delta between pass 1 and pass 2."},
        {"file": "detailed_assignment_report.html", "role": "This executive report."},
    ]

    app_table = []
    for row in sorted(results, key=lambda r: r["id"]):
        app_table.append(
            {
                "id": row["id"],
                "app": row["name"],
                "category": category_label(row["category"]),
                "access": access_bucket(row).replace("_", "-"),
                "auth": normalize_auth(row.get("auth_method")),
                "readiness": blocker_bucket(row),
                "api_breadth": api_breadth(row),
                "mcp": "yes" if row.get("has_mcp") is True else ("no" if row.get("has_mcp") is False else "unknown"),
                "confidence": row.get("confidence"),
            }
        )

    data = {
        "totalApps": total_apps,
        "coreApps": len(core_apps),
        "extraApps": len(extra_apps),
        "completeCount": complete_count,
        "lowConfidenceCount": low_conf_count,
        "accessCounts": dict(access_counts),
        "authCounts": dict(auth_counts),
        "blockerCounts": dict(blocker_counts),
        "confidenceCounts": dict(confidence_counts),
        "viaCounts": dict(via_counts),
        "accessByCategory": access_by_category,
        "authByCategory": auth_by_category,
        "readinessByCategory": readiness_by_category,
        "breadthByMcp": {k: dict(v) for k, v in breadth_by_mcp.items()},
        "verification": {
            "pass1": pass1_acc,
            "pass2": pass2_acc,
            "pass1Lenient": pass1_lenient,
            "pass2Lenient": pass2_lenient,
            "delta": delta.get("delta"),
            "improved": len(delta.get("improved", [])),
            "regressed": len(delta.get("regressed", [])),
            "unchanged": len(delta.get("unchanged", [])),
            "sampleApps": pass2.get("apps_reviewed") or pass1.get("apps_reviewed") or 0,
        },
        "scatterPoints": scatter_points,
        "effortSplit": effort_split,
    }

    html_out = render_html(
        data=data,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        patterns_summary=patterns.get("summary", {}),
        output_files=output_files,
        missing_any=missing_any,
        hygiene_tables=hygiene_tables,
        app_table=app_table,
    )
    OUT_HTML.write_text(html_out, encoding="utf-8")
    print(f"Wrote {OUT_HTML}")


def render_html(
    *,
    data: dict[str, Any],
    generated_at: str,
    patterns_summary: dict[str, Any],
    output_files: list[dict[str, str]],
    missing_any: list[dict[str, Any]],
    hygiene_tables: dict[str, list[dict[str, Any]]],
    app_table: list[dict[str, Any]],
) -> str:
    output_table = make_table(output_files, [("file", "Output file"), ("role", "How to read it")])
    missing_table = make_table(missing_any, [("id", "ID"), ("name", "App"), ("category", "Category"), ("missing", "Missing fields")], 40)
    tracker_table = make_table(hygiene_tables["tracker_or_ad_redirect_ids"], [("id", "ID"), ("name", "App"), ("host", "Host"), ("evidence_url", "Evidence URL")], 20)
    docs_table = make_table(hygiene_tables["not_docs_like_heuristic_ids"], [("id", "ID"), ("name", "App"), ("host", "Host"), ("evidence_url", "Evidence URL")], 35)
    composio_table = make_table(hygiene_tables["composio_docs_evidence_ids"], [("id", "ID"), ("name", "App"), ("category", "Category"), ("evidence_url", "Evidence URL")], 45)
    app_table_html = make_table(
        app_table,
        [("id", "ID"), ("app", "App"), ("category", "Category"), ("access", "Access"), ("auth", "Auth"), ("readiness", "Readiness"), ("api_breadth", "API"), ("mcp", "MCP"), ("confidence", "Confidence")],
        100,
    )
    payload = json.dumps(data)
    total = data["totalApps"]
    complete = data["completeCount"]
    pass1 = data["verification"]["pass1"] or 0
    pass2 = data["verification"]["pass2"] or 0
    delta = data["verification"]["delta"] or 0

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Composio Audit Assignment Report</title>
  <style>
    :root {{
      --bg: #f7f8fb;
      --ink: #152033;
      --muted: #64748b;
      --line: #d8dee9;
      --panel: #ffffff;
      --soft: #eef3f8;
      --blue: #2563eb;
      --green: #16a34a;
      --amber: #d97706;
      --red: #dc2626;
      --purple: #7c3aed;
      --teal: #0f766e;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Arial, sans-serif; }}
    .wrap {{ max-width: 1220px; margin: 0 auto; padding: 28px 20px 56px; }}
    h1 {{ margin: 0; font-size: 30px; line-height: 1.15; letter-spacing: 0; }}
    h2 {{ margin: 0 0 10px; font-size: 20px; line-height: 1.25; letter-spacing: 0; }}
    h3 {{ margin: 0 0 8px; font-size: 15px; letter-spacing: 0; }}
    p {{ color: var(--muted); line-height: 1.55; margin: 0 0 12px; }}
    code {{ background: #edf2f7; border: 1px solid var(--line); border-radius: 5px; padding: 1px 5px; }}
    .top {{ display: grid; grid-template-columns: 1.5fr .8fr; gap: 18px; align-items: start; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px; box-shadow: 0 8px 22px rgba(15, 23, 42, .05); }}
    .band {{ margin-top: 18px; }}
    .kpis {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 18px; }}
    .kpi {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .kpi strong {{ display: block; font-size: 26px; line-height: 1; }}
    .kpi span {{ display: block; color: var(--muted); font-size: 12px; margin-top: 7px; }}
    .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .grid3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
    .chart-box {{ min-height: 310px; }}
    .chart-box.tall {{ min-height: 430px; }}
    .legend-note {{ font-size: 12px; color: var(--muted); margin-top: 8px; }}
    .flow {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .node {{ background: #ffffff; border: 1px solid var(--line); border-radius: 7px; padding: 9px 11px; font-size: 13px; font-weight: 650; }}
    .arrow {{ color: var(--muted); font-weight: 800; }}
    .step-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 12px; }}
    .step {{ border: 1px solid var(--line); background: #fbfcfe; border-radius: 8px; padding: 13px; }}
    .step b {{ display: block; margin-bottom: 4px; }}
    .step span {{ color: var(--muted); font-size: 13px; line-height: 1.45; }}
    .callout {{ border-left: 4px solid var(--amber); background: #fff8eb; padding: 13px 14px; border-radius: 6px; }}
    .callout strong {{ display: block; margin-bottom: 4px; }}
    .table-wrap {{ overflow: auto; border: 1px solid var(--line); border-radius: 8px; background: #fff; }}
    table {{ border-collapse: collapse; width: 100%; min-width: 820px; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #e8edf3; font-size: 12px; text-align: left; vertical-align: top; }}
    th {{ background: #f1f5f9; color: #334155; position: sticky; top: 0; }}
    .table-note {{ color: var(--muted); font-size: 12px; margin-top: 8px; }}
    details {{ background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; margin-top: 10px; }}
    summary {{ cursor: pointer; font-weight: 750; }}
    svg {{ display: block; width: 100%; height: auto; }}
    .axis text, .label {{ fill: #475569; font-size: 11px; }}
    .title-small {{ fill: #334155; font-weight: 750; font-size: 12px; }}
    .muted-svg {{ fill: #64748b; font-size: 11px; }}
    @media (max-width: 900px) {{
      .top, .grid2, .grid3, .step-grid {{ grid-template-columns: 1fr; }}
      .kpis {{ grid-template-columns: repeat(2, 1fr); }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="top">
      <div class="panel">
        <h1>Composio Audit: 100-App Research, Pattern Analysis, and Verification</h1>
        <p style="margin-top:10px">This report explains the assignment output in plain terms: what the agent researched, how claims moved through validation, which patterns emerged, and where human review is still required.</p>
        <div class="flow" aria-label="pipeline flow">
          <span class="node">100 Apps</span><span class="arrow">-></span>
          <span class="node">Research Agent</span><span class="arrow">-></span>
          <span class="node">Composio Toolkit Search</span><span class="arrow">-></span>
          <span class="node">Official Documentation Search</span><span class="arrow">-></span>
          <span class="node">Content Extraction</span><span class="arrow">-></span>
          <span class="node">LLM Structuring</span><span class="arrow">-></span>
          <span class="node">results.json</span><span class="arrow">-></span>
          <span class="node">Pattern Analysis</span><span class="arrow">-></span>
          <span class="node">Verification Pipeline</span><span class="arrow">-></span>
          <span class="node">Pass 1</span><span class="arrow">-></span>
          <span class="node">Human Review</span><span class="arrow">-></span>
          <span class="node">Pass 2</span><span class="arrow">-></span>
          <span class="node">Final Report</span>
        </div>
      </div>
      <div class="panel">
        <h2>Executive Summary</h2>
        <p><b>{total}</b> apps are present in <code>results.json</code>. The assignment's first 90 apps are fully covered, with 10 additional AI/media apps included.</p>
        <p><b>{complete}</b> apps have all 7 required claim fields populated. The remaining rows need targeted cleanup before final submission.</p>
        <p>Manual verification improved strict sampled accuracy from <b>{pass1:.1%}</b> to <b>{pass2:.1%}</b>, a <b>{delta:+.1%}</b> change.</p>
        <p class="legend-note">Generated {esc(generated_at)}. Pattern rows: {esc(patterns_summary.get("clean_rows"))} clean, {esc(patterns_summary.get("errored_rows"))} errored, {esc(patterns_summary.get("low_confidence_rows"))} low confidence.</p>
      </div>
    </section>

    <section class="kpis">
      <div class="kpi"><strong>{total}</strong><span>Total app rows analyzed</span></div>
      <div class="kpi"><strong>{data["coreApps"]}/90</strong><span>Assignment apps covered</span></div>
      <div class="kpi"><strong>{pct(complete, total)}</strong><span>Rows with all 7 fields</span></div>
      <div class="kpi"><strong>{data["verification"]["sampleApps"]}</strong><span>Apps manually scored per pass</span></div>
    </section>

    <section class="band panel">
      <h2>How the Agents Work</h2>
      <div class="step-grid">
        <div class="step"><b>1. Research agent</b><span><code>agent/research.py</code> starts from <code>data/apps.json</code> and fills missing fields into <code>output/results.json</code>.</span></div>
        <div class="step"><b>2. Fast path</b><span>It checks Composio toolkit metadata first. When a toolkit exists, it records auth, tool count, MCP claim, buildability, and Composio evidence.</span></div>
        <div class="step"><b>3. Web fallback</b><span>If no toolkit is found, it searches for API docs, extracts page text, and asks the LLM to structure the seven research fields.</span></div>
        <div class="step"><b>4. Pattern analysis</b><span><code>agent/pattern.py</code> groups results by auth type, access model, blockers, easy wins, and low-confidence rows.</span></div>
        <div class="step"><b>5. Verification</b><span><code>agent/verify.py</code> samples apps into templates, scores human verdicts, and compares pass 1 vs pass 2.</span></div>
        <div class="step"><b>6. Report layer</b><span>This HTML summarizes the raw outputs and highlights what still requires official documentation checks.</span></div>
      </div>
    </section>

    <section class="band grid2">
      <div class="panel chart-box"><h2>Category vs Accessibility</h2><p>Grouped columns show whether app categories are mostly self-serve, gated, or still unknown.</p><div id="accessChart"></div></div>
      <div class="panel chart-box"><h2>Research Effort Split</h2><p>Donut uses workflow touches: automated rows, web fallback rows, and human QC sample. Human QC overlaps with researched apps.</p><div id="effortDonut"></div></div>
    </section>

    <section class="band panel chart-box tall">
      <h2>Authentication Protocols by Category</h2>
      <p>Stacked horizontal bars make it clear where OAuth2 dominates and where API keys are common. Unknowns are immediate review targets.</p>
      <div id="authStacked"></div>
    </section>

    <section class="band grid2">
      <div class="panel chart-box tall"><h2>Buildability Verdicts and Blockers</h2><p>Stacked columns show ready-to-build categories versus blockers such as sales gates, missing docs, research failures, or limited toolkits.</p><div id="readinessStacked"></div></div>
      <div class="panel chart-box tall"><h2>API Surface Breadth vs MCP</h2><p>Treemap groups apps by inferred API breadth and colors each slice by whether MCP support is claimed in the current output. Treat this as a review queue, not proof of official MCP support.</p><div id="treemap"></div></div>
    </section>

    <section class="band grid2">
      <div class="panel chart-box"><h2>Verification Loop Impact</h2><p>The two-point line shows the validation loop improved strict accuracy after browser validation and human feedback.</p><div id="accuracyLine"></div></div>
      <div class="panel chart-box"><h2>Agent Confidence vs Actual Accuracy</h2><p>Each dot is one sampled app from pass 1. High-confidence dots with low accuracy are the likely hallucination or overclaim zone.</p><div id="scatter"></div></div>
    </section>

    <section class="band grid3">
      <div class="panel chart-box"><h2>Overall Auth Mix</h2><div id="authDonut"></div></div>
      <div class="panel chart-box"><h2>Overall Access Mix</h2><div id="accessDonut"></div></div>
      <div class="panel chart-box"><h2>Confidence Mix</h2><div id="confidenceDonut"></div></div>
    </section>

    <section class="band panel">
      <h2>What the Output Folder Means</h2>
      <p>The output folder has claim data, pattern summaries, manual review templates, scored verification passes, and this report. The most important distinction is that <code>results.json</code> contains claims while the <code>verification_*</code> files contain checks against official docs.</p>
      {output_table}
    </section>

    <section class="band panel">
      <h2>Where Human Intervention Is Needed</h2>
      <div class="callout"><strong>Key rule for final submission</strong><span>Official documentation must confirm each field. If official docs do not confirm a field, mark it unsure rather than inferring.</span></div>
      <details open><summary>Rows missing required fields ({len(missing_any)})</summary>{missing_table}</details>
      <details><summary>Tracker or ad redirect evidence URLs ({len(hygiene_tables["tracker_or_ad_redirect_ids"])})</summary>{tracker_table}</details>
      <details><summary>Evidence URLs that do not look like developer/API docs ({len(hygiene_tables["not_docs_like_heuristic_ids"])})</summary>{docs_table}</details>
      <details><summary>Rows using Composio docs as evidence ({len(hygiene_tables["composio_docs_evidence_ids"])})</summary><p>These are useful for Composio integration context, but the assignment asks for official vendor documentation when verifying vendor facts such as auth method, gating, API surface, and MCP support.</p>{composio_table}</details>
    </section>

    <section class="band panel">
      <h2>100-App Operational View</h2>
      <p>This table gives a compact, reviewer-friendly view of every app row and the derived pattern buckets used in the charts.</p>
      {app_table_html}
    </section>
  </div>

  <script>
    const DATA = {payload};
    const COLORS = {{
      self_serve: "#16a34a", gated: "#dc2626", unknown: "#94a3b8",
      "OAuth2": "#2563eb", "OAuth2 + API key": "#7c3aed", "API key / token": "#0f766e", "Basic auth": "#d97706", other: "#64748b",
      Ready: "#16a34a", "Sales/API gate": "#dc2626", "Anti-bot/Captcha": "#ea580c", "Missing docs": "#d97706", "No/limited toolkit": "#7c3aed", "Research failure": "#64748b", "Other blocker": "#94a3b8",
      high: "#16a34a", medium: "#d97706", low: "#dc2626", seed: "#64748b", composio: "#2563eb", web: "#7c3aed",
      mcp_true: "#16a34a", mcp_false: "#dc2626", mcp_unknown: "#94a3b8"
    }};

    function el(id) {{ return document.getElementById(id); }}
    function maxSum(rows, keys) {{ return Math.max(1, ...rows.map(r => keys.reduce((s, k) => s + (r[k] || 0), 0))); }}
    function labelText(text, max=18) {{ return text.length > max ? text.slice(0, max - 1) + "…" : text; }}

    function renderLegend(keys, labels) {{
      return `<div class="legend-note">${{keys.map(k => `<span style="display:inline-flex;align-items:center;margin-right:12px"><span style="width:10px;height:10px;background:${{COLORS[k] || "#64748b"}};display:inline-block;border-radius:2px;margin-right:5px"></span>${{labels?.[k] || k}}</span>`).join("")}}</div>`;
    }}

    function groupedColumns(target, rows, keys, labels) {{
      const w = 760, h = 300, p = {{l:52,r:20,t:18,b:82}};
      const innerW = w - p.l - p.r, innerH = h - p.t - p.b;
      const maxVal = Math.max(1, ...rows.flatMap(r => keys.map(k => r[k] || 0)));
      const groupW = innerW / rows.length;
      const barW = Math.max(4, (groupW - 12) / keys.length);
      let svg = `<svg viewBox="0 0 ${{w}} ${{h}}">`;
      svg += `<line x1="${{p.l}}" y1="${{p.t + innerH}}" x2="${{w - p.r}}" y2="${{p.t + innerH}}" stroke="#cbd5e1"/>`;
      rows.forEach((r, i) => {{
        const gx = p.l + i * groupW + 6;
        keys.forEach((k, j) => {{
          const val = r[k] || 0;
          const bh = val / maxVal * innerH;
          const x = gx + j * barW;
          const y = p.t + innerH - bh;
          svg += `<rect x="${{x}}" y="${{y}}" width="${{barW - 2}}" height="${{bh}}" rx="2" fill="${{COLORS[k]}}"/>`;
          if (val) svg += `<text x="${{x + (barW - 2) / 2}}" y="${{y - 4}}" text-anchor="middle" class="muted-svg">${{val}}</text>`;
        }});
        svg += `<text x="${{gx + groupW/2 - 6}}" y="${{h - 42}}" text-anchor="end" transform="rotate(-35 ${{gx + groupW/2 - 6}} ${{h - 42}})" class="label">${{labelText(r.category, 16)}}</text>`;
      }});
      svg += `</svg>${{renderLegend(keys, labels)}}`;
      target.innerHTML = svg;
    }}

    function stackedHorizontal(target, rows, keys) {{
      const w = 860, rowH = 28, gap = 10, p = {{l:122,r:54,t:14,b:32}};
      const h = p.t + p.b + rows.length * (rowH + gap);
      const innerW = w - p.l - p.r;
      const maxTotal = maxSum(rows, keys);
      let svg = `<svg viewBox="0 0 ${{w}} ${{h}}">`;
      rows.forEach((r, i) => {{
        const y = p.t + i * (rowH + gap);
        svg += `<text x="${{p.l - 8}}" y="${{y + 18}}" text-anchor="end" class="label">${{labelText(r.category, 17)}}</text>`;
        let x = p.l;
        keys.forEach(k => {{
          const val = r[k] || 0;
          const bw = val / maxTotal * innerW;
          if (bw > 0) {{
            svg += `<rect x="${{x}}" y="${{y}}" width="${{bw}}" height="${{rowH}}" fill="${{COLORS[k] || "#64748b"}}" rx="2"/>`;
            if (bw > 20) svg += `<text x="${{x + bw / 2}}" y="${{y + 18}}" text-anchor="middle" fill="#fff" font-size="11">${{val}}</text>`;
          }}
          x += bw;
        }});
      }});
      svg += `</svg>${{renderLegend(keys)}}`;
      target.innerHTML = svg;
    }}

    function stackedColumns(target, rows, keys) {{
      const w = 760, h = 360, p = {{l:46,r:20,t:18,b:88}};
      const innerW = w - p.l - p.r, innerH = h - p.t - p.b;
      const maxTotal = maxSum(rows, keys);
      const colW = innerW / rows.length * .66;
      let svg = `<svg viewBox="0 0 ${{w}} ${{h}}">`;
      svg += `<line x1="${{p.l}}" y1="${{p.t + innerH}}" x2="${{w - p.r}}" y2="${{p.t + innerH}}" stroke="#cbd5e1"/>`;
      rows.forEach((r, i) => {{
        const cx = p.l + i * (innerW / rows.length) + (innerW / rows.length - colW) / 2;
        let y = p.t + innerH;
        keys.forEach(k => {{
          const val = r[k] || 0;
          const bh = val / maxTotal * innerH;
          y -= bh;
          if (bh > 0) svg += `<rect x="${{cx}}" y="${{y}}" width="${{colW}}" height="${{bh}}" fill="${{COLORS[k] || "#64748b"}}" rx="2"/>`;
        }});
        svg += `<text x="${{cx + colW/2}}" y="${{h - 46}}" text-anchor="end" transform="rotate(-35 ${{cx + colW/2}} ${{h - 46}})" class="label">${{labelText(r.category, 15)}}</text>`;
      }});
      svg += `</svg>${{renderLegend(keys)}}`;
      target.innerHTML = svg;
    }}

    function donut(target, items) {{
      const total = items.reduce((s, d) => s + d.value, 0) || 1;
      let offset = 0;
      let segs = "";
      items.forEach(d => {{
        const part = d.value / total * 100;
        segs += `<circle cx="70" cy="70" r="48" fill="none" stroke="${{d.color}}" stroke-width="18" pathLength="100" stroke-dasharray="${{part}} ${{100-part}}" stroke-dashoffset="${{-offset}}" transform="rotate(-90 70 70)"/>`;
        offset += part;
      }});
      target.innerHTML = `<svg viewBox="0 0 430 150"><circle cx="70" cy="70" r="48" fill="none" stroke="#e2e8f0" stroke-width="18"/>${{segs}}<text x="70" y="68" text-anchor="middle" font-size="20" font-weight="800">${{total}}</text><text x="70" y="88" text-anchor="middle" class="muted-svg">total</text>${{items.map((d,i) => `<rect x="155" y="${{25+i*24}}" width="11" height="11" fill="${{d.color}}" rx="2"/><text x="174" y="${{35+i*24}}" class="label">${{d.label}}: ${{d.value}} (${{(d.value*100/total).toFixed(1)}}%)</text>`).join("")}}</svg>`;
    }}

    function lineChart(target) {{
      const points = [{{label:"Pass 1", value: DATA.verification.pass1 || 0}}, {{label:"Pass 2", value: DATA.verification.pass2 || 0}}];
      const w = 520, h = 240, p = {{l:56,r:28,t:26,b:48}};
      const x = i => p.l + i * (w - p.l - p.r);
      const y = v => p.t + (1 - v) * (h - p.t - p.b);
      let svg = `<svg viewBox="0 0 ${{w}} ${{h}}"><line x1="${{p.l}}" y1="${{h-p.b}}" x2="${{w-p.r}}" y2="${{h-p.b}}" stroke="#cbd5e1"/><line x1="${{p.l}}" y1="${{p.t}}" x2="${{p.l}}" y2="${{h-p.b}}" stroke="#cbd5e1"/>`;
      svg += `<path d="M ${{x(0)}} ${{y(points[0].value)}} L ${{x(1)}} ${{y(points[1].value)}}" stroke="#2563eb" stroke-width="4" fill="none"/>`;
      points.forEach((d,i) => {{
        svg += `<circle cx="${{x(i)}}" cy="${{y(d.value)}}" r="8" fill="#2563eb"/><text x="${{x(i)}}" y="${{y(d.value)-15}}" text-anchor="middle" class="title-small">${{(d.value*100).toFixed(1)}}%</text><text x="${{x(i)}}" y="${{h-18}}" text-anchor="middle" class="label">${{d.label}}</text>`;
      }});
      svg += `<text x="${{w/2}}" y="20" text-anchor="middle" class="muted-svg">Strict accuracy, unsure counted as wrong</text></svg>`;
      target.innerHTML = svg;
    }}

    function scatter(target) {{
      const pts = DATA.scatterPoints;
      const w = 560, h = 270, p = {{l:54,r:22,t:20,b:48}};
      const x = v => p.l + v * (w - p.l - p.r);
      const y = v => p.t + (1 - v) * (h - p.t - p.b);
      let svg = `<svg viewBox="0 0 ${{w}} ${{h}}"><line x1="${{p.l}}" y1="${{h-p.b}}" x2="${{w-p.r}}" y2="${{h-p.b}}" stroke="#cbd5e1"/><line x1="${{p.l}}" y1="${{p.t}}" x2="${{p.l}}" y2="${{h-p.b}}" stroke="#cbd5e1"/>`;
      svg += `<text x="${{w/2}}" y="${{h-10}}" text-anchor="middle" class="label">Agent confidence</text><text x="16" y="${{h/2}}" transform="rotate(-90 16 ${{h/2}})" text-anchor="middle" class="label">Actual pass 1 accuracy</text>`;
      svg += `<rect x="${{x(.7)}}" y="${{y(.4)}}" width="${{x(1)-x(.7)}}" height="${{y(0)-y(.4)}}" fill="#fee2e2" opacity=".65"/><text x="${{x(.84)}}" y="${{y(.34)}}" text-anchor="middle" class="muted-svg">high confidence / low accuracy</text>`;
      pts.forEach(d => {{
        svg += `<circle cx="${{x(d.x)}}" cy="${{y(d.accuracy)}}" r="6" fill="${{COLORS[d.confidence] || "#64748b"}}" opacity=".9"><title>${{d.name}}: ${{d.confidence}}, ${{(d.accuracy*100).toFixed(0)}}%</title></circle>`;
      }});
      svg += `</svg>${{renderLegend(["high","medium","low"], {{high:"high confidence", medium:"medium confidence", low:"low confidence"}})}}`;
      target.innerHTML = svg;
    }}

    function treemap(target) {{
      const groups = DATA.breadthByMcp;
      const entries = Object.keys(groups).sort().map(k => ({{breadth:k, ...groups[k], total:Object.values(groups[k]).reduce((a,b)=>a+b,0)}}));
      const total = entries.reduce((s,d) => s + d.total, 0) || 1;
      const w = 560, h = 310;
      let x = 0, svg = `<svg viewBox="0 0 ${{w}} ${{h}}">`;
      entries.forEach(g => {{
        const gw = w * g.total / total;
        let y = 0;
        ["mcp_true","mcp_false","mcp_unknown"].forEach(k => {{
          const val = g[k] || 0;
          const gh = val ? h * val / g.total : 0;
          if (gh > 0) svg += `<rect x="${{x}}" y="${{y}}" width="${{gw}}" height="${{gh}}" fill="${{COLORS[k]}}" stroke="#fff"/><text x="${{x+8}}" y="${{y+20}}" fill="#fff" font-size="12" font-weight="700">${{gh > 26 ? val : ""}}</text>`;
          y += gh;
        }});
        svg += `<text x="${{x+8}}" y="${{h-10}}" fill="#fff" font-size="12" font-weight="800">${{g.breadth}} (${{g.total}})</text>`;
        x += gw;
      }});
      svg += `</svg>${{renderLegend(["mcp_true","mcp_false","mcp_unknown"], {{mcp_true:"MCP claimed", mcp_false:"No MCP", mcp_unknown:"MCP unknown"}})}}`;
      target.innerHTML = svg;
    }}

    groupedColumns(el("accessChart"), DATA.accessByCategory, ["self_serve","gated","unknown"], {{self_serve:"Self-serve", gated:"Gated", unknown:"Unknown"}});
    stackedHorizontal(el("authStacked"), DATA.authByCategory, ["OAuth2","OAuth2 + API key","API key / token","Basic auth","other","unknown"]);
    stackedColumns(el("readinessStacked"), DATA.readinessByCategory, ["Ready","Sales/API gate","Anti-bot/Captcha","Missing docs","No/limited toolkit","Research failure","Other blocker"]);
    treemap(el("treemap"));
    lineChart(el("accuracyLine"));
    scatter(el("scatter"));
    donut(el("effortDonut"), DATA.effortSplit.map((d,i) => ({{...d, color:["#2563eb","#7c3aed","#d97706"][i]}})));
    donut(el("authDonut"), Object.entries(DATA.authCounts).map(([label,value]) => ({{label, value, color: COLORS[label] || "#64748b"}})));
    donut(el("accessDonut"), Object.entries(DATA.accessCounts).map(([label,value]) => ({{label: label.replace("_","-"), value, color: COLORS[label] || "#64748b"}})));
    donut(el("confidenceDonut"), Object.entries(DATA.confidenceCounts).map(([label,value]) => ({{label, value, color: COLORS[label] || "#64748b"}})));
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
