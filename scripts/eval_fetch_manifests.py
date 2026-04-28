#!/usr/bin/env python3
"""For each gold pair with repo info, fetch its runelite-plugin.properties
file from raw.githubusercontent.com.

Output: corpus/eval_pair_manifests.jsonl, one record per pair with the
parsed manifest fields.
"""

import json
import urllib.request
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
PAIRS_PATH = PRISM_ROOT / "corpus" / "eval_pair_repos.jsonl"
EXTRAS_PATH = PRISM_ROOT / "corpus" / "eval_pair_repos_extras.json"
GOLD_PATH = PRISM_ROOT / "corpus" / "eval_gold_pairs.jsonl"
OUT_PATH = PRISM_ROOT / "corpus" / "eval_pair_manifests.jsonl"

USELESS_REPOS = {("runelite", "runelite"), ("runelite", "plugin-hub"),
                 ("notifications", "unsubscribe-auth")}


def parse_properties(text):
    fields = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        fields[k.strip()] = v.strip()
    return fields


def fetch_manifest(owner, repo, commit):
    """Try to fetch runelite-plugin.properties from a specific repo+commit."""
    refs = [commit] if commit else ["master", "main"]
    for ref in refs:
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/runelite-plugin.properties"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                return resp.read().decode("utf-8", errors="replace"), url
        except Exception:
            continue
    return None, None


def main():
    gold = {g["number"]: g for g in [json.loads(l) for l in open(GOLD_PATH)]}
    initial = [json.loads(l) for l in open(PAIRS_PATH)]
    extras = json.load(open(EXTRAS_PATH))

    # Build merged list of (gold pair + repo info)
    pair_map = {p["number"]: p for p in initial}
    for num_str, info in extras.items():
        num = int(num_str)
        if (info["owner"], info["repo"]) in USELESS_REPOS:
            continue
        if num not in pair_map:
            pair_map[num] = {**gold[num], "source": info}

    print(f"Total pairs to fetch: {len(pair_map)}")

    fetched = 0
    failed = []
    with open(OUT_PATH, "w") as out:
        for num, p in pair_map.items():
            src = p["source"]
            text, url = fetch_manifest(src["owner"], src["repo"], src["commit"])
            if text is None:
                failed.append(num)
                continue
            manifest = parse_properties(text)
            record = {
                **p,
                "manifest": manifest,
                "manifest_url": url,
            }
            out.write(json.dumps(record) + "\n")
            fetched += 1

    print(f"Fetched {fetched} manifests")
    if failed:
        print(f"Failed: {failed}")


if __name__ == "__main__":
    main()
