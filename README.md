# PRISM

Triage AI-generated PRs for open-source maintainers. Splits each submission into five components — **P**rovenance, **R**isk, **I**ntegrity, **S**aturation, **M**aintainability — and routes most to a verdict before any LLM call is made.

**Status:** early WIP. Building the catalog first, against the RuneLite plugin-hub (~1,000 plugins).

## The five axes

- **Provenance** — model disclosure (via an [LTM](https://github.com/dennisdevulder/ltm) packet attached to the PR), signal that the human author understood what they shipped
- **Risk** — keystroke APIs, raw network sinks, `eval`/`exec`, writes outside the repo, suspicious blobs
- **Integrity** — does the diff match the description, are the claimed decisions coherent with the code
- **Saturation** — how many near-equivalents already exist in the ecosystem
- **Maintainability** — LOC, cyclomatic complexity, near-duplicate detection (AST + MinHash)

## How it stays cheap

A tiered pipeline. **T0** is pure static analysis with zero LLM tokens and routes most PRs to a verdict on its own. Only what survives reaches a small model at **T1** (~500 tokens, diff skeleton only). Only the flagged slices reach a capable model at **T2** (~3–5k tokens).

The headline eval metric is **tokens-per-correct-decision** — collapses cost and accuracy into one comparable number across models.

## Harness-neutral via LTM

PRISM's rule packs and per-ecosystem saturation indices live as [Core Memory Packets](https://github.com/dennisdevulder/ltm/blob/main/SPEC.md). Any harness — Claude Code, Cursor, Codex, plain CLI — pulls them via the `ltm` MCP. Authors attach a packet to their PR; `provenance.author_model` is the disclosure field, `decisions` and `attempts` are the understanding signal.

## License

MIT
