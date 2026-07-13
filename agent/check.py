import json
from collections import Counter, defaultdict

results = json.load(open("/Users/fuki/Documents/composio/composio-audit/output/results.json"))

by_source = Counter(r.get("researched_via", "seed") for r in results)
by_category_source = defaultdict(Counter)
for r in results:
    by_category_source[r["category"]][r.get("researched_via", "seed")] += 1

print("Overall source breakdown:")
for source, count in by_source.items():
    print(f"  {source}: {count}")

print("\nBy category:")
for category, counts in sorted(by_category_source.items()):
    parts = ", ".join(f"{k}={v}" for k, v in counts.items())
    print(f"  {category}: {parts}")

# List rows sourced via Composio (fast, high-confidence ground truth)
composio_apps = [r["name"] for r in results if r.get("researched_via") == "composio"]
print(f"\nVia Composio ({len(composio_apps)}): {', '.join(composio_apps)}")

# List rows sourced via web search + LLM extraction (needs more scrutiny)
web_apps = [r["name"] for r in results if r.get("researched_via") == "web"]
print(f"\nVia web search ({len(web_apps)}): {', '.join(web_apps)}")

# Flag anything with a stale/unclean run for your honesty section
errored = [r["name"] for r in results if "research_error" in r]
low_conf = [r["name"] for r in results if r.get("confidence") == "low"]
print(f"\nHad a research_error this run: {errored}")
print(f"Low confidence: {low_conf}")