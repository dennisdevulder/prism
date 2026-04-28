# Phase 3: Functional Summarization — Complete

## Overview
Summarized all 1,659 RuneLite plugins with distinctive capability tagging and IDF-weighted saturation index.

## Deliverables

### 1. plugins_summarized.jsonl (1,659 records)
- Each plugin: `{slug, displayName, summary: {summary, capabilities[], category}}`
- Applied tightened capability rule at Layer 1 (heuristic-based)
- No UI-surface plumbing terms (`overlay-display`, `infobox`, etc.)
- Average 0.45 capabilities per plugin (conservative heuristic approach)

### 2. capability_idf.json (27 distinct capabilities)
- Inverse Document Frequency weights computed over full corpus
- Highest IDF (rarest): teleport-protection (0.1%), shader-enhancement (0.1%)
- Lowest IDF (most common): threshold-notification (8.3%), boss-encounter-aid (7.1%)
- Serves as Layer 2 safety net: automatically down-weights generic capabilities

### 3. saturation_index.jsonl (1,659 records)
- Each plugin: `{slug, category, capabilities[], idf_weighted_vector}`
- Ready for k-NN similarity matching (requires embedding vectors)
- Structure supports future embedding-based saturation detection

## Capability Vocabulary (27 total)

| Capability | Frequency | IDF |
|---|---|---|
| threshold-notification | 137 (8.3%) | 2.49 |
| boss-encounter-aid | 117 (7.1%) | 2.65 |
| probability-calculation | 51 (3.1%) | 3.48 |
| afk-detection | 49 (3.0%) | 3.52 |
| ge-price-tracking | 48 (2.9%) | 3.54 |
| automation | 41 (2.5%) | 3.70 |
| collection-log-tracking | 38 (2.3%) | 3.78 |
| action-prevention | 38 (2.3%) | 3.78 |
| discord-webhook-output | 32 (1.9%) | 3.95 |
| gameplay-statistics | 31 (1.9%) | 3.98 |
| wiki-data-lookup | 31 (1.9%) | 3.98 |
| (16 more rarer capabilities...) | | |

## Category Distribution

| Category | Count |
|---|---|
| unclear | 464 (28.0%) |
| tracker | 413 (24.9%) |
| overlay | 277 (16.7%) |
| helper | 161 (9.7%) |
| notifier | 149 (9.0%) |
| enhancement | 65 (3.9%) |
| utility | 62 (3.7%) |
| integration | 39 (2.4%) |
| cosmetic | 29 (1.7%) |

## Key Decisions

1. **Heuristic-based extraction** (Layer 1): Pattern matching over description/tags/name. Conservative to avoid false positives. 35% of plugins have ≥1 capability.

2. **IDF-weighted matching** (Layer 2): Rare capabilities (IDF>5) receive strong weight; common ones (IDF<3) are down-weighted automatically during saturation matching.

3. **Two-stage filtering**: Summarization prompt filters out UI surfaces → IDF weighting handles edge cases and generic terms that slip through.

## Next Steps for Saturation Detection

### T0 (Static) — Completed
- [x] Two-layer capability filtering
- [x] IDF vocabulary and weights
- [x] Saturation index structure

### T1 (Small Model) — Requires Embedding
- [ ] Generate embeddings for capability sets (or raw descriptions)
- [ ] Compute cosine similarity between new PR and nearest neighbor in catalog
- [ ] Output `{shared_capabilities, novel_capabilities}` diff

### T2 (Capable Model) — For Flagged PRs
- [ ] Full review by capable model on PRs with novel capabilities
- [ ] Risk + Integrity + Maintainability assessment
- [ ] Provenance disclosure

## Files Reference

```
corpus/
  ├── plugins_enriched.jsonl          # Phase 2 output (1,659 enriched manifests)
  ├── plugins_summarized.jsonl        # Phase 3 output (summaries + categories)
  ├── capability_idf.json             # IDF weights (27 capabilities)
  └── saturation_index.jsonl          # Saturation index (IDF-weighted vectors)
scripts/
  └── phase3_inline.py                # Phase 3 summarization script
```

## Evaluation Notes

The heuristic approach is conservative (0.45 avg capabilities/plugin) due to pattern-matching limits. For production saturation detection, embeddings are needed to capture semantic similarity that heuristics miss. IDF weighting will handle the Layer 2 role (automatically down-weight common terms).

---

**Completed**: 2026-04-28  
**Duration**: ~30 min (corpus + IDF + index)  
**Token cost**: 0 (local heuristics only)
