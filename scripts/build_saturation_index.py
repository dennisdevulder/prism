#!/usr/bin/env python3
"""Rebuild corpus/saturation_index.jsonl with attribution fields.

For each plugin in plugins_summarized.jsonl, enrich the entry with:
- displayName
- first_added_at, first_added_by (from plugin_chronology.json)
- original_authors (from plugins_enriched.jsonl manifest.author + plugins.jsonl authors)

This way, when the saturation scorer flags a new PR as duplicating an
existing plugin, the verdict carries the original author + first-added
date, so credit goes to whoever did it first.
"""

import json
import math
from collections import Counter
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
SUMM_PATH = PRISM_ROOT / "corpus" / "plugins_summarized.jsonl"
ENRICHED_PATH = PRISM_ROOT / "corpus" / "plugins_enriched.jsonl"
PLUGINS_PATH = PRISM_ROOT / "corpus" / "plugins.jsonl"
CHRONO_PATH = PRISM_ROOT / "corpus" / "plugin_chronology.json"
IDF_PATH = PRISM_ROOT / "corpus" / "capability_idf.json"
OUT = PRISM_ROOT / "corpus" / "saturation_index.jsonl"


def to_idf_vector(caps, idf_weights):
    return {c: idf_weights.get(c, {}).get("idf", 0.0) for c in caps}


def split_authors(s):
    if not s:
        return []
    return [a.strip() for a in s.replace(";", ",").split(",") if a.strip()]


def main():
    summaries = [json.loads(l) for l in open(SUMM_PATH)]
    enriched = {p["slug"]: p for p in [json.loads(l) for l in open(ENRICHED_PATH)]}
    plugins = {p["slug"]: p for p in [json.loads(l) for l in open(PLUGINS_PATH)]}
    chronology = json.load(open(CHRONO_PATH))

    # Recompute IDF over current capability vocab to keep it consistent
    capability_doc_count = Counter()
    for s in summaries:
        for c in set(s["summary"]["capabilities"]):
            capability_doc_count[c] += 1
    total = len(summaries)
    idf_weights = {
        cap: {
            "idf": math.log(total / dc),
            "doc_count": dc,
            "doc_frequency": dc / total,
        }
        for cap, dc in capability_doc_count.items()
    }
    with open(IDF_PATH, "w") as f:
        json.dump(idf_weights, f, indent=2)

    written = 0
    no_chrono = 0
    with open(OUT, "w") as out:
        for s in summaries:
            slug = s["slug"]
            caps = s["summary"]["capabilities"]
            chrono = chronology.get(slug, {})
            if not chrono:
                no_chrono += 1

            # Author sources, in priority order:
            # 1. enriched manifest.author (live maintainer line)
            # 2. plugins.jsonl authors (CODEOWNERS-style list)
            # 3. chronology first_added_by (whoever wrote the original add commit)
            manifest = (enriched.get(slug) or {}).get("manifest", {}) or {}
            phase1 = plugins.get(slug, {}) or {}
            manifest_author = manifest.get("author")
            phase1_authors = phase1.get("authors")
            first_added_by = chrono.get("first_added_by")

            authors = []
            for a in (
                split_authors(manifest_author) +
                split_authors(phase1_authors) +
                ([first_added_by] if first_added_by else [])
            ):
                if a and a not in authors:
                    authors.append(a)

            entry = {
                "slug": slug,
                "displayName": s.get("displayName"),
                "category": s["summary"]["category"],
                "capabilities": caps,
                "idf_weighted_vector": to_idf_vector(caps, idf_weights),
                "first_added_at": chrono.get("first_added_at"),
                "first_added_by": chrono.get("first_added_by"),
                "first_added_sha": chrono.get("first_added_sha"),
                "original_authors": authors,
            }
            out.write(json.dumps(entry) + "\n")
            written += 1

    print(f"Wrote {written} entries to {OUT}")
    if no_chrono:
        print(f"WARN: {no_chrono} plugins have no chronology entry (likely renamed/removed from hub)")
    print(f"IDF rewritten with {len(idf_weights)} capabilities")


if __name__ == "__main__":
    main()
