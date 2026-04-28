#!/usr/bin/env python3
"""Sanity check: for each gold pair (rejected_PR, cited_existing), confirm
the cited existing plugin was on plugin-hub BEFORE the rejected PR was
created. Otherwise the gold pair is wrong-direction (the catalog plugin
is the duplicate, not the original).

Reads:
  corpus/plugin_chronology.json
  corpus/plugin_hub_rejected_prs.jsonl (for createdAt timestamps)
  corpus/eval_pair_manifests.jsonl (the 19 actually-evaluated pairs)
"""

import json
from datetime import datetime
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
CHRONO_PATH = PRISM_ROOT / "corpus" / "plugin_chronology.json"
PRS_PATH = PRISM_ROOT / "corpus" / "plugin_hub_rejected_prs.jsonl"
EVAL_PATH = PRISM_ROOT / "corpus" / "eval_pair_manifests.jsonl"


def parse_iso(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main():
    chrono = json.load(open(CHRONO_PATH))
    prs_by_num = {p["number"]: p for p in [json.loads(l) for l in open(PRS_PATH)]}
    pairs = [json.loads(l) for l in open(EVAL_PATH)]

    print(f"{'PR#':<8} {'Rejected':<28} {'Cited Existing':<26} {'PR created':<12} {'Cited added':<12} Status")
    print("-" * 110)

    inversions = []
    valid = []
    missing = []
    for pair in pairs:
        num = pair["number"]
        cited = pair["cited_existing_slug"]
        pr = prs_by_num.get(num)
        pr_created = parse_iso(pr.get("createdAt") if pr else None)
        cited_added = parse_iso(chrono.get(cited, {}).get("first_added_at"))

        if not cited_added:
            status = "NO CHRONO"
            missing.append(pair)
        elif not pr_created:
            status = "NO PR DATE"
            missing.append(pair)
        elif cited_added < pr_created:
            status = "ok (predates)"
            valid.append(pair)
        else:
            status = f"INVERTED — cited added {(cited_added - pr_created).days}d AFTER PR"
            inversions.append((pair, pr_created, cited_added))

        pr_str = pr_created.date().isoformat() if pr_created else "?"
        cited_str = cited_added.date().isoformat() if cited_added else "?"
        print(
            f"#{num:<7} {pair['title'][:26]:<28} {cited:<26} "
            f"{pr_str:<12} {cited_str:<12} {status}"
        )

    print("-" * 110)
    print(f"Valid (cited predates PR):   {len(valid)}/{len(pairs)}")
    print(f"Inverted (cited came later): {len(inversions)}/{len(pairs)}")
    print(f"Missing data:                {len(missing)}/{len(pairs)}")

    if inversions:
        print()
        print("INVERSIONS — these gold pairs have the wrong direction; cited plugin was added AFTER the rejected PR.")
        print("They should be removed from the eval set or have direction flipped.")
        for pair, pr_d, cited_d in inversions:
            print(f"  #{pair['number']}: {pair['title']}")
            print(f"    PR created {pr_d.date()}, cited '{pair['cited_existing_slug']}' added {cited_d.date()}")


if __name__ == "__main__":
    main()
