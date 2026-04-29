# PRISM benchmark — combined cross-provider run

**Cases**: 2 — PR #10069 memory-diagnostic (reflection rejection), PR #11565 osrs-tracker (clean PR with undisclosed feature sets)
**Tiers**: T1 (code-level pointers) + T2 (holistic semantic review) — 2 cells per case per model
**Runs**:
- 2026-04-28 Claude family — direct Anthropic API
- 2026-04-28 open-weight — DigitalOcean Gradient Serverless Inference (`https://inference.do-ai.run/v1`)

The DO subscription tier on this account does **not** include the proprietary Anthropic / OpenAI catalog entries — those 401'd ("not available for your subscription tier"). For Claude family numbers we rely on the prior direct-API run; OpenAI GPT-5.x, Gemini, etc. are unrun until keys are added.

## Per-model totals (4 cells = 2 cases × 2 tiers)

| Model | Caught | Total tokens | Total cost | $/correct | Notes |
|---|---:|---:|---:|---:|---|
| **DeepSeek 3.2** | **4/4** | 83,550 | **$0.0304** | **$0.0076** | T1+T2 both reliable; fastest provider too (2-5s/cell) |
| GLM-5 (z.ai) | 4/4 | 85,314 | $0.0960 | $0.0240 | Strong synthesis on T2 |
| Llama 4 Maverick | 4/4 | 81,068 | $0.1259 | $0.0315 | Reliable but priciest open-weight |
| Claude Haiku 4.5 | 3/4 | 137,134 | $0.2194 | $0.0731 | Missed undisclosed features in T2 (10069 ✓, 11565 T2 ✗) |
| Claude Sonnet 4.6 | 4/4 | 177,982 | $0.8543 | $0.2136 | Best prose synthesis; nuanced T2 verdicts |
| Claude Opus 4.7 | 4/4 | 139,186 | $1.1135 | $0.2784 | No quality gain over Sonnet on these cases |
| Qwen 3.5 397B (MoE) | 2/4 | 103,946 | $0.0329 | $0.0165 | T2 unreliable (parse_error + empty_response) |
| Kimi K2.5 | 1/4 | 86,849 | $0.0075 | $0.0075 | T1 returned empty completions on both cases |
| GPT-5.5 | — | — | — | — | DO tier 401; Anthropic-key path needs separate run |
| GPT-5.4 | — | — | — | — | DO tier 401 |

## Cost per correct decision (ASCII)

```
  DeepSeek 3.2         █                                          $0.008  4/4
  GLM-5 (z.ai)         ██                                         $0.024  4/4
  Llama 4 Maverick     ███                                        $0.032  4/4
  Claude Haiku 4.5     ███████                                    $0.073  3/4
  Claude Sonnet 4.6    █████████████████████                      $0.214  4/4
  Claude Opus 4.7      ████████████████████████████               $0.278  4/4
```

## Per-cell detail (open-weight run only, full run already in 2026-04-28-claude-family/)

| Model | Case | Tier | Caught | Tokens | Cost | Time | Status |
|---|---|---|:-:|---:|---:|---:|---|
| DeepSeek 3.2 | #10069 | T1 | ✓ | 8,048 | $0.0031 | 2.1s | ok |
| DeepSeek 3.2 | #10069 | T2 | ✓ | 7,968 | $0.0030 | 2.2s | ok |
| DeepSeek 3.2 | #11565 | T1 | ✓ | 21,040 | $0.0078 | 3.4s | ok |
| DeepSeek 3.2 | #11565 | T2 | ✓ | 46,494 | $0.0165 | 4.7s | ok |
| GLM-5 | #10069 | T1 | ✓ | 8,585 | $0.0115 | 21.1s | ok |
| GLM-5 | #10069 | T2 | ✓ | 7,758 | $0.0091 | 10.5s | ok |
| GLM-5 | #11565 | T1 | ✓ | 22,009 | $0.0259 | 31.1s | ok |
| GLM-5 | #11565 | T2 | ✓ | 46,962 | $0.0495 | 24.8s | ok |
| Llama 4 Maverick | #10069 | T1 | ✓ | 7,498 | $0.0122 | 8.8s | ok |
| Llama 4 Maverick | #10069 | T2 | ✓ | 7,345 | $0.0116 | 5.2s | ok |
| Llama 4 Maverick | #11565 | T1 | ✓ | 20,359 | $0.0317 | 10.7s | ok |
| Llama 4 Maverick | #11565 | T2 | ✓ | 45,866 | $0.0704 | 23.5s | ok |
| Qwen 3.5 397B | #10069 | T1 | ✓ | 9,906 | $0.0097 | 19.4s | ok |
| Qwen 3.5 397B | #10069 | T2 | ✗ | 10,776 | — | 7.4s | parse_error |
| Qwen 3.5 397B | #11565 | T1 | ✓ | 25,865 | $0.0232 | 7.1s | ok |
| Qwen 3.5 397B | #11565 | T2 | ✗ | 57,399 | — | 31.2s | empty_response |
| Kimi K2.5 | #10069 | T1 | ✗ | 9,282 | — | 30.7s | empty_response |
| Kimi K2.5 | #10069 | T2 | ✓ | 8,539 | $0.0075 | 20.6s | ok |
| Kimi K2.5 | #11565 | T1 | ✗ | 21,939 | — | 32.8s | empty_response |
| Kimi K2.5 | #11565 | T2 | ✗ | 47,089 | — | 34.2s | empty_response |

## Findings

### 1. DeepSeek 3.2 is the value champion
$0.0076 per correct decision — **9.6× cheaper than Haiku 4.5**, **28× cheaper than Sonnet 4.6**, and 4/4 caught with the lowest latency in the field (2-5s per cell). For a maintainer running PRISM in CI on every PR, this is the default to reach for. The full PRISM stack (T0+T1+T2) on a typical PR runs **under 5 cents** with DeepSeek 3.2.

### 2. GLM-5 and Llama 4 Maverick are reliable backups
Both 4/4 with no JSON / empty-response issues. GLM-5 is meaningfully slower than DeepSeek (~25s vs ~3s) but still cheaper than Claude Haiku per correct call.

### 3. Kimi K2.5 and Qwen 3.5 397B failed JSON-mode reliability
Both models returned empty completions or unparseable JSON when asked for `response_format: json_object`. Kimi missed 3/4 cells, Qwen missed 2/4. They may be usable with a different prompt strategy (free-form output + parser) but in the current strict-JSON harness they're unreliable.

### 4. Claude Opus 4.7 is not worth the premium for this task
On both cases at both tiers, Sonnet 4.6 either matches or has a more nuanced verdict than Opus, at ~30% of the cost. **Do not default to Opus for triage.**

### 5. Sonnet 4.6 remains the recommended T2 default among Claude
4/4 with the best prose synthesis. The maintainer-facing brief from Sonnet T2 is qualitatively the most useful — it surfaces description-vs-implementation gaps that get framed as "this PR introduces X, Y, Z subsystems not in the manifest."

### 6. Haiku 4.5 is the safe T1 default for Claude users
3/4 (missed only the harder description-gap case at T2; T1 caught everything). For maintainers already on the Anthropic console, Haiku at T1 + Sonnet at T2 is a reasonable stack at ~$0.40/PR.

## Recommendations by maintainer profile

| Profile | T1 | T2 | $/PR |
|---|---|---|---|
| Cost-optimized (recommended default) | DeepSeek 3.2 | DeepSeek 3.2 | ~$0.02 |
| Cost-optimized, want diversity | DeepSeek 3.2 | GLM-5 | ~$0.04 |
| Anthropic-only stack | Claude Haiku 4.5 | Claude Sonnet 4.6 | ~$0.40 |
| Frontier-quality at any cost | Claude Sonnet 4.6 | Claude Opus 4.7 | ~$0.65 |

## Models not run (subscription / key gaps)

| Model | Provider | Status |
|---|---|---|
| GPT-5.5 / 5.4 | OpenAI | DO subscription 401 — would need direct OpenAI key |
| Claude family on DO | Anthropic via DO | DO subscription 401 — direct Anthropic key was used in the parallel run |
| GLM-5.1 | z.ai | Not in DO catalog (only GLM-5); would need separate z.ai key |
| Gemini 3.1 Pro | Google | `GOOGLE_API_KEY` not set |

## Reproducing

```bash
# Open-weight via DO
OPENAI_API_KEY=<DO Model Access Key> \
OPENAI_BASE_URL=https://inference.do-ai.run/v1 \
python3 scripts/benchmark.py --tiers t1,t2 \
  --only-models glm-5,deepseek-3-2,kimi-k2-5,qwen3-5-397b,llama-4-maverick

# Anthropic family (direct)
ANTHROPIC_API_KEY=<key> \
python3 scripts/benchmark.py --tiers t1,t2 \
  --only-models claude-haiku-4-5,claude-sonnet-4-6,claude-opus-4-7
```
