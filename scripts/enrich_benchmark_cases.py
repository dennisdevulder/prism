#!/usr/bin/env python3
"""Turn labeled rejection corpus into benchmark-case candidates.

Reads corpus/eval_rejections_v2.jsonl + corpus/plugin_hub_rejected_prs.jsonl,
extracts the rlphc bot's `owner/repo/tree/commit` reference, fetches the
manifest at that commit, and emits one candidate per PR in cases.json shape.

The output is a *candidate* set — a human still picks which ones land in
benchmarks/cases/cases.json. Junk filters: PRs with no fetchable manifest,
PRs without a clear repo reference, PRs labeled ambiguous/no_signal.
"""

import json
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent

REJECTIONS = PRISM_ROOT / "corpus" / "eval_rejections_v2.jsonl"
PRS = PRISM_ROOT / "corpus" / "plugin_hub_rejected_prs.jsonl"
OUT = PRISM_ROOT / "corpus" / "benchmark_candidates.jsonl"

REPO_RE = re.compile(r"https://github\.com/([^/\s]+)/([^/\s]+)/tree/([0-9a-f]{6,40})")

KEEP_BUCKETS = {"policy", "saturation", "code_quality"}


def fetch_manifest(owner, repo, commit):
    """Fetch the `runelite-plugin.properties` from raw.githubusercontent.com.

    Returns parsed key/value dict, or None if the file isn't reachable.
    """
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{commit}/runelite-plugin.properties"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None
    fields = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        fields[k.strip()] = v.strip()
    return fields


def reason_from_snippet(snippet, bucket):
    """Coarse classifier: from the matched comment text, guess the rule."""
    s = (snippet or "").lower()
    if "reflection" in s:
        return "reflection"
    if "third-party client" in s or "jagex" in s and "guideline" in s:
        return "jagex_3pc_guidelines"
    if "rejected-or-rolled-back" in s or "rejected features" in s:
        return "rejected_features_wiki"
    if "takeover" in s:
        return "takeover_policy"
    if "duplicate" in s or bucket == "saturation":
        return "saturation_duplicate"
    if "build" in s and "fail" in s:
        return "build_failure"
    return f"{bucket}_unspecified"


def extract_repo_ref(pr):
    """Pull (owner, repo, commit) out of the rlphc bot comment, if present."""
    comments = (pr.get("comments") or {}).get("nodes") or []
    for c in comments:
        body = c.get("body") or ""
        match = REPO_RE.search(body)
        if match:
            return match.group(1), match.group(2), match.group(3)
    return None, None, None


def main():
    # Index PRs by number
    pr_by_number = {}
    with open(PRS) as f:
        for line in f:
            pr = json.loads(line)
            pr_by_number[pr["number"]] = pr

    # Walk rejections, enrich keep-bucket entries with repo + manifest
    candidates = []
    bucket_counts = Counter()
    skipped_no_repo = 0
    skipped_no_manifest = 0
    for line in open(REJECTIONS):
        rej = json.loads(line)
        bucket = rej.get("bucket")
        if bucket not in KEEP_BUCKETS:
            continue
        pr = pr_by_number.get(rej["number"])
        if not pr:
            continue
        owner, repo, commit = extract_repo_ref(pr)
        if not owner:
            skipped_no_repo += 1
            continue
        manifest = fetch_manifest(owner, repo, commit)
        if manifest is None:
            skipped_no_manifest += 1
            continue
        slug = (rej.get("candidate_slug") or "").strip() or None
        if not slug:
            files = (pr.get("files") or {}).get("nodes") or []
            for f in files:
                p = f.get("path") or ""
                if p.startswith("plugins/"):
                    slug = p.split("/", 2)[1]
                    break
        rejection_reason = reason_from_snippet(rej.get("matched_snippet"), bucket)
        candidates.append({
            "id": f"pr_{rej['number']}_{(slug or 'unknown').replace('-', '_')}",
            "pr": rej["number"],
            "title": rej.get("title") or pr.get("title"),
            "bucket": bucket,
            "rejection_type": "policy_violation" if bucket == "policy" else bucket,
            "rejection_reason": rejection_reason,
            "matched_snippet": (rej.get("matched_snippet") or "")[:300],
            "matched_by": rej.get("matched_by"),
            "manifest": {
                "displayName": manifest.get("displayName", ""),
                "description": manifest.get("description", ""),
                "tags": manifest.get("tags", ""),
            },
            "source": {
                "owner": owner,
                "repo": repo,
                "commit": commit,
            },
        })
        bucket_counts[bucket] += 1
        sys.stderr.write(f"  ✓ #{rej['number']:5d} {bucket:15s} {rejection_reason}\n")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        for c in candidates:
            f.write(json.dumps(c) + "\n")

    sys.stderr.write(f"\nWrote {len(candidates)} candidates to {OUT}\n")
    sys.stderr.write(f"  Skipped: no_repo={skipped_no_repo} no_manifest={skipped_no_manifest}\n")
    for b, n in bucket_counts.most_common():
        sys.stderr.write(f"  {b:15s} {n}\n")


if __name__ == "__main__":
    main()
