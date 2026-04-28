#!/usr/bin/env python3
"""Evaluate the Risk T0 scorer against:

1. The whole catalog (false-positive rate — these plugins were accepted, so
   most should be compliant; flagged ones are either real abuse-risk plugins
   that the maintainers tolerated, or false positives in our rules)

2. The 87 policy-bucket rejected PRs from the eval set (recall — how many of
   them did the rules catch? Uses PR title + first non-bot comment text as
   the description proxy)
"""

import json
from collections import Counter
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
import sys
sys.path.insert(0, str(PRISM_ROOT / "scripts"))
from risk_scorer import evaluate, load_rules

KNOWN_MAINTAINERS = {
    "riktenx", "tylerwgrass", "raiyni", "1Defence", "cdfisher",
    "pajlada", "Felanbird", "LlemonDuck", "abextm",
    "deathbeam", "hexagonscape", "iProdigy", "Adamcake",
}


def evaluate_catalog():
    print("=" * 80)
    print("FALSE-POSITIVE CHECK: scan all 1659 catalog plugins")
    print("=" * 80)
    summaries = [json.loads(l) for l in open(PRISM_ROOT / "corpus" / "plugins_summarized.jsonl")]
    enriched = {p["slug"]: p for p in [json.loads(l) for l in open(PRISM_ROOT / "corpus" / "plugins_enriched.jsonl")]}
    rules = load_rules()

    verdicts = Counter()
    flagged = []
    for s in summaries:
        manifest = (enriched.get(s["slug"]) or {}).get("manifest", {})
        plugin = {
            "slug": s["slug"],
            "displayName": s.get("displayName"),
            "description": manifest.get("description", ""),
            "capabilities": s["summary"]["capabilities"],
            "tags": manifest.get("tags", ""),
            "manifest": manifest,
        }
        result = evaluate(plugin, rules)
        verdicts[result["verdict"]] += 1
        if result["verdict"] != "compliant":
            flagged.append((s["slug"], result))

    total = len(summaries)
    print(f"Total catalog plugins: {total}")
    for v, n in verdicts.most_common():
        pct = n / total * 100
        print(f"  {v:<22} {n:>4}  ({pct:.1f}%)")

    # Show flagged plugins grouped by rule
    by_rule = Counter()
    for slug, result in flagged:
        for m in result["matched_rules"]:
            by_rule[m["rule_id"]] += 1

    print()
    print("Catalog hits by rule:")
    for rule_id, n in by_rule.most_common():
        print(f"  {rule_id:<35} {n}")

    print()
    print("First 15 flagged catalog plugins (manual review needed):")
    for slug, result in flagged[:15]:
        rules_hit = ", ".join(m["rule_id"] for m in result["matched_rules"])
        print(f"  [{result['verdict']:<17}] {slug:<35} -> {rules_hit}")


def evaluate_rejections():
    print()
    print("=" * 80)
    print("RECALL CHECK: against 87 policy-bucket rejected PRs")
    print("=" * 80)

    prs_by_num = {p["number"]: p for p in [json.loads(l) for l in open(PRISM_ROOT / "corpus" / "plugin_hub_rejected_prs.jsonl")]}
    labels = [json.loads(l) for l in open(PRISM_ROOT / "corpus" / "eval_rejections_v2.jsonl")]
    rules = load_rules()

    policy_prs = [l for l in labels if l["bucket"] == "policy"]
    print(f"Policy-bucket PRs: {len(policy_prs)}")

    hit = 0
    miss = []
    for label in policy_prs:
        pr = prs_by_num[label["number"]]
        # Build description proxy from title + maintainer comments
        title = pr["title"]
        comment_text = ""
        for c in pr["comments"]["nodes"]:
            login = (c.get("author") or {}).get("login")
            # Include EVERYONE for description proxy (the policy text often
            # comes from the maintainer reasoning, not the PR description)
            comment_text += " " + c.get("body", "")

        plugin = {
            "slug": f"_pr_{label['number']}",
            "displayName": title,
            "description": title + " " + comment_text,
            "capabilities": [],
            "tags": "",
            "manifest": {},
        }
        result = evaluate(plugin, rules)
        if result["verdict"] != "compliant":
            hit += 1
        else:
            miss.append((label["number"], title, label.get("llm_rationale", "")))

    print(f"Detected (verdict != compliant): {hit}/{len(policy_prs)} ({hit/len(policy_prs)*100:.0f}%)")
    print()
    print(f"First 10 misses (these policy PRs slipped through the rules):")
    for num, title, rationale in miss[:10]:
        print(f"  #{num} — {title[:60]}")
        if rationale:
            print(f"    LLM rationale: {rationale[:120]}")


def main():
    evaluate_catalog()
    evaluate_rejections()


if __name__ == "__main__":
    main()
