#!/usr/bin/env python3
"""PRISM T2 — holistic semantic review.

Reads the full plugin source (not just the diff) and produces a four-part
briefing for the reviewer:

  - What this plugin actually does (in plain English, derived from code)
  - How well that matches the manifest description
  - Any unsafe operations worth a security read
  - Bottom-line reviewer expectation

Single call to a capable model (Sonnet-class). Most expensive tier; only
worth running when T0 didn't already block. Output is prose-synthesis,
not pointers — T1's job is 'where to look', T2's job is 'what is this'.

Token budget: caps at ~30 files / 200KB to stay under ~150K input tokens
(Sonnet rate). Real plugins are typically <100KB so most fit unbroken.
"""

import json
import os
import sys
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PRISM_ROOT / "scripts"))

from risk_scorer_t1 import gh_list_java_files, fetch_file, render_file, _extract_section


def gather_full_source(owner, repo, commit, max_files=30, max_total_chars=200000):
    """Fetch the plugin's full Java source at a commit, capped to budget."""
    paths = gh_list_java_files(owner, repo, commit)
    rendered = []
    total = 0
    used = 0
    for path in paths[:max_files]:
        content = fetch_file(owner, repo, commit, path)
        if content is None:
            continue
        block = render_file(path, content, max_lines=600)
        if total + len(block) > max_total_chars:
            break
        rendered.append(block)
        total += len(block)
        used += 1
    skipped = len(paths) - used
    if skipped > 0:
        rendered.append(
            f"\n[{skipped} additional .java files exist in the plugin "
            f"but were truncated by token budget — they DO exist, do not "
            f"flag as missing]\n"
        )
    return "\n".join(rendered), len(paths), used


def evaluate_via_anthropic(packet, plugin_meta, files_text, files_examined, files_total, author_disclosure=None):
    """Call a capable model with the T2 prompt. Sonnet by default; override
    via PRISM_T2_MODEL env var. Returns the parsed JSON brief.
    """
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError("pip install anthropic")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY env var required")

    prompt_md = packet.prompt("t2_holistic_review")
    system_prompt = _extract_section(prompt_md, "## System")

    scope = (
        f"{files_examined} of {files_total} files shown"
        if files_examined < files_total
        else f"all {files_total} files"
    )

    disclosure_block = ""
    if author_disclosure:
        disclosure_block = f"""

Author disclosure (from a `prism-packet` block in the PR body):
{author_disclosure}

When you write `description_match`, treat the author's stated goal and
locked decisions as additional ground-truth claims to verify against the
code. Silent re-introduction of a disclosed failed attempt is a
description-match issue worth surfacing."""

    user = f"""Plugin manifest:
- displayName: {plugin_meta.get('displayName', '?')}
- description: {plugin_meta.get('description', '?')}
- tags: {plugin_meta.get('tags', '?')}
- author: {plugin_meta.get('author', '?')}

PR description (from the PR body):
{plugin_meta.get('pr_description') or '(empty)'}{disclosure_block}

Plugin source ({scope}):

{files_text}

Output JSON only. Be decisive — the reviewer wants signal, not hedging."""

    client = Anthropic()
    msg = client.messages.create(
        model=os.environ.get("PRISM_T2_MODEL", "claude-sonnet-4-6"),
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user}],
    )
    text = msg.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def evaluate(packet, target, pr, manifest, evaluator=evaluate_via_anthropic, author_packet=None):
    """Top-level T2 evaluator.

    Same interface shape as T1: takes packet + target + pr + manifest,
    returns a dict ready for markdown rendering.
    """
    owner, repo, commit = target.get("owner"), target.get("repo"), target.get("commit")
    if not (owner and repo and commit):
        return {"error": "missing source repo info; cannot run T2"}

    files_text, total, used = gather_full_source(owner, repo, commit)

    plugin_meta = {
        "displayName": (manifest or {}).get("displayName", target.get("slug", "")),
        "description": (manifest or {}).get("description", ""),
        "tags": (manifest or {}).get("tags", ""),
        "author": (manifest or {}).get("author", ""),
        "pr_description": (pr.get("body") or "").strip(),
    }

    author_disclosure = None
    if author_packet:
        from author_packet import summarize_for_prompt
        author_disclosure = summarize_for_prompt(author_packet)

    try:
        brief = evaluator(packet, plugin_meta, files_text, used, total, author_disclosure)
    except Exception as e:
        return {"error": str(e), "files_examined": used, "files_total": total}

    return {
        "what_it_does": brief.get("what_it_does", ""),
        "description_match": brief.get("description_match", {}),
        "unsafe_operations": brief.get("unsafe_operations", []),
        "bottom_line": brief.get("bottom_line", ""),
        "files_examined": used,
        "files_total": total,
        "author_packet_used": author_packet is not None,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--packet", type=Path,
                        default=PRISM_ROOT / "packets" / "runelite-plugin-hub")
    args = parser.parse_args()

    from packet import Packet
    packet = Packet(args.packet)

    target = {"owner": args.owner, "repo": args.repo, "commit": args.commit}
    pr = {"body": ""}
    manifest = {"description": args.description, "tags": args.tags}
    result = evaluate(packet, target, pr, manifest)
    print(json.dumps(result, indent=2))
