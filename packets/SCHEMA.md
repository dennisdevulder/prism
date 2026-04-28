# PRISM Core Memory Packet — Schema v1

A PRISM packet is a self-contained directory that lets the framework triage submissions for a specific ecosystem (e.g. RuneLite plugin hub, VS Code marketplace, npm registry, etc.). The framework code is generic; ecosystems differ entirely in their packet contents.

## Why packets

The whole point of the LTM positioning is harness-neutrality. The same `prism triage` command should work for any open-source registry, just by pointing at the right packet. A reviewer for a different ecosystem builds their packet once (rules from their docs, catalog index from their existing entries) and then PRISM works the same way.

## Directory layout

```
<packet-id>/
├── manifest.yaml                       # packet metadata + content hashes
├── risk_rules.yaml                     # ecosystem-specific policy rules
├── saturation_index.jsonl              # IDF-weighted capability vectors per existing entry
├── capability_idf.json                 # IDF weights over the capability vocabulary
├── prompts/
│   ├── capability_extraction.md        # prompt for generating capabilities from a new submission
│   └── t1_risk_classification.md       # T1 risk-axis prompt
├── README.md                           # human-readable description of this packet
```

Optional ecosystem-specific extensions can live alongside (e.g. `eval/` for measured recall data, `chronology.json` for first-added timestamps).

## File roles

### `manifest.yaml`

Declares packet identity, version, sources, and content hashes. Fields:

```yaml
schema_version: 1
packet:
  id: <slug>                      # stable identifier
  version: <yyyy-mm-dd>           # date of this snapshot
  ecosystem: <human-readable>
  ecosystem_url: <upstream URL>

sources:
  rules:
    primary_citation: <URL of the policy doc maintainers cite>
    last_updated: <yyyy-mm-dd>
  saturation:
    catalog_size: <int>
    last_updated: <yyyy-mm-dd>

contents:
  - file: risk_rules.yaml
    type: rule_catalog
  - file: saturation_index.jsonl
    type: saturation_index
  - file: capability_idf.json
    type: idf_weights
  - file: prompts/capability_extraction.md
    type: prompt_template
  - file: prompts/t1_risk_classification.md
    type: prompt_template
```

### `risk_rules.yaml`

Rule catalog. Each rule has `id`, `category`, `severity` (block | warn), `detect` patterns, `citation`, `rationale`. Patterns are regex over text fields or capability lookups. See the runelite-plugin-hub packet for a working example.

### `saturation_index.jsonl`

One line per existing catalog entry. Each line:

```json
{
  "slug": "...",
  "displayName": "...",
  "category": "...",
  "capabilities": ["..."],
  "idf_weighted_vector": {"capability": <float weight>, ...},
  "first_added_at": "<ISO timestamp>",
  "first_added_by": "<author>",
  "original_authors": ["..."]
}
```

Attribution fields support PRISM's chronology principle: credit goes to whoever did it first, never to a later submitter who happened to merge faster.

### `capability_idf.json`

```json
{
  "capability-name": {"idf": <float>, "doc_count": <int>, "doc_frequency": <float>}
}
```

### `prompts/`

Markdown templates. The framework substitutes ecosystem-specific values (rule catalog, plugin manifest text) into placeholders. Two prompts ship by default:

- `capability_extraction.md` — generates capability tags + summary for a new submission
- `t1_risk_classification.md` — runs T1 risk against the rule catalog

A packet author can replace either with ecosystem-specific framing. The framework calls them by file name.

## What the framework provides

The packet contains data + prompts. The framework provides:

- IDF-weighted cosine similarity (saturation match)
- Rule pattern engine (T0 risk)
- LLM call wiring + N=3 ensemble (T1 risk)
- Chronology / attribution rendering
- Markdown verdict output

## How to build a new packet

1. Write `risk_rules.yaml` from the ecosystem's policy docs (the wiki, the contributing guide, closed-PR rejection language).
2. Generate capability summaries for every existing entry (Phase 3-style summarization).
3. Compute IDF weights and write the saturation index.
4. Walk the registry's git history for first-added timestamps (Phase 4).
5. Adapt the prompt templates if the ecosystem has unique vocabulary.
6. Write `manifest.yaml`. Hash the content files for verification.
7. Distribute the directory.

A reviewer points `prism triage --packet <dir>` at it and gets the same triage flow as the runelite-plugin-hub ecosystem.

## Versioning

Packets are dated, not semver'd. Replace the whole packet directory to update. The framework checks `schema_version` for compatibility; rule contents and the saturation index can change between packet releases without breaking the framework.

## Distribution

Initial distribution: ship the packet directory in the framework repo under `packets/<id>/`. A real LTM integration would let `ltm pull prism://<id>` resolve and install. Out of scope for v1.

## Ecosystem-specific extensions

Anything not in this schema is fair game in the packet directory — `eval/`, `chronology.json`, `policy_docs/`, etc. The framework ignores files it doesn't recognize.
