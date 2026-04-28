#!/usr/bin/env python3
"""For each policy-bucket rejected PR, extract the source repo URL from the
runelite-github-app bot comment and fetch the runelite-plugin.properties.

Output: corpus/eval_policy_manifests.jsonl
  {number, title, regex_bucket, source: {owner, repo, commit}, manifest: {...}, manifest_url}
"""

import json
import re
import urllib.request
import sys
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
PRS = PRISM_ROOT / "corpus" / "plugin_hub_rejected_prs.jsonl"
LABELS = PRISM_ROOT / "corpus" / "eval_rejections_v2.jsonl"
OUT = PRISM_ROOT / "corpus" / "eval_policy_manifests.jsonl"

NEW_PLUGIN = re.compile(
    r"New plugin\s+`([a-z0-9_-]+)`:\s+https://github\.com/([^/\s]+)/([^/\s]+)/tree/([0-9a-f]{7,40})",
    re.IGNORECASE,
)
COMPARE = re.compile(
    r"`([a-z0-9_-]+)`:\s+(?:\[[^\]]*\])?\s*\(?https://github\.com/([^/\s)]+)/([^/\s)]+)/compare/[0-9a-f]+\.\.(?:[a-z0-9_.-]+:)?([0-9a-f]{7,40})",
    re.IGNORECASE,
)
TREE_FALLBACK = re.compile(
    r"https://github\.com/([^/\s)`]+)/([^/\s)`]+)/tree/([0-9a-f]{7,40})",
)


def extract_source(pr):
    for c in pr["comments"]["nodes"]:
        login = (c.get("author") or {}).get("login")
        if login != "runelite-github-app":
            continue
        body = c.get("body", "")
        m = NEW_PLUGIN.search(body)
        if m:
            return m.groups()
        m = COMPARE.search(body)
        if m:
            return m.groups()
        m = TREE_FALLBACK.search(body)
        if m:
            owner, repo, commit = m.groups()
            if (owner.lower(), repo.lower()) in {("runelite", "runelite"), ("runelite", "plugin-hub")}:
                continue
            return (None, owner, repo, commit)
    return None


def fetch(owner, repo, commit):
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{commit}/runelite-plugin.properties"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.read().decode("utf-8", errors="replace"), url
    except Exception:
        return None, None


def parse_props(text):
    fields = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        fields[k.strip()] = v.strip()
    return fields


def main():
    prs_by_num = {p["number"]: p for p in [json.loads(l) for l in open(PRS)]}
    labels = [json.loads(l) for l in open(LABELS)]

    target_buckets = {"policy"}
    targets = [l for l in labels if l["bucket"] in target_buckets]
    print(f"Target PRs: {len(targets)}", file=sys.stderr)

    fetched = 0
    no_source = 0
    fetch_failed = 0
    with open(OUT, "w") as out:
        for label in targets:
            pr = prs_by_num.get(label["number"])
            if not pr:
                continue
            src = extract_source(pr)
            if not src:
                no_source += 1
                continue
            slug, owner, repo, commit = src
            text, url = fetch(owner, repo, commit)
            if not text:
                fetch_failed += 1
                continue
            manifest = parse_props(text)
            record = {
                "number": label["number"],
                "title": label["title"],
                "regex_bucket": label["bucket"],
                "regex_rationale": label.get("llm_rationale") or label.get("matched_snippet"),
                "source": {"slug": slug, "owner": owner, "repo": repo, "commit": commit},
                "manifest": manifest,
                "manifest_url": url,
            }
            out.write(json.dumps(record) + "\n")
            fetched += 1
            if fetched % 10 == 0:
                print(f"  {fetched} fetched...", file=sys.stderr)

    print(f"Fetched: {fetched}/{len(targets)}", file=sys.stderr)
    print(f"No source URL in comments: {no_source}", file=sys.stderr)
    print(f"Fetch 404 / failed: {fetch_failed}", file=sys.stderr)


if __name__ == "__main__":
    main()
