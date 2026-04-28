# PRISM Core Memory Packet — Schema v1

A PRISM packet is a self-contained directory that lets the framework triage submissions for a specific ecosystem (e.g. RuneLite plugin hub, VS Code marketplace, npm registry, etc.). The framework code is generic; ecosystems differ entirely in their packet contents.

## Why packets

The whole point of the LTM positioning is harness-neutrality. The same `prism triage` command should work for any open-source registry, just by pointing at the right packet. A reviewer for a different ecosystem builds their packet once (rules from their docs, catalog index from their existing entries) and then PRISM works the same way.

## Security model — hash verification is mandatory

Packets carry policy rules and a saturation index that influence triage outputs. Anyone with write access to the packet location (a stale release artifact, a compromised mirror, a malicious PR to a packet repo) could swap a file with one that biases triage — e.g. a rule catalog where `simulated_content` becomes `severity: warn` instead of `block`, or a saturation index that claims a malicious plugin duplicates a benign one.

The framework defends against this with **mandatory sha256 verification at packet load time**:

1. `manifest.yaml` declares full sha256 (64 hex chars) for every file in `contents[]`
2. `Packet(path)` computes sha256 of each file and compares to the manifest entry
3. **Any mismatch raises `PacketIntegrityError`** — no warning, no fallback, no "load anyway"
4. The CI action (and any downstream consumer) inherits this — a tampered packet fails the action loudly

The framework code itself must be pinned by **commit SHA** (not tag) in any GitHub Action that consumes a packet, so the verification code itself can't be swapped. `@v1` tags are mutable; `@a1b2c3d` commit SHAs are not.

**Future hardening (v2):** `manifest.yaml.sig` will sign the manifest with sigstore, so substituting both a file AND the manifest is also caught. Loader will require the signature when present and verify it against a well-known public key.

**To regenerate hashes after editing packet contents during development:**

```bash
python3 scripts/packet.py --packet <dir> --update-hashes
```

Production packets should never be modified post-release; bump `packet.version` and ship a new packet instead.

## Tier layering (read this first)

PRISM is a layered triage tool. Each tier exists to do something a cheaper tier can't:

- **T0 — rule-based detection.** Catches obvious slop and policy violations. Two checks live here: regex over the rule catalog (instant, no tokens) and an optional LLM rule sweep (Haiku-class, N=3 ensemble) for when the regex doesn't fire. If T0 blocks, the PR stops here — no point spending bigger model tokens on something the rules already rejected.
- **T1 — code-level correctness review.** Small model reads the source diff and surfaces `file:line` pointers worth a closer look. Output is reviewer guidance, not a verdict.
- **T2 — holistic semantic review.** Capable model reads the whole plugin, answers two questions: *"are there unsafe operations?"* and *"does the plugin do what its description claims?"* Output is a 30-second briefing for the reviewer.

**No tier replaces the reviewer.** The reviewer still reads every line. The tiers exist to make a 600-line PR chewable — by the time the reviewer opens the diff, they already know where to look.

## Directory layout

```
<packet-id>/
├── manifest.yaml                       # packet metadata + content hashes
├── risk_rules.yaml                     # ecosystem-specific policy rules (consumed by T0 regex + T0 LLM)
├── saturation_index.jsonl              # IDF-weighted capability vectors per existing entry (T0 saturation)
├── capability_idf.json                 # IDF weights over the capability vocabulary
├── prompts/
│   ├── capability_extraction.md        # generates capabilities from a new submission (build-time)
│   ├── t0_llm_rule_check.md            # T0 LLM rule sweep — runs when regex T0 returns compliant
│   ├── t1_correctness_review.md        # T1 code-level pointers (planned)
│   └── t2_holistic_review.md           # T2 semantic safety + description-match (planned)
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
  - file: prompts/t0_llm_rule_check.md
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

Markdown templates. The framework substitutes ecosystem-specific values (rule catalog, plugin manifest text) into placeholders. Default prompts:

- `capability_extraction.md` — generates capability tags + summary at build time (Phase 3)
- `t0_llm_rule_check.md` — T0 LLM rule sweep (runs after regex T0 returns compliant if `--t0-llm` flag is set)
- `t1_correctness_review.md` — T1 code-level pointers (planned)
- `t2_holistic_review.md` — T2 semantic safety + description-match (planned)

A packet author can replace any of these with ecosystem-specific framing. The framework calls them by file name.

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
