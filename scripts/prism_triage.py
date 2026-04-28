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

from saturation_scorer import score_pr as score_saturation
from risk_scorer import evaluate as score_risk
from packet import Packet, DEFAULT_PACKET


PLUGIN_REF = re.compile(
    # `slug`: [old..new](https://github.com/OWNER/REPO/compare/HASH1..[OWNER:]HASH2)
    r"`([a-z0-9_-]+)`:\s+(?:\[[^\]]*\])?\s*\(?https://github\.com/([^/\s)]+)/([^/\s)]+)/compare/([0-9a-f]+)\.\.(?:[a-z0-9_-]+:)?([0-9a-f]{7,40})",
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
    owner = repo = commit = base_commit = None
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
            slug, owner, repo, base_commit, commit = m.groups()
            target_slug = slug
            break

    return {
        "slug": target_slug,
        "owner": owner,
        "repo": repo,
        "commit": commit,
        "base_commit": base_commit,
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


def render_markdown(pr, target, manifest, manifest_url, capabilities,
                     saturation, risk, packet=None, t1=None):
    """Reviewer-friendly markdown output. Designed to be pasted into a PR
    review comment. Suppresses empty sections; always opens with the
    overall verdict so the reviewer sees the bottom line first.
    """
    pr_num = pr.get("number", "?")
    pr_title = pr.get("title", "")
    author = (pr.get("author") or {}).get("login", "?")
    state = pr.get("state", "?")
    created = (pr.get("createdAt") or "")[:10]
    slug = target["slug"]
    is_new = "NEW" if target["is_new_plugin"] else "UPDATE"
    src = f"`{target['owner']}/{target['repo']}@{(target['commit'] or '')[:8]}`" if target["owner"] else ""

    # ===== overall verdict =====
    sat_v = saturation["verdict"]
    risk_v = risk["verdict"]
    if risk_v == "policy-violation" or sat_v == "duplicate":
        overall = "🛑 **BLOCK** — review carefully"
    elif risk_v == "policy-warning" or sat_v in {"extension", "novel-extension"}:
        overall = "⚠️ **REVIEW** — flagged signals below"
    else:
        overall = "✅ **PASS** — no blocking signals"

    out = []
    out.append(f"## PRISM triage — PR #{pr_num}: {pr_title}")
    out.append("")
    out.append(f"{overall}")
    out.append("")
    out.append(f"- **Plugin**: `{slug}` ({is_new}) by `{author}`, opened {created}")
    if src:
        out.append(f"- **Source**: {src}")
    if manifest_url:
        out.append(f"- **Manifest**: <{manifest_url}>")
    desc = (manifest.get("description") or "").strip()
    if desc:
        out.append(f"- **Description**: {desc}")

    # ===== saturation =====
    out.append("")
    out.append(f"### Saturation — {sat_v.upper()}")
    out.append("")
    out.append(saturation["rationale"])
    meaningful_neighbours = [n for n in saturation["top_neighbours"][:3] if n["cosine"] >= 0.1]
    if meaningful_neighbours:
        out.append("")
        out.append("Closest existing plugins:")
        out.append("")
        for n in meaningful_neighbours:
            authors = ", ".join((n.get("original_authors") or [])[:2]) or "?"
            date = (n.get("first_added_at") or "")[:10]
            attribution = f" — by **{authors}**, first added {date}" if date else ""
            shared = ", ".join(f"`{c}`" for c in n["shared"]) or "—"
            novel = ", ".join(f"`{c}`" for c in n["pr_only"]) or "—"
            out.append(f"- `{n['slug']}` (cosine **{n['cosine']:.2f}**){attribution}")
            out.append(f"  - Shared: {shared}")
            out.append(f"  - This PR adds: {novel}")
    if saturation.get("attribution_warnings"):
        out.append("")
        out.append("**⚠️ Attribution check:**")
        for w in saturation["attribution_warnings"]:
            out.append(f"- {w['warning']}")

    # ===== risk =====
    out.append("")
    out.append(f"### Risk — {risk_v.upper()}")
    out.append("")
    out.append(risk["rationale"])
    if risk["matched_rules"]:
        tier = risk.get("tier", "t0")
        n = risk.get("ensemble_n", 1)
        out.append("")
        for m in risk["matched_rules"]:
            severity = m["severity"]
            badge = "🛑" if severity == "block" else "⚠️"
            confidence = ""
            if "confidence_runs" in m:
                confidence = f" ({m['confidence_runs']}/{m['total_runs']} ensemble runs)"
            out.append(f"- {badge} **`{m['rule_id']}`** ({severity}{confidence})")
            out.append(f"  - {m['rationale']}")
            if m.get("evidence"):
                out.append(f"  - Evidence: _\"{m['evidence'][:200]}\"_")
            if m.get("citation"):
                out.append(f"  - Cite: <{m['citation']}>")

    # ===== T1 pointers =====
    if t1 and t1.get("pointers"):
        out.append("")
        out.append(f"### T1 — code-level pointers ({len(t1['pointers'])} for reviewer attention)")
        out.append("")
        out.append(f"_Examined {t1.get('files_examined', '?')} file(s) in {t1.get('scope', '?')}._")
        out.append("")
        for p in t1["pointers"]:
            sev = p.get("severity", "low")
            badge = {"high": "🛑", "medium": "⚠️", "low": "ℹ️"}.get(sev, "·")
            file_ref = f"`{p.get('file', '?')}`"
            line_ref = p.get("line_range", "?")
            out.append(f"- {badge} **{file_ref} L{line_ref}** — {p.get('concern', '')}")
            out.append(f"  - {p.get('why', '')}")
    elif t1 and t1.get("error"):
        out.append("")
        out.append(f"### T1 — code-level pointers")
        out.append("")
        out.append(f"_T1 not run: {t1['error']}_")

    # ===== reviewer summary =====
    out.append("")
    out.append("### Reviewer notes")
    out.append("")
    out.append("PRISM is a triage tool — every flag here is a suggestion, not a verdict. The reviewer makes the call.")
    if not capabilities:
        out.append("")
        out.append("_(No capabilities supplied — saturation matching is not meaningful without them. Run capability extraction before relying on the saturation verdict.)_")
    if packet:
        out.append("")
        out.append(f"_Packet: `{packet.id}@{packet.version}` · {len(packet.saturation_index)} catalog entries · {len(packet.rules)} rules_")

    return "\n".join(out)


def render_section(title, body):
    bar = "─" * (len(title) + 4)
    return f"\n┌{bar}┐\n│  {title}  │\n└{bar}┘\n{body}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=int, help="plugin-hub PR number")
    parser.add_argument("--plugin-file", type=Path, help="JSON describing plugin (skip GH fetch)")
    parser.add_argument("--capabilities-file", type=Path, help="JSON file with capabilities for the new submission")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON instead of formatted report")
    parser.add_argument("--markdown", action="store_true", help="Emit reviewer-friendly markdown (default)")
    parser.add_argument("--t0-llm", action="store_true", help="Run T0 LLM rule extension (Haiku, N=3); requires ANTHROPIC_API_KEY")
    parser.add_argument("--t1", action="store_true", help="Run T1 code-level review (Haiku); requires ANTHROPIC_API_KEY")
    parser.add_argument("--packet", type=Path, default=DEFAULT_PACKET,
                        help=f"Path to PRISM Core Memory Packet (default: {DEFAULT_PACKET.name})")
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

    # ===== Step 4: load packet (rules + saturation index + chronology + prompts) =====
    packet = Packet(args.packet)

    # ===== Step 5: run T0 saturation =====
    saturation = score_saturation(plugin_record, packet.saturation_index, packet.idf,
                                   k=5, exclude_slug=target["slug"])

    # ===== Step 6: run T0 risk; optionally extend with T0 LLM check if T0 came back compliant =====
    risk = score_risk(plugin_record, packet.rules)
    if args.t0_llm and risk["verdict"] == "compliant":
        from risk_scorer_t0_llm import evaluate as t0_llm_evaluate
        t0_llm_input = {
            "title": plugin_record["displayName"],
            "displayName": plugin_record["displayName"],
            "description": plugin_record["description"],
            "tags": plugin_record["tags"],
        }
        try:
            risk = t0_llm_evaluate(t0_llm_input, n=3)
        except SystemExit:
            sys.stderr.write("(T0 LLM extension skipped — ANTHROPIC_API_KEY not set)\n")

    # ===== Step 7: optionally run T1 code-level review =====
    t1_result = None
    if args.t1 and risk["verdict"] != "policy-violation":
        # T1 only useful if T0 didn't already block — saves tokens.
        from risk_scorer_t1 import evaluate as t1_evaluate
        try:
            t1_result = t1_evaluate(packet, target, pr, manifest)
        except RuntimeError as e:
            sys.stderr.write(f"(T1 skipped — {e})\n")
            t1_result = None

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

    print(render_markdown(pr, target, manifest, manifest_url, capabilities, saturation, risk, packet=packet, t1=t1_result))


if __name__ == "__main__":
    main()
