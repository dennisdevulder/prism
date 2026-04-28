#!/usr/bin/env python3
"""For each gold-pair rejected PR, extract the source repository URL and
commit hash from the `runelite-github-app` bot comment that posts these
in a standard format.

Bot comment format:
  <!-- rlphc --> New plugin `SLUG`: https://github.com/USER/REPO/tree/COMMIT
  <!-- rlphc --> `SLUG`: https://github.com/USER/REPO/compare/A..B
"""

import json
import re
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
PRS = PRISM_ROOT / "corpus" / "plugin_hub_rejected_prs.jsonl"
GOLD = PRISM_ROOT / "corpus" / "eval_gold_pairs.jsonl"
OUT = PRISM_ROOT / "corpus" / "eval_pair_repos.jsonl"

NEW_PLUGIN = re.compile(
    r"New plugin\s+`([^`]+)`:\s+https://github\.com/([^/]+)/([^/]+)/tree/([0-9a-f]+)",
    re.IGNORECASE,
)
COMPARE = re.compile(
    r"`([^`]+)`:\s+\[[^\]]+\]\(https://github\.com/[^/]+/[^/]+/compare/[^.]+\.\.([0-9a-f]+)",
)
REPO_TREE = re.compile(
    r"https://github\.com/([^/\s)]+)/([^/\s)]+)/tree/([0-9a-f]{7,40})",
)


def extract(pr):
    """Try multiple formats to get (slug, owner, repo, commit)."""
    for c in pr["comments"]["nodes"]:
        login = (c.get("author") or {}).get("login")
        if login != "runelite-github-app":
            continue
        body = c["body"]
        m = NEW_PLUGIN.search(body)
        if m:
            slug, owner, repo, commit = m.groups()
            return {
                "slug": slug,
                "owner": owner,
                "repo": repo,
                "commit": commit,
                "format": "new_plugin",
            }
        # Fallback: any github tree URL
        m = REPO_TREE.search(body)
        if m:
            owner, repo, commit = m.groups()
            return {
                "slug": None,
                "owner": owner,
                "repo": repo,
                "commit": commit,
                "format": "tree_url",
            }
    return None


def main():
    prs_by_num = {p["number"]: p for p in [json.loads(l) for l in open(PRS)]}
    gold = [json.loads(l) for l in open(GOLD)]

    found = 0
    missing = []
    with open(OUT, "w") as out:
        for g in gold:
            pr = prs_by_num.get(g["number"])
            if not pr:
                missing.append((g["number"], "PR not in dataset"))
                continue
            info = extract(pr)
            if not info:
                missing.append((g["number"], g["title"]))
                continue
            record = {
                **g,
                "source": info,
            }
            out.write(json.dumps(record) + "\n")
            found += 1

    print(f"Found repo info for {found}/{len(gold)} gold pairs")
    print()
    if missing:
        print(f"Missing repo info ({len(missing)}):")
        for num, info in missing:
            print(f"  #{num}  {info}")


if __name__ == "__main__":
    main()
