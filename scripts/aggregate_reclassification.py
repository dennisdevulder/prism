#!/usr/bin/env python3
"""Merge LLM reclassification results into the regex-derived labels.

Reads:
  corpus/reclassify_result_{0..3}.json — LLM verdicts per chunk
  corpus/eval_rejections.jsonl         — original regex-derived labels
  corpus/plugins_summarized.jsonl      — to validate cited_existing_slug
Writes:
  corpus/eval_rejections_v2.jsonl      — merged final labels
  corpus/eval_saturation_pairs_v2.jsonl — saturation eval set with gold pairs
"""

import json
from collections import Counter
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
EVAL_PATH = PRISM_ROOT / "corpus" / "eval_rejections.jsonl"
SUMM_PATH = PRISM_ROOT / "corpus" / "plugins_summarized.jsonl"
OUT_LABELS = PRISM_ROOT / "corpus" / "eval_rejections_v2.jsonl"
OUT_PAIRS = PRISM_ROOT / "corpus" / "eval_saturation_pairs_v2.jsonl"


def load_results():
    by_num = {}
    for i in range(4):
        path = PRISM_ROOT / "corpus" / f"reclassify_result_{i}.json"
        if not path.exists():
            print(f"WARN: missing {path}")
            continue
        with open(path) as f:
            for record in json.load(f):
                by_num[record["number"]] = record
    return by_num


def main():
    catalog = {json.loads(l)["slug"] for l in open(SUMM_PATH)}
    llm = load_results()
    print(f"LLM verdicts loaded: {len(llm)}")

    original = [json.loads(l) for l in open(EVAL_PATH)]
    merged = []
    bucket_changes = Counter()
    final_buckets = Counter()
    for rec in original:
        num = rec["number"]
        original_bucket = rec["bucket"]
        if num in llm:
            new = llm[num]
            new_bucket = new["bucket"]
            cited = new.get("cited_existing_slug")
            # Validate cited slug against catalog
            if cited and cited not in catalog:
                cited = None
            rec["bucket"] = new_bucket
            rec["llm_cited_slug"] = cited
            rec["llm_rationale"] = new.get("rationale")
            rec["original_regex_bucket"] = original_bucket
            if original_bucket != new_bucket:
                bucket_changes[(original_bucket, new_bucket)] += 1
        final_buckets[rec["bucket"]] += 1
        merged.append(rec)

    with open(OUT_LABELS, "w") as f:
        for rec in merged:
            f.write(json.dumps(rec) + "\n")

    print()
    print("=== Final bucket distribution ===")
    for k, v in final_buckets.most_common():
        print(f"  {k:<18} {v:>4}")

    print()
    print(f"=== Changes from regex -> LLM ({sum(bucket_changes.values())} total) ===")
    for (old, new), n in sorted(bucket_changes.items(), key=lambda x: -x[1])[:25]:
        print(f"  {old:<15} -> {new:<15} {n}")

    # Build saturation pairs
    saturation_records = [r for r in merged if r["bucket"] == "saturation"]
    pairs = []
    gold_count = 0
    for r in saturation_records:
        cited = r.get("llm_cited_slug")
        pairs.append({
            "number": r["number"],
            "title": r["title"],
            "candidate_slug": r.get("candidate_slug"),
            "cited_existing_slug": cited,
            "rationale": r.get("llm_rationale"),
        })
        if cited:
            gold_count += 1

    with open(OUT_PAIRS, "w") as f:
        for p in pairs:
            f.write(json.dumps(p) + "\n")

    print()
    print(f"=== Saturation eval set ===")
    print(f"  Total saturation rejections: {len(pairs)}")
    print(f"  Gold pairs (with cited_existing_slug in catalog): {gold_count}")
    print()
    print("Gold pairs:")
    for p in pairs:
        if p["cited_existing_slug"]:
            print(f"  #{p['number']:>5}  {p['title'][:48]:<48}  -> {p['cited_existing_slug']}")

    print()
    print(f"Wrote: {OUT_LABELS}")
    print(f"Wrote: {OUT_PAIRS}")


if __name__ == "__main__":
    main()
