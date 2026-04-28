#!/usr/bin/env python3
"""Evaluate T0 saturation matching against the gold-pair eval set.

For each rejected PR with capabilities:
1. Score against the full catalog
2. Find the rank of the cited existing plugin in the neighbour list
3. Compute recall@1, @3, @5, @10 + MRR + verdict-correctness

Inputs:
  /tmp/eval_capabilities.jsonl — rejected plugin records {slug, displayName, summary{capabilities,category}}
  corpus/eval_pair_manifests.jsonl — links rejected slug back to cited_existing_slug
  corpus/saturation_index.jsonl + corpus/capability_idf.json — catalog

Outputs to stdout:
  - per-pair: rank of cited plugin, top-3 neighbours, verdict
  - aggregate: recall@K, MRR, verdict accuracy
"""

import json
import sys
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PRISM_ROOT / "scripts"))

from saturation_scorer import (
    load_jsonl, load_idf, score_against_entry, decide_verdict
)


def main():
    index = load_jsonl(PRISM_ROOT / "corpus" / "saturation_index.jsonl")
    idf = load_idf(PRISM_ROOT / "corpus" / "capability_idf.json")

    eval_caps = [json.loads(l) for l in open("/tmp/eval_capabilities.jsonl")]
    pair_manifests = [json.loads(l) for l in open(PRISM_ROOT / "corpus" / "eval_pair_manifests.jsonl")]

    # Map by PR number, e.g. _eval_9305 -> cited_existing_slug
    cited_by_eval_slug = {}
    title_by_eval_slug = {}
    for pm in pair_manifests:
        eval_slug = f"_eval_{pm['number']}"
        cited_by_eval_slug[eval_slug] = pm["cited_existing_slug"]
        title_by_eval_slug[eval_slug] = pm["title"]

    K_VALUES = [1, 3, 5, 10, 25]
    recalls = {k: 0 for k in K_VALUES}
    ranks = []
    verdicts_correct = {"duplicate": 0, "extension": 0, "novel-extension": 0, "novel": 0}
    verdict_counts = {"duplicate": 0, "extension": 0, "novel-extension": 0, "novel": 0}
    cited_cosines = []

    print("=" * 100)
    print(f"{'PR#':<8} {'Rejected Plugin':<32} {'Cited Existing':<26} {'Rank':>4} {'Cos':>6} Verdict")
    print("-" * 100)

    for rec in eval_caps:
        eval_slug = rec["slug"]
        cited = cited_by_eval_slug.get(eval_slug)
        if not cited:
            continue

        pr = {
            "slug": rec["slug"],
            "displayName": rec["displayName"],
            "capabilities": rec["summary"]["capabilities"],
        }
        # Score against everything
        candidates = [score_against_entry(pr, e, idf) for e in index]
        candidates.sort(key=lambda c: c["cosine"], reverse=True)

        # Find rank of cited
        rank = None
        cited_cos = None
        for i, c in enumerate(candidates, start=1):
            if c["slug"] == cited:
                rank = i
                cited_cos = c["cosine"]
                break

        # Verdict (top-1 logic)
        top = candidates[0]
        verdict, _ = decide_verdict(top, pr["capabilities"])
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        # Correct if not "novel" (since these are real saturation rejections)
        if verdict != "novel":
            verdicts_correct[verdict] = verdicts_correct.get(verdict, 0) + 1

        if rank is not None:
            ranks.append(rank)
            for k in K_VALUES:
                if rank <= k:
                    recalls[k] += 1
            cited_cosines.append(cited_cos)

        pr_num = eval_slug.replace("_eval_", "#")
        rank_str = str(rank) if rank else "—"
        cos_str = f"{cited_cos:.3f}" if cited_cos is not None else "—"
        print(f"{pr_num:<8} {rec['displayName'][:30]:<32} {cited:<26} {rank_str:>4} {cos_str:>6} {verdict}")

    n = len(eval_caps)
    n_with_rank = len(ranks)
    print("=" * 100)
    print()
    print(f"Total eval pairs: {n}")
    print(f"Pairs where cited slug found anywhere in catalog: {n_with_rank}")
    print()
    print("Recall @ K:")
    for k in K_VALUES:
        pct = recalls[k] / n * 100
        print(f"  recall@{k:<3}  {recalls[k]:>3}/{n}  ({pct:.0f}%)")
    if ranks:
        mrr = sum(1/r for r in ranks) / n
        print(f"  MRR       {mrr:.3f}")
        print(f"  median rank: {sorted(ranks)[len(ranks)//2]}")
    print()
    print("Verdict distribution (correct = anything except 'novel'):")
    for v, count in verdict_counts.items():
        print(f"  {v:<18} {count}/{n}")
    correct = sum(verdicts_correct.values())
    print(f"  ----")
    print(f"  not-novel rate: {correct}/{n} ({correct/n*100:.0f}%)")


if __name__ == "__main__":
    main()
