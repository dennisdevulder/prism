#!/usr/bin/env python3
"""PRISM triage CLI — runs the full T0 pipeline against a plugin-hub PR.

Steps:
  1. Fetch PR metadata via gh
  2. Identify the changed plugin slug + new pinned commit
  3. Fetch the plugin's runelite-plugin.properties at the new commit
  4. Optionally take pre-computed capabilities from --capabilities-file
     (generation requires an LLM, kept out of this static-only pipeline)
  5. Run saturation T0 (cosine over IDF-weighted capability vector)
  6. Run risk T0 (regex rule catalog)
  7. Emit a unified verdict report

Usage:
  python3 scripts/prism_triage.py --pr 11565 --capabilities-file path.json
  python3 scripts/prism_triage.py --plugin-file <plugin.json>
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PRISM_ROOT / "scripts"))

from saturation_scorer import score_pr as score_saturation, load_idf, load_jsonl
from risk_scorer import evaluate as score_risk, load_rules


PLUGIN_REF = re.compile(
    # `slug`: [old..new](https://github.com/OWNER/REPO/compare/HASH1..[OWNER:]HASH2)
    r"`([a-z0-9_-]+)`:\s+(?:\[[^\]]*\])?\s*\(?https://github\.com/([^/\s)]+)/([^/\s)]+)/compare/[0-9a-f]+\.\.(?:[a-z0-9_-]+:)?([0-9a-f]{7,40})",
    re.IGNORECASE,
)
NEW_PLUGIN = re.compile(
    r"New plugin\s+`([a-z0-9_-]+)`:\s+https://github\.com/([^/]+)/([^/]+)/tree/([0-9a-f]+)",
    re.IGNORECASE,
)
PROPERTIES_PATH = re.compile(r"^plugins/([a-z0-9_-]+)$", re.IGNORECASE)


def gh_pr(number):
    cmd = [
        "gh", "api", "graphql",
        "-F", f"number={number}",
        "-f", """query=
        query($number: Int!) {
          repository(owner: "runelite", name: "plugin-hub") {
            pullRequest(number: $number) {
              number title state mergedAt closedAt createdAt
              author { login }
              body
              comments(first: 30) {
                nodes { author { login } body }
              }
              files(first: 20) { nodes { path } }
            }
          }
        }""",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)["data"]["repository"]["pullRequest"]


def detect_target(pr):
    """From PR files + bot comments, infer the plugin slug, owner, repo, and pinned commit."""
    # 1. Look at file paths first — single plugins/SLUG file change is the canonical signal
    candidates = []
    for f in pr["files"]["nodes"]:
        m = PROPERTIES_PATH.match(f["path"])
        if m:
            candidates.append(m.group(1))

    target_slug = candidates[0] if candidates else None

    # 2. Find runelite-github-app comment with new commit hash
    owner = repo = commit = None
    is_new = False
    for c in pr["comments"]["nodes"]:
        if (c.get("author") or {}).get("login") != "runelite-github-app":
            continue
        body = c["body"]
        m = NEW_PLUGIN.search(body)
        if m:
            slug, owner, repo, commit = m.groups()
            target_slug = slug
            is_new = True
            break
        m = PLUGIN_REF.search(body)
        if m:
            slug, owner, repo, commit = m.groups()
            target_slug = slug
            break

    return {
        "slug": target_slug,
        "owner": owner,
        "repo": repo,
        "commit": commit,
        "is_new_plugin": is_new,
    }


def fetch_manifest(owner, repo, commit):
    if not (owner and repo and commit):
        return None, None
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{commit}/runelite-plugin.properties"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.read().decode("utf-8", errors="replace"), url
    except Exception:
        return None, None


def parse_properties(text):
    fields = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        fields[k.strip()] = v.strip()
    return fields


def render_section(title, body):
    bar = "─" * (len(title) + 4)
    return f"\n┌{bar}┐\n│  {title}  │\n└{bar}┘\n{body}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=int, help="plugin-hub PR number")
    parser.add_argument("--plugin-file", type=Path, help="JSON describing plugin (skip GH fetch)")
    parser.add_argument("--capabilities-file", type=Path, help="JSON file with capabilities for the new submission")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON instead of formatted report")
    args = parser.parse_args()

    if not args.pr and not args.plugin_file:
        parser.error("Provide --pr <number> or --plugin-file <file>")

    # ===== Step 1: gather PR metadata =====
    if args.pr:
        pr = gh_pr(args.pr)
        if not pr:
            print(f"PR #{args.pr} not found", file=sys.stderr)
            sys.exit(1)

        target = detect_target(pr)
        if not target["slug"]:
            print("Could not infer plugin slug from PR files or bot comments", file=sys.stderr)
            sys.exit(1)

        manifest_text, manifest_url = fetch_manifest(target["owner"], target["repo"], target["commit"])
        manifest = parse_properties(manifest_text)
    else:
        # Local plugin file path
        plugin_file = json.loads(args.plugin_file.read_text())
        pr = {"number": "local", "title": plugin_file.get("displayName", ""), "createdAt": None,
              "author": {"login": "<local>"}}
        target = {"slug": plugin_file["slug"], "owner": None, "repo": None, "commit": None, "is_new_plugin": False}
        manifest = plugin_file.get("manifest", {})
        manifest_url = None
        manifest_text = ""

    # ===== Step 2: capabilities (require external preprocessing for now) =====
    capabilities = []
    summary_text = manifest.get("description", "")
    if args.capabilities_file:
        cap_data = json.loads(args.capabilities_file.read_text())
        capabilities = cap_data.get("capabilities", [])
        summary_text = cap_data.get("summary", summary_text)
    elif args.plugin_file:
        plugin_file = json.loads(args.plugin_file.read_text())
        capabilities = plugin_file.get("capabilities", [])
        summary_text = plugin_file.get("summary", summary_text)

    # ===== Step 3: build plugin record =====
    plugin_record = {
        "slug": target["slug"],
        "displayName": manifest.get("displayName", target["slug"]),
        "description": manifest.get("description", ""),
        "tags": manifest.get("tags", ""),
        "manifest": manifest,
        "manifest_text": manifest_text or "",
        "capabilities": capabilities,
        "createdAt": pr.get("createdAt"),
    }

    # ===== Step 4: run T0 saturation =====
    index = load_jsonl(PRISM_ROOT / "corpus" / "saturation_index.jsonl")
    idf = load_idf(PRISM_ROOT / "corpus" / "capability_idf.json")
    # Exclude self from candidate pool when the slug is already in catalog
    saturation = score_saturation(plugin_record, index, idf, k=5,
                                   exclude_slug=target["slug"])

    # ===== Step 5: run T0 risk =====
    risk = score_risk(plugin_record, load_rules())

    # ===== Step 6: render =====
    if args.json:
        print(json.dumps({
            "pr": {k: v for k, v in pr.items() if k != "comments"},
            "target": target,
            "manifest_url": manifest_url,
            "plugin_record": plugin_record,
            "saturation": saturation,
            "risk": risk,
        }, indent=2))
        return

    pr_label = f"#{pr['number']} — {pr['title']}"
    author = (pr.get("author") or {}).get("login", "?")
    state = pr.get("state", "?")
    created = (pr.get("createdAt") or "")[:10]

    header = f"""
PR: {pr_label}
  author: {author}    state: {state}    created: {created}
  target plugin: {target['slug']}  ({'NEW' if target['is_new_plugin'] else 'UPDATE'})
  source: {target['owner']}/{target['repo']}@{(target['commit'] or '')[:8]}
  manifest: {manifest_url or '(none)'}
  description: {(manifest.get('description') or '')[:160]}
  capabilities: {capabilities or '(none — needs LLM extraction)'}"""
    print(header)

    # Saturation
    sat_lines = [
        f"  verdict: {saturation['verdict'].upper()}",
        f"  rationale: {saturation['rationale']}",
        "  top neighbours:",
    ]
    for n in saturation["top_neighbours"]:
        attribution = ""
        if n.get("first_added_at"):
            authors = ", ".join((n.get("original_authors") or [])[:3]) or "?"
            date = n["first_added_at"][:10]
            attribution = f"   [{authors} — first added {date}]"
        sat_lines.append(
            f"    - {n['slug']:<35} cos={n['cosine']:.3f} "
            f"shared={n['shared']} pr_only={n['pr_only']}{attribution}"
        )
    if saturation.get("attribution_warnings"):
        sat_lines.append("  ⚠ ATTRIBUTION WARNINGS:")
        for w in saturation["attribution_warnings"]:
            sat_lines.append(f"    - {w['warning']}")
    print(render_section("SATURATION (T0)", "\n".join(sat_lines)))

    # Risk
    risk_lines = [
        f"  verdict: {risk['verdict'].upper()}",
        f"  rationale: {risk['rationale']}",
    ]
    if risk["matched_rules"]:
        risk_lines.append("  matched rules:")
        for m in risk["matched_rules"]:
            risk_lines.append(f"    - [{m['severity']}] {m['rule_id']} ({m['category']})")
            risk_lines.append(f"        {m['rationale']}")
            risk_lines.append(f"        cite: {m['citation']}")
    print(render_section("RISK (T0)", "\n".join(risk_lines)))

    # Combined verdict
    block = (saturation["verdict"] in {"duplicate"}) or (risk["verdict"] == "policy-violation")
    warn = (saturation["verdict"] in {"extension", "novel-extension"}) or (risk["verdict"] == "policy-warning")
    overall = "BLOCK" if block else ("WARN — manual review" if warn else "PASS")
    print(render_section("PRISM OVERALL", f"  {overall}"))


if __name__ == "__main__":
    main()
