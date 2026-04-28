#!/usr/bin/env python3
"""
Saturation scorer.

Scores a plugin-like PR against the catalog and emits a verdict plus the
nearest-neighbour structured diff. Pure logic over the prebuilt index — no
network calls, no LLM. Capability extraction for a new PR is a separate
concern (Haiku-driven) that produces input matching the schema below.

PR input schema:
  {
    "slug": "<slug>",
    "displayName": "<name>",
    "description": "<text>",          # optional, used for fallback signals
    "tags": "<comma-separated>",      # optional
    "capabilities": ["cap-1", ...]    # required for the cosine path
  }

Output:
  {
    "verdict": "duplicate" | "extension" | "novel-extension" | "novel",
    "rationale": "<one-line explanation>",
    "top_neighbours": [
      {slug, displayName, cosine, slug_exact, displayname_ngram_jaccard,
       shared, pr_only},
      ...
    ]
  }
"""

import argparse
import json
import math
import sys
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
INDEX_PATH = PRISM_ROOT / "corpus" / "saturation_index.jsonl"
IDF_PATH = PRISM_ROOT / "corpus" / "capability_idf.json"
SUMMARIES_PATH = PRISM_ROOT / "corpus" / "plugins_summarized.jsonl"


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def load_idf(path):
    with open(path) as f:
        return json.load(f)


def cosine_similarity(vec_a, vec_b):
    """IDF-weighted cosine over sparse capability vectors."""
    if not vec_a or not vec_b:
        return 0.0
    keys = set(vec_a) | set(vec_b)
    dot = sum(vec_a.get(k, 0.0) * vec_b.get(k, 0.0) for k in keys)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def displayname_ngrams(name, n=3):
    name = "".join(c for c in (name or "").lower() if c.isalnum())
    if len(name) < n:
        return {name} if name else set()
    return {name[i:i + n] for i in range(len(name) - n + 1)}


def jaccard(a, b):
    if not a and not b:
        return 0.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def to_idf_vector(capabilities, idf_weights):
    return {c: idf_weights.get(c, {}).get("idf", 0.0) for c in capabilities}


def score_against_entry(pr, entry, idf_weights):
    pr_caps = set(pr.get("capabilities", []))
    entry_caps = set(entry.get("capabilities", []))

    pr_vec = to_idf_vector(pr_caps, idf_weights)
    entry_vec = entry.get("idf_weighted_vector") or to_idf_vector(entry_caps, idf_weights)

    pr_ngrams = displayname_ngrams(pr.get("displayName", ""))
    entry_ngrams = displayname_ngrams(entry.get("displayName", ""))

    return {
        "slug": entry["slug"],
        "displayName": entry.get("displayName", ""),
        "slug_exact": pr["slug"] == entry["slug"],
        "displayname_ngram_jaccard": jaccard(pr_ngrams, entry_ngrams),
        "cosine": cosine_similarity(pr_vec, entry_vec),
        "shared": sorted(pr_caps & entry_caps),
        "pr_only": sorted(pr_caps - entry_caps),
    }


def decide_verdict(top, pr_caps):
    """Threshold-based verdict from the top-1 neighbour.

    Thresholds are initial guesses — they need calibration against the
    disabled/warning eval set before being trusted in production.
    """
    if top is None:
        return "novel", "catalog empty"

    if top["slug_exact"]:
        return "duplicate", f"exact slug match against {top['slug']}"

    cos = top["cosine"]
    novel_caps = top["pr_only"]
    name_overlap = top["displayname_ngram_jaccard"]

    if cos >= 0.9 and len(novel_caps) == 0:
        return "duplicate", (
            f"cosine {cos:.2f} ≥ 0.9 with no novel capabilities vs {top['slug']}"
        )
    if cos >= 0.5 and len(novel_caps) == 0:
        return "extension", (
            f"cosine {cos:.2f} but no novel capabilities vs {top['slug']}"
        )
    if cos >= 0.5 and len(novel_caps) > 0:
        return "novel-extension", (
            f"cosine {cos:.2f} vs {top['slug']}, adds novel: {novel_caps}"
        )
    if name_overlap >= 0.5 and not pr_caps:
        return "novel-extension", (
            f"name overlap {name_overlap:.2f} vs {top['slug']} (no caps to compare)"
        )
    return "novel", f"cosine {cos:.2f} < 0.5 — no close match in catalog"


def score_pr(pr, index, idf_weights, k=5, exclude_slug=None):
    candidates = [
        score_against_entry(pr, entry, idf_weights)
        for entry in index
        if exclude_slug is None or entry["slug"] != exclude_slug
    ]
    candidates.sort(key=lambda c: c["cosine"], reverse=True)
    top_k = candidates[:k]
    top = top_k[0] if top_k else None
    verdict, rationale = decide_verdict(top, pr.get("capabilities", []))
    return {
        "verdict": verdict,
        "rationale": rationale,
        "top_neighbours": top_k,
    }


def format_result(pr, result):
    lines = [
        f"PR: {pr['slug']} — {pr.get('displayName', '')}",
        f"  capabilities: {pr.get('capabilities', [])}",
        f"VERDICT: {result['verdict'].upper()}",
        f"  rationale: {result['rationale']}",
        "  top neighbours:",
    ]
    for n in result["top_neighbours"]:
        lines.append(
            f"    - {n['slug']:<40} "
            f"cos={n['cosine']:.3f} "
            f"name={n['displayname_ngram_jaccard']:.2f} "
            f"shared={n['shared']} "
            f"pr_only={n['pr_only']}"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--slug",
        help="Leave-one-out: test using an existing plugin's data.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="JSON file describing a new PR (PR input schema in module docstring).",
    )
    parser.add_argument("--k", type=int, default=5, help="Neighbours to return.")
    parser.add_argument(
        "--json", action="store_true", help="Emit raw JSON instead of formatted text."
    )
    args = parser.parse_args()

    if not args.slug and not args.input:
        parser.error("Provide --slug (leave-one-out) or --input <file>")

    index = load_jsonl(INDEX_PATH)
    idf = load_idf(IDF_PATH)

    if args.slug:
        summaries = load_jsonl(SUMMARIES_PATH)
        by_slug = {s["slug"]: s for s in summaries}
        if args.slug not in by_slug:
            print(f"Slug not found: {args.slug}", file=sys.stderr)
            sys.exit(1)
        s = by_slug[args.slug]
        pr = {
            "slug": s["slug"],
            "displayName": s["displayName"],
            "capabilities": s["summary"]["capabilities"],
        }
        exclude = args.slug
    else:
        with open(args.input) as f:
            pr = json.load(f)
        exclude = None

    result = score_pr(pr, index, idf, k=args.k, exclude_slug=exclude)

    if args.json:
        print(json.dumps({"pr": pr, "result": result}, indent=2))
    else:
        print(format_result(pr, result))


if __name__ == "__main__":
    main()
