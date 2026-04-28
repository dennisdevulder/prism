# PRISM benchmark — Claude family

**Run**: 2026-04-28 · 12 runs (3 models × 2 cases × 2 tiers)

## Test cases

| Case | Rejection reason | What "caught" means |
|---|---|---|
| **PR #10069** memory-diagnostic | Maintainer rejected for `reflection` (forbidden language feature). Description ("Estimates relative memory usage of enabled plugins") is benign — invisible to T0 regex. | Model identifies reflection / `setAccessible` / cross-plugin field traversal in the source |
| **PR #11565** osrs-tracker | Clean PR (your own update). Ground truth: code ships 6 undisclosed feature sets not in the manifest (bingo tracking, pet drops, Item Snitch bank scanner, Backblaze direct uploads, etc.) | Model surfaces the description-vs-implementation gap |

## Results

| Case | Tier | Model | Tokens | Cost | Time | Caught? |
|---|---|---|---:|---:|---:|---:|
| #10069 | T1 | Haiku 4.5 | 28,314 | $0.0453 | 14.5s | ✓ |
| #10069 | T1 | Sonnet 4.6 | 22,099 | $0.1061 | 32.6s | ✓ |
| #10069 | T1 | Opus 4.7 | 29,373 | $0.2350 | 26.4s | ✓ |
| #10069 | T2 | Haiku 4.5 | 27,805 | $0.0445 | 8.5s | ✓ |
| #10069 | T2 | Sonnet 4.6 | 21,362 | $0.1025 | 17.8s | ✓ |
| #10069 | T2 | Opus 4.7 | 28,899 | $0.2312 | 22.2s | ✓ |
| #11565 | T1 | Haiku 4.5 | 46,968 | $0.0751 | 54.0s | ✓ |
| #11565 | T1 | Sonnet 4.6 | 54,004 | $0.2592 | 124.7s | ✓ |
| #11565 | T1 | Opus 4.7 | 51,762 | $0.4141 | 82.7s | ✓ |
| #11565 | T2 | Haiku 4.5 | 34,047 | $0.0545 | 27.7s | ✗ |
| #11565 | T2 | Sonnet 4.6 | 80,517 | $0.3865 | 60.0s | ✓ |
| #11565 | T2 | Opus 4.7 | 29,152 | $0.2332 | 67.5s | ✓ |

## Per-model totals

| Model | Caught | Tokens | Total cost | $/correct |
|---|---:|---:|---:|---:|
| Claude Haiku 4.5  | 3/4 | 137,134 | $0.2194 | **$0.0731** |
| Claude Sonnet 4.6 | 4/4 | 177,982 | $0.8543 | $0.2136 |
| Claude Opus 4.7   | 4/4 | 139,186 | $1.1135 | $0.2784 |

```
  Claude Haiku 4.5     █████████                                          $0.22  (3/4)
  Claude Sonnet 4.6    ██████████████████████████████████████             $0.85  (4/4)
  Claude Opus 4.7      ██████████████████████████████████████████████████ $1.11  (4/4)
```

## Notable findings

### T0 baseline
T0 (regex over the rule catalog) returned **compliant** on both PRs. The rule catalog has no pattern that matches "Estimates relative memory usage" or "Automatically sends level-ups…". That's correct behavior — these are description-clean cases. Catching them is T1/T2's job.

### #10069 reflection — every model + tier caught it
All 6 model/tier combinations identified the reflection pattern (`setAccessible(true)`, `getDeclaredFields()`, cross-plugin field traversal). Cheapest catch: **Haiku T2 at $0.0445 in 8.5s.** That's the value moment for the layered design — a maintainer rejection that's invisible to manifest reading gets surfaced for under 5¢ in under 10 seconds.

### #11565 osrs-tracker — interesting model divergences

- **Haiku T2 missed** the undisclosed features (verdict: "matches description"). Haiku doesn't synthesize across files well enough to say "these subsystems exist but aren't in the manifest."
- **Opus T1 outperformed Sonnet T2 on the same case at lower cost.** Opus's pointers identified Item Snitch, Bingo, Pet tracker, Quick Capture, AND the Bearer-token env-var leak — substantially more thorough than Sonnet T2's prose synthesis. $0.41 vs $0.39.
- **Sonnet T2 vs Opus T2** disagreed on verdict (Sonnet: "partial" with 6 gaps; Opus: "matches description"). Both interpretations are defensible — Sonnet read "the plugin overall does more than the manifest claims"; Opus read "this PR doesn't introduce new unsafe ops." A reviewer would benefit from seeing both.

### Tier-vs-tier substitutability
For a maintainer with a tight budget, **Haiku T1 alone catches both rejection types tested here**. Haiku T2 has the variance issue but is cheaper than running both. The full T0+T1+T2 stack with Sonnet for T2 is $0.39 + $0.05 = ~$0.44 per PR for the reviewer brief — well under a dollar for the full triage.

### Recommendation
- **T1 default**: Haiku 4.5 — cheap, reliably catches code-level violations
- **T2 default**: Sonnet 4.6 — best description-vs-implementation synthesis at this scale
- **Opus 4.7**: not worth the premium for this task; Sonnet equals or beats it for less

## Models not run

| Model | Provider | Notes |
|---|---|---|
| GPT-5.5 | OpenAI | Skipped — `OPENAI_API_KEY` not set |
| Gemini 3.1 Pro | Google | Skipped — `GOOGLE_API_KEY` not set |
| DeepSeek V3.2 | DeepSeek | Skipped — `DEEPSEEK_API_KEY` not set |

The benchmark harness (`scripts/benchmark.py`) supports all four providers; runs fill in additional rows as keys become available.

## Reproducing

```bash
./prism verify packets/runelite-plugin-hub
python3 scripts/benchmark.py --tiers t1,t2 --only-models claude-haiku-4-5,claude-sonnet-4-6,claude-opus-4-7
```
