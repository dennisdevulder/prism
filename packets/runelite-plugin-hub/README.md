# PRISM Packet — RuneLite Plugin Hub

Triages submissions to [github.com/runelite/plugin-hub](https://github.com/runelite/plugin-hub) for review support.

## What's in here

- `risk_rules.yaml` — 33 rules across 4 categories sourced from the [Rejected-or-Rolled-Back-Features wiki](https://github.com/runelite/runelite/wiki/Rejected-or-Rolled-Back-Features) and the [Jagex Third-Party Client Guidelines](https://secure.runescape.com/m=news/third-party-client-guidelines?oldschool=1)
- `saturation_index.jsonl` — IDF-weighted capability vectors for the 1,659 currently-accepted plugins, with first-added attribution from the plugin-hub git history
- `capability_idf.json` — IDF weights over the 1,889-term capability vocabulary
- `chronology.json` — first-add timestamps + first-commit author per slug (1,656/1,659 resolved)
- `prompts/` — capability extraction (Phase 3) and T1 risk classification prompt templates

## Coverage

The catalog covers all currently-accepted plugins. The risk rules cover 33 distinct violation patterns; the catalog has been validated:

- 0.4% false-positive rate on the catalog (6 plugins flagged, mostly genuine HTTP-exposure warnings the maintainers tolerate)
- T1 ensemble (N=3) recall on 49 known policy rejections: 45%
- Realistic T1 ceiling with prompt iteration: ~76% (description-only); remaining ~24% needs source-level inspection

## What this packet does NOT do

- Enforce decisions — every flag is a suggestion. The reviewer makes the call.
- Maintain an "approved exceptions" list — open source moves too fast for that to be meaningful. If a maintainer overrides a flag once, that decision doesn't propagate; the next reviewer sees the same flag fresh.
- Cover code-level violations (reflection, JNI, runtime code download). Those need a T2 tier with source fetching.

## How to refresh

When the wiki rules change or the catalog gains plugins, regenerate:

1. Re-fetch plugin-hub manifests (`scripts/fetch_manifests.py`)
2. Re-summarize for capabilities (Phase 3 — see `prompts/capability_extraction.md`)
3. Recompute IDF weights and rebuild the saturation index (`scripts/build_saturation_index.py`)
4. Walk plugin-hub git for chronology updates (`scripts/enrich_chronology.py`)
5. Update `risk_rules.yaml` from the wiki diff
6. Bump `manifest.yaml` version and recompute content hashes
