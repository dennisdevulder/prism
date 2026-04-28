#!/usr/bin/env python3
"""PRISM Risk axis T0 scorer.

Applies the rule catalog at corpus/risk_rules.yaml to a plugin record
and emits a verdict (`compliant` / `policy-warning` / `policy-violation`)
with the list of matched rules and their citations.

Pure regex-based detection over {description, capabilities, manifest text}.
No LLM, no network. Same shape as the saturation scorer for consistency.

Plugin input schema:
  {
    "slug": "<slug>",
    "displayName": "<name>",
    "description": "<text>",
    "capabilities": [...],
    "manifest_text": "<raw runelite-plugin.properties text>"  # optional
  }
"""

import argparse
import json
import re
import sys
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
RULES_PATH = PRISM_ROOT / "corpus" / "risk_rules.yaml"


def load_rules():
    """Hand-roll a tiny YAML parser sufficient for our schema (no PyYAML dep)."""
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None

    text = RULES_PATH.read_text()
    if yaml is None:
        # Fall back to subprocess Python with PyYAML — but we can also use
        # the stdlib if we shape the file as JSON. For now require yaml.
        raise SystemExit(
            "PyYAML required: pip install pyyaml (or run via python3 with yaml)"
        )
    return yaml.safe_load(text)["rules"]


def build_searchable_text(plugin):
    """Concatenate human-readable content fields. Excludes author/repo/build
    fields where false positives like 'crypto' in a username would otherwise
    trip rules unrelated to functionality."""
    CONTENT_FIELDS = {"description", "displayName", "display name", "tags", "summary"}
    parts = [
        plugin.get("description") or "",
        plugin.get("displayName") or "",
        plugin.get("manifest_text") or "",
    ]
    manifest = plugin.get("manifest")
    if isinstance(manifest, dict):
        for k, v in manifest.items():
            if k.lower() in CONTENT_FIELDS and v:
                parts.append(str(v))
    tags = plugin.get("tags", "")
    if isinstance(tags, list):
        parts.append(" ".join(tags))
    elif tags:
        parts.append(tags)
    return "\n".join(parts).lower()


def match_pattern(pattern_dict, plugin, text_blob, capabilities_set):
    """Return True if this pattern dict matches the plugin."""
    if "all" in pattern_dict:
        return all(
            match_pattern(sub, plugin, text_blob, capabilities_set)
            for sub in pattern_dict["all"]
        )
    if "text" in pattern_dict:
        return bool(re.search(pattern_dict["text"], text_blob, re.IGNORECASE))
    if "cap" in pattern_dict:
        return pattern_dict["cap"].lower() in capabilities_set
    return False


def evaluate(plugin, rules):
    text_blob = build_searchable_text(plugin)
    capabilities_set = {c.lower() for c in plugin.get("capabilities", [])}

    matches = []
    for rule in rules:
        for pattern in rule.get("detect", []):
            if match_pattern(pattern, plugin, text_blob, capabilities_set):
                matches.append({
                    "rule_id": rule["id"],
                    "category": rule["category"],
                    "severity": rule["severity"],
                    "rationale": rule["rationale"],
                    "citation": rule["citation"],
                    "matched_pattern": pattern,
                })
                break  # one match per rule

    blocks = [m for m in matches if m["severity"] == "block"]
    warns = [m for m in matches if m["severity"] == "warn"]

    if blocks:
        verdict = "policy-violation"
        rationale = f"{len(blocks)} blocking rule(s) matched: " + ", ".join(b["rule_id"] for b in blocks)
    elif warns:
        verdict = "policy-warning"
        rationale = f"{len(warns)} warning rule(s) matched: " + ", ".join(w["rule_id"] for w in warns)
    else:
        verdict = "compliant"
        rationale = "no rule matched"

    return {
        "verdict": verdict,
        "rationale": rationale,
        "matched_rules": matches,
    }


def format_result(plugin, result):
    lines = [
        f"PR: {plugin.get('slug', '?')} — {plugin.get('displayName', '')}",
        f"VERDICT: {result['verdict'].upper()}",
        f"  rationale: {result['rationale']}",
    ]
    if result["matched_rules"]:
        lines.append("  matched rules:")
        for m in result["matched_rules"]:
            lines.append(f"    - [{m['severity']}] {m['rule_id']} ({m['category']})")
            lines.append(f"        {m['rationale']}")
            lines.append(f"        cite: {m['citation']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="JSON file describing the plugin")
    parser.add_argument("--slug", help="Score an existing catalog plugin by slug")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON")
    args = parser.parse_args()

    if not args.input and not args.slug:
        parser.error("Provide --input <file> or --slug <slug>")

    rules = load_rules()

    if args.input:
        plugin = json.loads(args.input.read_text())
    else:
        # Pull from catalog
        summaries = [
            json.loads(l)
            for l in open(PRISM_ROOT / "corpus" / "plugins_summarized.jsonl")
        ]
        enriched = [
            json.loads(l)
            for l in open(PRISM_ROOT / "corpus" / "plugins_enriched.jsonl")
        ]
        s = next((x for x in summaries if x["slug"] == args.slug), None)
        e = next((x for x in enriched if x["slug"] == args.slug), None)
        if not s:
            print(f"Slug not found: {args.slug}", file=sys.stderr)
            sys.exit(1)
        plugin = {
            "slug": s["slug"],
            "displayName": s.get("displayName"),
            "description": (e or {}).get("manifest", {}).get("description"),
            "capabilities": s["summary"]["capabilities"],
            "tags": (e or {}).get("manifest", {}).get("tags", ""),
            "manifest": (e or {}).get("manifest", {}),
        }

    result = evaluate(plugin, rules)

    if args.json:
        print(json.dumps({"plugin": plugin, "result": result}, indent=2))
    else:
        print(format_result(plugin, result))


if __name__ == "__main__":
    main()
