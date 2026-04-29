# prism

**A second pair of eyes for plugin-hub PRs.**

prism reads each pull request the way a careful maintainer would and writes a short brief: what the plugin does, what's worth a closer look, and whether anything in the code clashes with what the description claims. It never approves, rejects, or merges. It just makes the next ten minutes of review faster.

## Why this exists

The cost of writing a PR has gone to zero. The cost of triaging one hasn't moved. As that gap widens, more time per PR goes to questions that don't need a human — *"is this a known-bad pattern?"*, *"does the description match the code?"*, *"is this a near-duplicate of something already in the catalog?"* — and less time goes to the parts that do.

prism answers the cheap questions in seconds, with citations, so the expensive attention lands where it earns its keep.

## What you get

For every PR, prism produces a markdown brief like this:

```
## PRISM triage — PR #11565: update osrs-tracker

⚠️ REVIEW — flagged signals below

- Plugin: `osrs-tracker` (UPDATE) by `dennisdevulder`, opened 2026-04-18
- Description: Automatically sends level-ups, quest completions, loot drops...

### Saturation — NOVEL-EXTENSION
cosine 0.64 vs universal-discord-notifications, adds novel:
['external-data-export', 'gpu-video-encoding', 'video-replay-capture']

### Risk — COMPLIANT
no rule matched

### T1 — code-level pointers (5 for reviewer attention)
- ⚠️ OsrsTrackerConfig.java L140-158 — env var override of API URL in dev mode
- 🛑 EventKind.java L1-3 — references VulkanEncoder.java but that file is truncated
- ⚠️ ApiClient.java L1271 — Authorization header built by concatenation
...

### T2 — holistic brief
What it does: Sends gameplay events to osrs-tracker.com with video clips.
Description match: PARTIAL — code also ships bingo progress reporter,
                              item-snitch bank scanner, and Backblaze
                              direct uploads not in the manifest.
```

It's never a verdict. The reviewer reads the code. prism just told them which lines to read first, and which existing plugins to compare against. Full sample: [`examples/triage_pr11565_full.md`](./examples/triage_pr11565_full.md).

## Try it

You need [`gh`](https://cli.github.com/) authenticated and Python 3. From the repo root:

```bash
./prism triage --pr 11565
```

That runs the cheap layers (regex sweep + saturation match) and prints the brief to stdout. No API key needed, runs in under five seconds.

For deeper review, add LLM layers:

```bash
export OPENAI_API_KEY=...
./prism triage --pr 11565 --t0-llm --t1 --t2
```

`--t0-llm` adds the manifest-only LLM rule sweep, `--t1` reads the diff for code-level pointers, `--t2` reads the source for a holistic brief. Each is independent — pick what your case warrants. The [benchmark](#benchmark--what-works) below scores models on T1+T2 so you can pick one with numbers.

## Run it on every PR (GitHub Action)

Drop this into the plugin-hub workflow:

```yaml
# .github/workflows/prism.yml
on: pull_request
jobs:
  triage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dennisdevulder/prism/action@v0.1   # pin a release, not @main
        with:
          api-key: ${{ secrets.PRISM_API_KEY }}
```

The brief gets posted as a PR comment. A working example: [`action/example-workflow.yml`](./action/example-workflow.yml).

## Author-side: tell prism what you intended to ship

If you're an author submitting a PR and you want prism's brief to show your intent up front, paste a packet into the PR description:

````markdown
```prism-packet
{
  "ltm_version": "0.2",
  "goal": "Add a Sailing-skill quest helper overlaying NPC dialogue choices.",
  "decisions": [
    {"what": "Use existing QuestStep API", "locked": true},
    {"what": "No prayer-flick or DPS hints — out of scope", "locked": true}
  ],
  "provenance": {
    "author_model": "claude-opus-4-7",
    "author_human": "your-handle"
  }
}
```
````

Maintainers see a Provenance section at the top of the brief showing what you said you were doing — "stated goal," "locked decisions," any failed attempts you disclosed. It's a credibility signal *you* control, and it tends to move PRs through review faster. The packet shape follows the [LTM Core Memory Packet protocol](https://github.com/dennisdevulder/ltm/blob/main/SPEC.md); generate it with `ltm`, an agent, or by hand. No packet attached = neutral note. Never a penalty.

Sample shape: [`examples/sample_author_packet.json`](./examples/sample_author_packet.json).

## How it works (if you care)

prism is built as four independent layers. Each is opt-in via a CLI flag, and each gets cheaper-but-shallower as you go down the list:

1. **T0 — regex sweep.** Match the diff and manifest against the ecosystem's rule catalog (forbidden APIs, simulated content, keystroke automation). Pure static, zero tokens. Runs always.
2. **T0+ — light LLM rule sweep** (`--t0-llm`). If T0 said clean, a cheap model re-reads the manifest description against the rules. Catches policy violations the regex can't see.
3. **T1 — code-level review** (`--t1`). A small model reads the diff and points at lines worth attention. No verdicts, just *"look here."*
4. **T2 — holistic brief** (`--t2`). A capable model reads the source and writes a four-part summary: what it does, whether the description matches, any unsafe ops, bottom-line reviewer effort.

If T0 fires on a clear policy violation, T1 and T2 are skipped — the brief is built from T0 alone. Otherwise the layers you enabled all run and contribute their sections to the brief.

## Benchmark

prism ships its own benchmark harness so you can pick a model with numbers, not a coin flip. The latest run scored **15 open-weight models × 16 cases × T1 and T2 = 480 cells** on recall, specificity, accuracy, and cost-per-correct-decision.

Headline: **Llama 4 Maverick** at 94% accuracy, **GPT-OSS 120B** at the same 88% as DeepSeek for a third the cost.

Full results, the case set, false-positive offenders, and a "test your own model" guide → [**BENCHMARK.md**](./BENCHMARK.md)

## What ecosystems are supported

Right now: **RuneLite plugin-hub.** The reference packet at [`packets/runelite-plugin-hub/`](./packets/runelite-plugin-hub/) ships with a 34-rule catalog scraped from the rejected-features wiki and Jagex 3PC guidelines, a 1,659-plugin similarity index, and tuned prompts.

Adding another ecosystem (Obsidian community plugins, BetterDiscord, glitch-soc forks) means writing a new packet — same shape, different rules and index. The CLI doesn't care which one you load.

## What it is *not*

- **Not a gatekeeper.** prism never closes, blocks, or auto-merges anything. Every flag is a suggestion.
- **Not an allowlist.** No "trusted authors," no "approved dependencies." Open source moves too fast for static registries.
- **Not a rubber stamp.** Reviewers still read every line of every PR they merge. prism just makes the high-volume ones chewable so the real reviews get the time they need.

## Contributing

The most useful contributions right now:

- **Labeled cases for the benchmark.** If you're a maintainer and you remember closing a PR for a specific reason, the [`benchmarks/cases/cases.json`](./benchmarks/cases/cases.json) file is where ground-truth lives. Open an issue with the PR number and rejection reason.
- **A packet for another ecosystem.** Copy [`packets/runelite-plugin-hub/`](./packets/runelite-plugin-hub/), swap the rules and prompts, regenerate the saturation index from your catalog. Open a PR.
- **Better adversarial fixtures.** [`benchmarks/fixtures/adversarial_*`](./benchmarks/fixtures/) tests model resistance to prompt injection in code comments and lying manifests. More attacker-creative cases sharpen the benchmark.

For bugs and feature requests, [open an issue](https://github.com/dennisdevulder/prism/issues).

## Status

Pre-alpha. The pipeline runs end-to-end against RuneLite plugin-hub, the GitHub Action installs cleanly, and the benchmark catalogs 16 open-weight models on DigitalOcean Gradient (15 in the latest sweep). Packet schema may break before the first tagged release.

## How this project was built

If a tool whose whole point is *"disclose what model wrote your code"* didn't disclose what model wrote *its* code, that would be a tell. So:

```prism-packet
{
  "ltm_version": "0.2",
  "project": {
    "name": "prism",
    "ref": "github.com/dennisdevulder/prism"
  },
  "goal": "A second-pair-of-eyes triage tool for plugin-hub maintainers — supports reviewers, never replaces them.",
  "decisions": [
    {
      "what": "Tiered architecture (T0 regex / T0+ light LLM / T1 small model / T2 capable model). Most PRs decidable cheaply; only ambiguous ones need expensive synthesis.",
      "locked": true
    },
    {
      "what": "No allowlists, no auto-merge, no auto-close. Open source moves too fast for static registries; reviewers always decide.",
      "locked": true
    },
    {
      "what": "Hash-verified packets per ecosystem. Rule catalogs and indices need to be tamper-resistant in CI.",
      "locked": true
    },
    {
      "what": "Tokens-per-correct-decision is the headline metric. Collapses cost and accuracy into one comparable number across models.",
      "locked": true
    }
  ],
  "attempts": [
    {
      "tried": "Building generalized provider adapters inside the product itself.",
      "outcome": "failed",
      "learned": "The benchmark harness is the modular concern; the product picks one wire format (OpenAI-compatible) and stops."
    },
    {
      "tried": "Framing prism as a classifier with high-recall targets.",
      "outcome": "failed",
      "learned": "Re-framed around 'reviewer brief' — pointers, summaries, flagged lines, never verdicts. We support, we do not replace."
    },
    {
      "tried": "Reading author packets from a `.prism/packet.json` file in the PR's source repo.",
      "outcome": "failed",
      "learned": "That created a dependency on the author's repo state and conflated the LTM protocol with one storage choice. Switched to a fenced block in the PR body — same protocol, surface we already fetch."
    }
  ],
  "provenance": {
    "author_human": "dennisdevulder",
    "author_model": "claude-opus-4-7",
    "confidence": "high"
  }
}
```

The architecture, the benchmark harness, most of the prose, and a substantial share of the code itself were generated in collaboration with Claude Opus 4.7. Every decision was reviewed and locked by a human; every line was read before being committed. That's the model prism asks PR authors to use, and it's the model used to build prism.

## License

[MIT](./LICENSE)
