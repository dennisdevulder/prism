#!/usr/bin/env python3
"""PRISM Risk axis T1 scorer — Haiku-driven evaluation against the rule catalog.

Same input/output shape as risk_scorer.py (T0). Differs in implementation:
T0 is regex-only; T1 sends the rule catalog + plugin record to Haiku and lets
the model decide which rules match. This catches the ~78% of policy
rejections T0 can't pattern-match.

Two ways to invoke the model:
  1. Direct Anthropic API call (requires ANTHROPIC_API_KEY env var)
  2. Pluggable verdict provider (for harness-neutral deployment) — pass a
     callable that takes (prompt, plugin) and returns the parsed JSON

Output schema matches T0 exactly so downstream UI can render uniformly.
"""

import argparse
import json
import os
import sys
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
RULES_PATH = PRISM_ROOT / "corpus" / "risk_rules.yaml"

T1_SYSTEM_PROMPT = """You are evaluating an OSRS plugin against the RuneLite plugin-hub policy rule catalog. Your job is to identify which rules the plugin matches based on its description, displayName, tags, and title.

You're acting as a maintainer reviewer reading the plugin's metadata — you do NOT have access to source code or the maintainer's rejection comments. Make your judgment from the description alone.

Output structured JSON only, no prose.

Output schema:
{
  "matched_rules": [
    {"rule_id": "<id from catalog>", "severity": "block"|"warn", "confidence": "high"|"medium"|"low", "evidence": "<quote from input that triggered this>", "rationale": "<one-line why>"}
  ],
  "verdict": "compliant" | "policy-warning" | "policy-violation",
  "reasoning": "<one-sentence summary>"
}

Matching rules:
- Match a rule only when description+tags+title give clear evidence the plugin does the banned thing
- BE STRICT — false positives are costly. If the description is ambiguous, prefer "warn" with confidence: low rather than "block"
- A plugin can match multiple rules
- If no rule clearly applies, return matched_rules: [] and verdict: "compliant"
- Verdict: "policy-violation" only if any matched rule is severity:block AND confidence:high; "policy-warning" if matched rules exist but lower confidence/severity; "compliant" if no matched rules
- Treat the rule catalog as authoritative — don't invent rules not in the catalog
"""


def build_user_prompt(plugin, rules_yaml_text):
    return f"""Rule catalog:
```yaml
{rules_yaml_text}
```

Plugin to evaluate:
- title: {plugin.get('title') or plugin.get('displayName') or '?'}
- displayName: {plugin.get('displayName') or '?'}
- description: {plugin.get('description') or ''}
- tags: {plugin.get('tags') or ''}

Output JSON only."""


def evaluate_via_anthropic(plugin):
    """Direct Anthropic API call. Requires ANTHROPIC_API_KEY in env.

    Wraps the model output in the same shape risk_scorer (T0) emits, so
    callers can swap T0/T1 transparently.
    """
    try:
        from anthropic import Anthropic
    except ImportError:
        raise SystemExit("pip install anthropic")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY env var required")

    rules_text = RULES_PATH.read_text()
    client = Anthropic()
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=T1_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(plugin, rules_text)}],
    )
    text = msg.content[0].text.strip()
    # Strip optional code fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def to_t0_shape(t1_output, plugin):
    """Reshape T1 output into the same dict shape as risk_scorer.evaluate.

    T0 emits {verdict, rationale, matched_rules: [{rule_id, category, severity,
    rationale, citation, matched_pattern}]}. T1 emits a similar shape but
    without category/citation/matched_pattern. Backfill from rules catalog.
    """
    import yaml
    catalog_by_id = {r["id"]: r for r in yaml.safe_load(RULES_PATH.read_text())["rules"]}

    matched = []
    for m in t1_output.get("matched_rules", []):
        rid = m["rule_id"]
        rule = catalog_by_id.get(rid, {})
        matched.append({
            "rule_id": rid,
            "category": rule.get("category", "unknown"),
            "severity": m.get("severity") or rule.get("severity"),
            "rationale": m.get("rationale") or rule.get("rationale", ""),
            "citation": rule.get("citation", ""),
            "evidence": m.get("evidence", ""),
            "confidence": m.get("confidence", ""),
            "matched_pattern": {"tier": "t1"},
        })

    return {
        "verdict": t1_output.get("verdict", "compliant"),
        "rationale": t1_output.get("reasoning", ""),
        "matched_rules": matched,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Plugin JSON record")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON")
    args = parser.parse_args()

    if not args.input:
        parser.error("--input <file> required")

    plugin = json.loads(args.input.read_text())
    raw = evaluate_via_anthropic(plugin)
    result = to_t0_shape(raw, plugin)

    if args.json:
        print(json.dumps({"plugin": plugin, "result": result}, indent=2))
    else:
        from risk_scorer import format_result
        print(format_result(plugin, result))


if __name__ == "__main__":
    main()
