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

    # Pull PR createdAt timestamps so the scorer can flag chronology inversions
    PRISM = Path(__file__).parent.parent
    prs = [json.loads(l) for l in open(PRISM / "corpus" / "plugin_hub_rejected_prs.jsonl")]
    created_by_num = {p["number"]: p.get("createdAt") for p in prs}

    K_VALUES = [1, 3, 5, 10, 25]
    recalls = {k: 0 for k in K_VALUES}
    valid_ranks = []  # only chronologically-valid pairs
    all_ranks = []
    verdicts_correct = {"duplicate": 0, "extension": 0, "novel-extension": 0, "novel": 0}
    verdict_counts = {"duplicate": 0, "extension": 0, "novel-extension": 0, "novel": 0}
    chronologically_valid = 0
    chronology_inversions = []

    print("=" * 110)
    print(f"{'PR#':<8} {'Rejected Plugin':<32} {'Cited Existing':<26} {'Rank':>4} {'Cos':>6} Verdict          Chrono")
    print("-" * 110)

    for rec in eval_caps:
        eval_slug = rec["slug"]
        cited = cited_by_eval_slug.get(eval_slug)
        if not cited:
            continue

        pr_num = int(eval_slug.replace("_eval_", ""))
        pr = {
            "slug": rec["slug"],
            "displayName": rec["displayName"],
            "capabilities": rec["summary"]["capabilities"],
            "createdAt": created_by_num.get(pr_num),
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

        # Chronology check: cited slug must predate the rejected PR
        cited_added = next((c["first_added_at"] for c in candidates if c["slug"] == cited), None)
        pr_created = pr.get("createdAt")
        chrono_status = "?"
        is_inversion = False
        if cited_added and pr_created:
            if cited_added < pr_created:
                chrono_status = "ok"
                chronologically_valid += 1
            else:
                chrono_status = "INVERTED"
                is_inversion = True
                chronology_inversions.append((eval_slug, cited, pr_created, cited_added))

        if rank is not None:
            all_ranks.append(rank)
            if not is_inversion:
                valid_ranks.append(rank)
                for k in K_VALUES:
                    if rank <= k:
                        recalls[k] += 1

        pr_label = f"#{pr_num}"
        rank_str = str(rank) if rank else "—"
        cos_str = f"{cited_cos:.3f}" if cited_cos is not None else "—"
        print(f"{pr_label:<8} {rec['displayName'][:30]:<32} {cited:<26} {rank_str:>4} {cos_str:>6} {verdict:<16} {chrono_status}")

    n = len(eval_caps)
    n_valid = len(valid_ranks)
    print("=" * 110)
    print()
    print(f"Total eval pairs:         {n}")
    print(f"Chronologically valid:    {chronologically_valid}")
    print(f"Chronology inversions:    {len(chronology_inversions)}  (cited 'original' was actually added AFTER the rejected PR)")
    print()
    print(f"Recall @ K (over {n_valid} chronologically-valid pairs):")
    for k in K_VALUES:
        pct = recalls[k] / n_valid * 100 if n_valid else 0
        print(f"  recall@{k:<3}  {recalls[k]:>3}/{n_valid}  ({pct:.0f}%)")
    if valid_ranks:
        mrr = sum(1/r for r in valid_ranks) / n_valid
        print(f"  MRR        {mrr:.3f}")
        print(f"  median rank: {sorted(valid_ranks)[len(valid_ranks)//2]}")
    print()
    print("Verdict distribution (correct = anything except 'novel'):")
    for v, count in verdict_counts.items():
        print(f"  {v:<18} {count}/{n}")
    correct = sum(verdicts_correct.values())
    print(f"  ----")
    print(f"  not-novel rate: {correct}/{n} ({correct/n*100:.0f}%)")
    if chronology_inversions:
        print()
        print("Chronology inversions (these gold pairs have wrong direction):")
        for slug, cited, pr_d, cited_d in chronology_inversions:
            print(f"  {slug}: rejected PR ({pr_d[:10]}) PREDATES cited '{cited}' ({cited_d[:10]})")


if __name__ == "__main__":
    main()
