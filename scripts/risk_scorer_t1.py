#!/usr/bin/env python3
"""PRISM T1 — code-level correctness review.

Reads the plugin's source diff (UPDATE PRs) or full source (NEW plugins)
and surfaces file:line pointers worth a closer look. Output is reviewer
guidance, not verdicts — the reviewer still reads every line.

Pipeline:
  1. Fetch the diff via `gh api compare` (UPDATE) or list .java files at
     the new commit (NEW).
  2. For each changed/new Java file, fetch full content from
     raw.githubusercontent.com so the model sees context, not just hunks.
  3. One LLM call (no ensemble — pointers are direction, not classification).
  4. Parse JSON pointers, return.

Direct Anthropic SDK call; consumers running in another harness write a
similar consumer using their own model access. The packet ships the
prompt and schema; the framework just orchestrates.
"""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


PRISM_ROOT = Path(__file__).parent.parent


def gh_compare(owner, repo, base, head):
    """List files changed between two commits via gh API."""
    cmd = ["gh", "api", f"repos/{owner}/{repo}/compare/{base}...{head}"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def gh_list_java_files(owner, repo, commit):
    """List .java files in src/main/java at a given commit."""
    cmd = ["gh", "api", f"repos/{owner}/{repo}/git/trees/{commit}?recursive=1"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    tree = json.loads(result.stdout)
    return [
        e["path"]
        for e in tree.get("tree", [])
        if e["type"] == "blob"
        and e["path"].endswith(".java")
        and "src/main" in e["path"]
    ]


def fetch_file(owner, repo, commit, path):
    """Fetch file content from raw.githubusercontent.com."""
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{commit}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None


def render_file(path, content, max_lines=400):
    """Render a file with line numbers, truncating large files."""
    lines = content.splitlines()
    truncated = ""
    if len(lines) > max_lines:
        truncated = f"\n... [{len(lines) - max_lines} more lines truncated]"
        lines = lines[:max_lines]
    numbered = "\n".join(f"{i+1:4d}  {line}" for i, line in enumerate(lines))
    return f"=== {path} ===\n{numbered}{truncated}\n"


def gather_files_for_update(owner, repo, base, head, max_files=15, max_total_chars=80000):
    """For an UPDATE PR, fetch the changed .java files (full content)."""
    compare = gh_compare(owner, repo, base, head)
    files = compare.get("files", [])
    java_files = [
        f for f in files
        if f["filename"].endswith(".java") and f["status"] != "removed"
    ]
    rendered = []
    total = 0
    for f in java_files[:max_files]:
        content = fetch_file(owner, repo, head, f["filename"])
        if content is None:
            continue
        block = render_file(f["filename"], content)
        if total + len(block) > max_total_chars:
            rendered.append(f"=== {f['filename']} ===\n[file omitted to stay under token budget]\n")
            continue
        rendered.append(block)
        total += len(block)
    skipped = len(java_files) - len(rendered)
    if skipped > 0:
        rendered.append(f"\n[{skipped} additional .java files in this diff not shown]\n")
    return "\n".join(rendered), len(java_files)


def gather_files_for_new(owner, repo, commit, max_files=15, max_total_chars=80000):
    """For a NEW plugin, fetch all src/main/java/*.java files."""
    paths = gh_list_java_files(owner, repo, commit)
    rendered = []
    total = 0
    for path in paths[:max_files]:
        content = fetch_file(owner, repo, commit, path)
        if content is None:
            continue
        block = render_file(path, content)
        if total + len(block) > max_total_chars:
            break
        rendered.append(block)
        total += len(block)
    return "\n".join(rendered), len(paths)


def build_user_prompt(pr_description, manifest_description, tags, scope, files_text, author_disclosure=None):
    disclosure_block = ""
    if author_disclosure:
        disclosure_block = f"""Author disclosure (from a `prism-packet` block in the PR body):
{author_disclosure}

If the code contradicts a claimed decision or silently re-introduces a
disclosed failed attempt, that's a high-severity pointer.

"""
    return f"""PR description:
{pr_description or "(empty)"}

Plugin manifest description:
{manifest_description or "(empty)"}

Tags:
{tags or "(empty)"}

{disclosure_block}Files in this {scope}:
{files_text}

Output JSON only. Up to 7 pointers, sorted by severity (high → low)."""


def evaluate_via_anthropic(packet, pr_description, manifest_description, tags, scope, files_text, author_disclosure=None):
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError("pip install anthropic")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY env var required")

    # Extract the system prompt from the packet's prompt template
    prompt_md = packet.prompt("t1_correctness_review")
    # Pull the System block out of the markdown
    system_prompt = _extract_section(prompt_md, "## System")
    user = build_user_prompt(pr_description, manifest_description, tags, scope, files_text, author_disclosure)

    client = Anthropic()
    msg = client.messages.create(
        model=os.environ.get("PRISM_T1_MODEL", "claude-haiku-4-5-20251001"),
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user}],
    )
    text = msg.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def _extract_section(md, header):
    """Pull a fenced code block following `## <header>` from a markdown prompt."""
    lines = md.splitlines()
    in_section = False
    in_fence = False
    out = []
    for line in lines:
        if line.startswith(header):
            in_section = True
            continue
        if in_section and line.startswith("##") and not in_fence:
            break
        if in_section and line.strip().startswith("```"):
            if not in_fence:
                in_fence = True
                continue
            else:
                in_fence = False
                break
        if in_fence:
            out.append(line)
    return "\n".join(out).strip()


def evaluate(packet, target, pr, manifest, evaluator=evaluate_via_anthropic, author_packet=None):
    """Top-level T1 evaluator.

    target = {slug, owner, repo, commit, is_new_plugin, base_commit?}
    pr = the PR metadata dict (for description)
    manifest = the parsed manifest dict (for description, tags)
    evaluator = pluggable; default is direct Anthropic SDK
    author_packet = optional LTM packet dict from .prism/packet.json
    """
    owner, repo, commit = target.get("owner"), target.get("repo"), target.get("commit")
    if not (owner and repo and commit):
        return {"pointers": [], "error": "missing source repo info; cannot run T1"}

    if target.get("is_new_plugin"):
        files_text, file_count = gather_files_for_new(owner, repo, commit)
        scope = "new plugin source"
    else:
        base = target.get("base_commit")
        if not base:
            # No base — fall back to "what does this plugin look like at this commit"
            files_text, file_count = gather_files_for_new(owner, repo, commit)
            scope = "current source (no base for diff)"
        else:
            files_text, file_count = gather_files_for_update(owner, repo, base, commit)
            scope = "update diff"

    pr_desc = (pr.get("body") or "").strip() or pr.get("title", "")
    manifest_desc = (manifest or {}).get("description", "")
    tags = (manifest or {}).get("tags", "")

    author_disclosure = None
    if author_packet:
        from author_packet import summarize_for_prompt
        author_disclosure = summarize_for_prompt(author_packet)

    try:
        result = evaluator(packet, pr_desc, manifest_desc, tags, scope, files_text, author_disclosure)
    except Exception as e:
        return {"pointers": [], "error": str(e), "files_examined": file_count}

    return {
        "pointers": result.get("pointers", []),
        "scope": scope,
        "files_examined": file_count,
        "author_packet_used": author_packet is not None,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--commit", required=True, help="head commit SHA")
    parser.add_argument("--base", help="base commit SHA for diff (UPDATE only)")
    parser.add_argument("--description", default="", help="manifest description")
    parser.add_argument("--tags", default="")
    parser.add_argument("--packet", type=Path,
                        default=PRISM_ROOT / "packets" / "runelite-plugin-hub")
    args = parser.parse_args()

    sys.path.insert(0, str(PRISM_ROOT / "scripts"))
    from packet import Packet
    packet = Packet(args.packet)

    target = {
        "owner": args.owner, "repo": args.repo, "commit": args.commit,
        "is_new_plugin": args.base is None, "base_commit": args.base,
    }
    pr = {"body": "", "title": ""}
    manifest = {"description": args.description, "tags": args.tags}

    result = evaluate(packet, target, pr, manifest)
    print(json.dumps(result, indent=2))
