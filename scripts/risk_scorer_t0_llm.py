#!/usr/bin/env python3
"""PRISM Risk axis — T0 LLM rule extension.

T0 is the rule-based detection tier. Two checks live here:
  1. risk_scorer.py — regex over rule catalog (instant, blocks slop)
  2. risk_scorer_t0_llm.py (this file) — LLM-driven rule matching
     for cases the regex doesn't catch

Both check the same rule catalog. Together they form T0: catch obvious
slop and blocked features before any deeper analysis happens.

This is NOT T1. T1 is the next tier — code-level correctness review with
file:line pointers for the reviewer. T2 is the holistic semantic pass.

Why N=3 ensemble: single-run Haiku has ~21pp recall variance on this
task (Jaccard 0.05–0.41 between runs of identical input). Three runs +
union of flags + confidence-by-agreement gets stable behavior at small
token cost.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
RULES_PATH = PRISM_ROOT / "corpus" / "risk_rules.yaml"

T0_LLM_SYSTEM_PROMPT = """You are evaluating an OSRS plugin against the RuneLite plugin-hub policy rule catalog. Identify which rules the plugin matches based on its description, displayName, tags, and title.

You're a maintainer reviewer reading the plugin's metadata — you do NOT have source code or rejection comments. Make your judgment from the description alone.

Output JSON only. Schema:
{
  "matched_rules": [
    {"rule_id": "<id from catalog>", "severity": "block"|"warn", "confidence": "high"|"medium"|"low", "evidence": "<exact quote from input>", "rationale": "<one-line>"}
  ],
  "verdict": "compliant" | "policy-warning" | "policy-violation",
  "reasoning": "<one-sentence>"
}

Matching rules:
- Match a rule when description+tags+title give clear evidence of the banned thing
- Be thorough — match every applicable rule
- A plugin can match multiple rules
- Verdict: "policy-violation" if any matched rule is severity:block AND confidence:high; "policy-warning" if matched rules exist but lower confidence; "compliant" otherwise
- Treat the rule catalog as authoritative — don't invent rules"""


def evaluate_via_anthropic(plugin):
    try:
        from anthropic import Anthropic
    except ImportError:
        raise SystemExit("pip install anthropic")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY env var required")

    rules_text = RULES_PATH.read_text()
    user = f"""Rule catalog:
```yaml
{rules_text}
```

Plugin to evaluate:
- title: {plugin.get('title') or plugin.get('displayName') or '?'}
- displayName: {plugin.get('displayName') or '?'}
- description: {plugin.get('description') or ''}
- tags: {plugin.get('tags') or ''}

Output JSON only."""

    client = Anthropic()
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=T0_LLM_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
    )
    text = msg.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def ensemble(plugin, n=3, verdict_provider=evaluate_via_anthropic):
    """Run the verdict provider N times and union the matched rules.

    Confidence_runs tracks how many runs flagged each rule, which is the
    more honest confidence signal than the per-run confidence label.
    """
    runs = []
    for _ in range(n):
        try:
            runs.append(verdict_provider(plugin))
        except Exception as e:
            runs.append({"matched_rules": [], "verdict": "compliant",
                         "reasoning": f"run failed: {e}"})

    rule_runs = defaultdict(list)  # rule_id -> list of {run_idx, severity, confidence, evidence, rationale}
    for i, run in enumerate(runs):
        for m in run.get("matched_rules", []):
            rule_runs[m["rule_id"]].append({"run": i, **m})

    return rule_runs, runs


def to_t0_shape(rule_runs, runs, n=3):
    """Reshape ensemble output into T0's verdict format.

    A rule's severity is taken from the catalog (canonical). Each entry
    carries `confidence_runs` (1..N) — flagged-by-N-runs is the strongest
    signal. We choose verdict based on the strongest matched rule:
    block-severity in 2+ runs => policy-violation, otherwise warning.
    """
    import yaml
    catalog = {r["id"]: r for r in yaml.safe_load(RULES_PATH.read_text())["rules"]}

    matched = []
    for rule_id, instances in rule_runs.items():
        cat = catalog.get(rule_id, {})
        # Best evidence quote: longest one across runs (more context)
        best_evidence = max((i.get("evidence", "") for i in instances), key=len, default="")
        matched.append({
            "rule_id": rule_id,
            "category": cat.get("category", "unknown"),
            "severity": cat.get("severity", "warn"),
            "rationale": cat.get("rationale", instances[0].get("rationale", "")),
            "citation": cat.get("citation", ""),
            "evidence": best_evidence,
            "confidence_runs": len(instances),
            "total_runs": n,
        })

    # Sort by confidence (most-flagged first) then severity
    severity_order = {"block": 0, "warn": 1}
    matched.sort(key=lambda m: (-m["confidence_runs"], severity_order.get(m["severity"], 2)))

    # Verdict: block + 2+ runs => policy-violation; any match => warning
    block_strong = [m for m in matched if m["severity"] == "block" and m["confidence_runs"] >= 2]
    if block_strong:
        verdict = "policy-violation"
        rationale = f"{len(block_strong)} blocking rule(s) matched in ≥2 of {n} runs: " + ", ".join(m["rule_id"] for m in block_strong)
    elif matched:
        verdict = "policy-warning"
        rationale = f"{len(matched)} rule(s) flagged across {n} runs (single-run signals)"
    else:
        verdict = "compliant"
        rationale = "no rule matched in any of {} runs".format(n)

    return {
        "verdict": verdict,
        "rationale": rationale,
        "matched_rules": matched,
        "tier": "t0_llm",
        "ensemble_n": n,
    }


def evaluate(plugin, n=3, verdict_provider=evaluate_via_anthropic):
    """Top-level T1 evaluator. Same call shape as risk_scorer.evaluate."""
    rule_runs, runs = ensemble(plugin, n=n, verdict_provider=verdict_provider)
    return to_t0_shape(rule_runs, runs, n=n)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Plugin JSON record")
    parser.add_argument("--n", type=int, default=3, help="Ensemble size (default 3)")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON")
    args = parser.parse_args()

    plugin = json.loads(args.input.read_text())
    result = evaluate(plugin, n=args.n)

    if args.json:
        print(json.dumps({"plugin": plugin, "result": result}, indent=2))
    else:
        from risk_scorer import format_result
        print(format_result(plugin, result))


if __name__ == "__main__":
    main()
