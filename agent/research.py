#!/usr/bin/env python3
"""
Research pipeline: fill null audit fields for apps listed in data/apps.json.

For each app with null fields in output/results_seed.json:
  1. Query the Composio toolkit catalog (same ground truth as the Composio MCP
     COMPOSIO_SEARCH_TOOLS / toolkit metadata APIs) by slug and name.
  2. If a toolkit exists, record auth_method, tools_count_composio, and has_mcp
     from Composio and skip web search.
  3. Otherwise web-search "<app name> API docs", fetch the top result, and
     extract remaining fields from the docs page via LLM.

Results are flushed to output/results.json after every app so a crash does not
lose progress. Re-running skips apps that no longer have null research fields.

Requires: COMPOSIO_API_KEY, OPENAI_API_KEY
Optional: OPENAI_MODEL (default gpt-4.1-mini)
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT / ".env")

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

APPS_PATH = ROOT / "data" / "apps.json"
SEED_PATH = ROOT / "output" / "results_seed.json"
RESULTS_PATH = ROOT / "output" / "results.json"

COMPOSIO_API_BASE = "https://backend.composio.dev/api/v3.1"
REQUEST_TIMEOUT = 30
MAX_PAGE_CHARS = 18_000

RESEARCH_FIELDS = (
    "auth_method",
    "self_serve_or_gated",
    "api_surface",
    "has_mcp",
    "buildability_verdict",
    "blocker",
    "evidence_url",
    "confidence",
)

WEB_EXTRA_FIELDS = ("api_breadth",)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        os.unlink(tmp_name)
        raise


def needs_research(row: dict[str, Any]) -> bool:
    return any(row.get(field) is None for field in RESEARCH_FIELDS)


def slug_candidates(name: str) -> list[str]:
    """Generate likely Composio toolkit slugs from an app display name."""
    stripped = re.sub(r"\s*\([^)]*\)", "", name).strip().lower()
    compact = re.sub(r"[^a-z0-9]", "", stripped)
    underscored = re.sub(r"[^a-z0-9]+", "_", stripped).strip("_")
    dashed = re.sub(r"[^a-z0-9]+", "-", stripped).strip("-")
    parts = [p for p in re.split(r"[\s\-_]+", stripped) if p]
    first_word = parts[0] if parts else stripped

    candidates: list[str] = []
    for value in (compact, underscored, dashed, first_word):
        if value and value not in candidates:
            candidates.append(value)
    return candidates


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


class ComposioCatalog:
    """Read toolkit metadata from the Composio catalog (MCP ground truth)."""

    def __init__(self, api_key: str) -> None:
        self.session = requests.Session()
        self.session.headers.update({"x-api-key": api_key})

    def get_by_slug(self, slug: str) -> dict[str, Any] | None:
        resp = self.session.get(
            f"{COMPOSIO_API_BASE}/toolkits/{slug}",
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        resp = self.session.get(
            f"{COMPOSIO_API_BASE}/toolkits",
            params={"search": query, "limit": limit},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("items") or []

    def find_toolkit(self, app_name: str) -> dict[str, Any] | None:
        for slug in slug_candidates(app_name):
            toolkit = self.get_by_slug(slug)
            if toolkit:
                return toolkit

        target = normalize_name(app_name)
        for item in self.search(app_name):
            if normalize_name(item.get("name", "")) == target:
                return self.get_by_slug(item["slug"]) or item
            if normalize_name(item.get("slug", "")) == target:
                return self.get_by_slug(item["slug"]) or item

        # Loose contains match when search returns a single strong hit.
        hits = self.search(app_name)
        if len(hits) == 1:
            only = hits[0]
            if target in normalize_name(only.get("name", "")) or target in normalize_name(
                only.get("slug", "")
            ):
                return self.get_by_slug(only["slug"]) or only
        return None


def format_auth_method(toolkit: dict[str, Any]) -> str:
    if toolkit.get("no_auth"):
        return "none"

    details = toolkit.get("auth_config_details") or []
    labels: list[str] = []
    for detail in details:
        label = detail.get("name") or detail.get("mode") or ""
        label = label.replace("_", " ").strip()
        if not label:
            continue
        normalized = label.title()
        if normalized.lower() in {"oauth2", "oauth 2", "oauth 2.0"}:
            normalized = "OAuth2"
        elif normalized.lower() == "api key":
            normalized = "API key"
        labels.append(normalized)

    if not labels:
        schemes = toolkit.get("composio_managed_auth_schemes") or []
        if schemes:
            return ", ".join(str(s).replace("_", " ").title() for s in schemes)
        return "unknown"

    primary = labels[0]
    if len(labels) == 1:
        return primary
    extras = ", ".join(labels[1:])
    return f"{primary} (also {extras})"


def extract_from_composio(toolkit: dict[str, Any]) -> dict[str, Any]:
    meta = toolkit.get("meta") or {}
    tools_count = meta.get("tools_count", toolkit.get("tools_count"))
    docs_url = f"https://docs.composio.dev/toolkits/{toolkit.get('slug')}"
    slug = toolkit.get("slug")

    if tools_count is not None:
        api_surface = (
            f"Wrapped by Composio as {tools_count} agent-callable tools "
            f"(managed via Composio's toolkit catalog for '{slug}')"
        )
    else:
        api_surface = f"Wrapped by Composio's toolkit catalog for '{slug}'"

    # A toolkit with 0 registered tools is not a usable agent toolkit today,
    # regardless of whether Composio "knows about" the app. Verification pass
    # 1 caught this exact contradiction on Front (0 tools, but verdict said
    # "yes, buildable") — guard against repeating it for any app.
    if tools_count == 0:
        buildability_verdict = (
            "Partial - Composio has a toolkit entry for this app but it "
            "currently exposes 0 agent-callable tools"
        )
        blocker = "Composio toolkit exists but has no tools registered yet"
    else:
        buildability_verdict = "Yes - already an agent toolkit today via Composio"
        blocker = "none"

    return {
        "auth_method": format_auth_method(toolkit),
        # A Composio toolkit existing means Composio already offers managed
        # auth for it, i.e. a developer can get credentials without going
        # through a partner/approval gate. That is the definition of
        # self-serve for this audit.
        "self_serve_or_gated": "self-serve",
        "api_surface": api_surface,
        "tools_count_composio": tools_count,
        "has_mcp": True,
        "buildability_verdict": buildability_verdict,
        "blocker": blocker,
        # Pass-1 verification found every Composio-sourced evidence_url was
        # landing on the app's marketing homepage (attio.com, klaviyo.com,
        # xero.com, ...) via Composio's own `meta.app_url` field, which is
        # NOT developer docs. Composio's toolkit page for this app is the
        # actual ground truth we used to fill this row, so it is stronger,
        # more honest evidence than a homepage guess — use it directly.
        "evidence_url": docs_url,
        "composio_docs_url": docs_url,
        "confidence": "high",
        "researched_via": "composio",
        "composio_toolkit_slug": slug,
        "researched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# Ad networks, redirectors, and link-tracking domains that occasionally
# outrank real docs pages for branded queries. A hit from any of these is
# not evidence of anything about the app itself and must never be treated
# as a docs URL.
BLOCKED_RESULT_DOMAINS = (
    "bing.com/aclick",
    "doubleclick.net",
    "googleadservices.com",
    "googlesyndication.com",
    "ad.doubleclick.net",
    "duckduckgo.com/y.js",
)


def is_blocked_result(url: str) -> bool:
    return any(blocked in url for blocked in BLOCKED_RESULT_DOMAINS)


def search_web(query: str) -> str | None:
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # fallback: old frozen package
        except ImportError as exc:
            raise RuntimeError(
                "No DuckDuckGo search package found. "
                "Install with: pip install ddgs"
            ) from exc

    with DDGS() as ddgs:
        for result in ddgs.text(query, max_results=8):
            href = result.get("href") or result.get("url")
            if not href or not href.startswith("http"):
                continue
            if is_blocked_result(href):
                continue
            return href
    return None


def fetch_page_text(url: str) -> str:
    resp = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "composio-audit-research/1.0"},
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:MAX_PAGE_CHARS]


def extract_from_docs(
    client: OpenAI,
    *,
    app: dict[str, Any],
    evidence_url: str,
    page_text: str,
    model: str,
) -> dict[str, Any]:
    schema = {
        "auth_method": "string|null",
        "self_serve_or_gated": "self-serve|gated|unknown|null",
        "api_surface": "string|null",
        "api_breadth": "none|narrow|moderate|broad|unknown|null",
        "has_mcp": "boolean|null",
        "buildability_verdict": "string|null",
        "blocker": "string|null",
        "confidence": "high|medium|low",
    }
    prompt = f"""
You are auditing whether an app can become a Composio agent toolkit.

App: {app["name"]}
Category: {app.get("category")}
Hint URL/domain: {app.get("hint")}
Evidence URL fetched: {evidence_url}

Extract ONLY what the documentation directly supports. Use null when unknown.
Set confidence to:
- high: docs explicitly state auth, API availability, and access model
- medium: partial or inferred from secondary sections
- low: sparse/ambiguous page or mostly marketing copy

Return strict JSON with keys:
{json.dumps(schema, indent=2)}

Documentation excerpt:
---
{page_text}
---
""".strip()

    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Return concise audit fields as JSON. "
                    "Prefer official developer docs over marketing language."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    data["evidence_url"] = evidence_url
    data["researched_via"] = "web"
    data["researched_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return data


def research_via_web(
    client: OpenAI,
    app: dict[str, Any],
    *,
    model: str,
) -> dict[str, Any]:
    query = f'{app["name"]} API docs'
    evidence_url = search_web(query)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if not evidence_url:
        return {
            "auth_method": None,
            "self_serve_or_gated": None,
            "api_surface": None,
            "api_breadth": None,
            "has_mcp": None,
            "buildability_verdict": "Unknown - no API docs found in web search",
            "blocker": "no public API docs found",
            "evidence_url": None,
            "confidence": "low",
            "researched_via": "web",
            "researched_at": now,
            "research_error": f"No search results for query: {query}",
        }

    try:
        page_text = fetch_page_text(evidence_url)
    except requests.RequestException as exc:
        return {
            "auth_method": None,
            "self_serve_or_gated": None,
            "api_surface": None,
            "api_breadth": None,
            "has_mcp": None,
            "buildability_verdict": "Unknown - docs URL found but fetch failed",
            "blocker": "could not fetch docs page",
            "evidence_url": evidence_url,
            "confidence": "low",
            "researched_via": "web",
            "researched_at": now,
            "research_error": str(exc),
        }

    if len(page_text.strip()) < 200:
        host = urlparse(evidence_url).netloc
        return {
            "auth_method": None,
            "self_serve_or_gated": None,
            "api_surface": None,
            "api_breadth": None,
            "has_mcp": None,
            "buildability_verdict": "Unknown - docs page had insufficient text",
            "blocker": "empty or JS-rendered docs page",
            "evidence_url": evidence_url,
            "confidence": "low",
            "researched_via": "web",
            "researched_at": now,
            "research_error": f"Fetched page from {host} contained <200 chars of text",
        }

    return extract_from_docs(
        client,
        app=app,
        evidence_url=evidence_url,
        page_text=page_text,
        model=model,
    )


def merge_row(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Apply the outcome of one research attempt onto an existing row.

    `patch` always represents the freshest attempt at researching this app,
    so its fields win outright — including explicit Nones, which mean "this
    attempt could not determine this field", not "leave whatever was there
    before". This matters because a prior run may have left stale data next
    to a stale research_error; without this, a later successful patch could
    never clear that leftover error message.
    """
    merged = dict(base)
    for key, value in patch.items():
        merged[key] = value

    # A patch with no research_error means this attempt did not hit the
    # failure paths in research_via_web / extract_from_composio, so any
    # research_error left over from an earlier failed attempt is stale.
    if "research_error" not in patch and "research_error" in merged:
        del merged["research_error"]

    return merged


def build_initial_rows(apps: list[dict[str, Any]], seed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seed_by_id = {row["id"]: row for row in seed_rows}
    rows: list[dict[str, Any]] = []
    for app in apps:
        seed = seed_by_id.get(app["id"], {})
        row = {
            "id": app["id"],
            "name": app["name"],
            "category": app["category"],
            "hint": app.get("hint"),
        }
        row.update({k: v for k, v in seed.items() if k not in row or seed.get(k) is not None})
        rows.append(row)
    rows.sort(key=lambda item: item["id"])
    return rows


def load_or_init_results(apps: list[dict[str, Any]], seed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if RESULTS_PATH.exists():
        existing = load_json(RESULTS_PATH)
        if isinstance(existing, list) and existing:
            by_id = {row["id"]: row for row in existing if "id" in row}
            initial = build_initial_rows(apps, seed_rows)
            merged: list[dict[str, Any]] = []
            for row in initial:
                merged.append(merge_row(row, by_id.get(row["id"], {})))
            return merged
    return build_initial_rows(apps, seed_rows)


def print_progress(done: int, total: int, via_composio: int, via_web: int) -> None:
    print(f"{done}/{total} done, {via_composio} via Composio, {via_web} via web search")


def main() -> int:
    composio_api_key = os.getenv("COMPOSIO_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not composio_api_key:
        print("COMPOSIO_API_KEY is required", file=sys.stderr)
        return 1
    if not openai_api_key:
        print("OPENAI_API_KEY is required for web-research extraction", file=sys.stderr)
        return 1

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    apps = load_json(APPS_PATH)
    seed_rows = load_json(SEED_PATH)
    results = load_or_init_results(apps, seed_rows)

    pending = [row for row in results if needs_research(row)]
    total = len(pending)
    if total == 0:
        print("Nothing to research — all apps already have required fields.")
        save_json_atomic(RESULTS_PATH, results)
        return 0

    catalog = ComposioCatalog(composio_api_key)
    llm = OpenAI(api_key=openai_api_key)

    done = 0
    via_composio = 0
    via_web = 0

    for index, row in enumerate(results, start=1):
        if not needs_research(row):
            continue

        app = next(item for item in apps if item["id"] == row["id"])
        print(f"[{row['id']}/{len(apps)}] {row['name']} …", flush=True)

        toolkit = catalog.find_toolkit(app["name"])
        if toolkit:
            patch = extract_from_composio(toolkit)
            via_composio += 1
        else:
            patch = research_via_web(llm, app, model=model)
            via_web += 1
            time.sleep(0.5)

        results[index - 1] = merge_row(row, patch)
        save_json_atomic(RESULTS_PATH, results)

        done += 1
        if done % 10 == 0 or done == total:
            print_progress(done, total, via_composio, via_web)

    print_progress(done, total, via_composio, via_web)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())