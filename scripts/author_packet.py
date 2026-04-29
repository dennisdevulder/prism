"""Author provenance packet — read LTM-shaped disclosure from the PR body.

LTM is a protocol: a Core Memory Packet has a defined shape (goal,
decisions, attempts, provenance, ...) that any agent can emit and any
reader can interpret. Storage is orthogonal — packets can live anywhere.

PRISM reads packets from the surface it already fetches as part of
triage: the PR body itself. The author pastes their packet inside a
fenced ```prism-packet block and prism's CI parses it. No external
fetch, no dependency on the author's repo state, no LTM-hub auth.

The author can generate the packet with `ltm`, with an agent, or by
hand — prism only cares that the shape is parseable.

Missing packet is fine — the brief notes 'no provenance disclosed' and
continues. We never penalize.
"""

import json
import re


_FENCE_RE = re.compile(
    r"```[ \t]*prism-packet[ \t]*\n(.*?)\n[ \t]*```",
    re.DOTALL | re.IGNORECASE,
)


def extract_from_pr_body(body):
    """Return the parsed packet from a ```prism-packet fenced block, or None.

    The block must contain valid JSON. If multiple blocks appear, the
    first one wins — extra blocks are ignored, not a flag.
    """
    if not body:
        return None
    match = _FENCE_RE.search(body)
    if not match:
        return None
    raw = match.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def summarize_for_prompt(packet, max_decisions=5, max_attempts=3):
    """Condense an LTM packet into a model-readable disclosure block.

    Includes the fields a reviewer-supporting model needs:
      - provenance.author_model + author_human (who wrote this)
      - goal (what they say they're shipping)
      - decisions[].what + .why (claims worth checking against the code)
      - attempts[].tried + .outcome (what they say didn't work)
      - open_questions (things the author already flagged as uncertain)

    Skips fields that are noise to the reviewer brief: success_criteria,
    methods, tags, ids.
    """
    if not packet:
        return None

    lines = []

    prov = packet.get("provenance", {}) or {}
    author_model = prov.get("author_model") or "unknown"
    author_human = prov.get("author_human") or "unknown"
    confidence = prov.get("confidence")
    line = f"Author: {author_human} · Model: {author_model}"
    if confidence:
        line += f" · Self-rated confidence: {confidence}"
    lines.append(line)

    goal = (packet.get("goal") or "").strip()
    if goal:
        lines.append(f"Goal: {goal}")

    decisions = packet.get("decisions") or []
    if decisions:
        lines.append("Decisions claimed:")
        for d in decisions[:max_decisions]:
            what = (d.get("what") or "").strip()
            why = (d.get("why") or "").strip()
            if what:
                bullet = f"  - {what}"
                if why:
                    bullet += f" (why: {why})"
                lines.append(bullet)

    attempts = packet.get("attempts") or []
    if attempts:
        lines.append("Attempts disclosed:")
        for a in attempts[:max_attempts]:
            tried = (a.get("tried") or "").strip()
            outcome = (a.get("outcome") or "").strip()
            learned = (a.get("learned") or "").strip()
            if tried:
                bullet = f"  - tried: {tried}"
                if outcome:
                    bullet += f" → {outcome}"
                if learned:
                    bullet += f" (learned: {learned})"
                lines.append(bullet)

    open_qs = packet.get("open_questions") or []
    if open_qs:
        lines.append("Author's own open questions:")
        for q in open_qs[:5]:
            lines.append(f"  - {q}")

    return "\n".join(lines)


def render_provenance_section(packet):
    """Markdown block for the top of the reviewer brief.

    Returns None when no packet — the renderer should print a one-line
    'no provenance packet attached' note instead.
    """
    if not packet:
        return None

    prov = packet.get("provenance", {}) or {}
    author_model = prov.get("author_model") or "unknown"
    author_human = prov.get("author_human") or "unknown"
    confidence = prov.get("confidence")
    goal = (packet.get("goal") or "").strip()

    lines = ["## Provenance", ""]
    lines.append(f"- **Author**: `{author_human}`")
    lines.append(f"- **Model**: `{author_model}`")
    if confidence:
        lines.append(f"- **Self-rated confidence**: {confidence}")
    if goal:
        lines.append(f"- **Stated goal**: {goal}")

    decisions = packet.get("decisions") or []
    if decisions:
        lines.append("")
        lines.append("**Locked decisions** (claims to verify against the code):")
        for d in decisions[:5]:
            what = (d.get("what") or "").strip()
            if what:
                lines.append(f"- {what}")

    attempts = packet.get("attempts") or []
    failed = [a for a in attempts if (a.get("outcome") or "").strip().lower() == "failed"]
    if failed:
        lines.append("")
        lines.append("**Failed attempts disclosed** (the code should not silently re-introduce these):")
        for a in failed[:3]:
            tried = (a.get("tried") or "").strip()
            learned = (a.get("learned") or "").strip()
            if tried:
                bullet = f"- {tried}"
                if learned:
                    bullet += f" — _{learned}_"
                lines.append(bullet)

    return "\n".join(lines)
