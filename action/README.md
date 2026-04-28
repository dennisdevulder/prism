# PRISM Triage GitHub Action

Adoption shape for the runelite team: **one workflow file + one secret**.

The action runs `prism triage` on every PR opened against `plugins/**` and posts a single labelled comment containing the reviewer brief. Subsequent pushes to the same PR update the existing comment in place.

## Adopting

1. Pin to a reviewed commit SHA in the PRISM repository (never `@v1` or other mutable tag — see the security model in `packets/SCHEMA.md`).
2. Drop `example-workflow.yml` into `.github/workflows/prism-triage.yml` in the consuming repo.
3. Replace `<COMMIT_SHA>` placeholders with specific reviewed commits.
4. Add `ANTHROPIC_API_KEY` to repo secrets only if you're enabling `enable-t0-llm: true` (T0 regex alone needs no API key).

## What gets posted

A single comment per PR, prefixed with `<!-- prism-triage -->` so the action recognizes and updates it on subsequent runs:

```
## PRISM triage — PR #<n>: <title>

🛑 BLOCK | ⚠️ REVIEW | ✅ PASS

- **Plugin**: …
- **Source**: …
- **Description**: …

### Saturation — …
Closest existing plugins (with attribution: who built it first, when):
- `…`
- `…`

### Risk — …
Matched rules (severity badge + evidence quote + wiki citation):
- 🛑 `…`

### Reviewer notes
PRISM is a triage tool — every flag here is a suggestion, not a verdict.
The reviewer makes the call.

_Packet: `runelite-plugin-hub@2026-04-28` · 1659 catalog entries · 34 rules_
```

## What this action doesn't do

- **Doesn't replace review.** Reviewers still read every line. The comment exists to make a 600-line PR chewable by surfacing where to look first.
- **Doesn't maintain an exception list.** If a rule fires today and a maintainer overrides, the next reviewer on a future PR sees the same flag fresh. Open source moves too fast for static "approved" registries.
- **Doesn't auto-decide.** Verdicts are advisory. The action never closes/labels/blocks a PR on its own.

## Security model

- The action verifies packet sha256 hashes at every run; tampered packets cause the action to fail loudly (no fallback).
- Pin `actions/checkout` and the PRISM repo by commit SHA, not tag.
- The packet directory itself should be checked into the same repository or downloaded from a release with content-hash verification.

See `packets/SCHEMA.md` in the PRISM repo for the full threat model and verification details.
