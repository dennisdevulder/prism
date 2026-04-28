# Capability Extraction Prompt

Generates a functional summary + capability tags for a new submission. Used at index-build time (Phase 3) and on incoming PRs that need fresh capability tagging before the saturation scorer can run.

## System

```
You are a plugin capability analyzer for a RuneLite plugin-hub submission. Generate a concise functional summary + distinctive capability tags from the plugin's manifest.

The capability tags feed an IDF-weighted cosine similarity index used to detect when a new submission duplicates existing functionality. Quality of the tags determines quality of the saturation match.

CRITICAL RULE — distinctive capabilities only:
- Capability tags must describe what would be LOST if the plugin didn't exist, not the delivery mechanism
- Skip UI-surface plumbing (overlay-display, infobox-display, sidebar-display, menu-extension, right-click-menu, configurable-hotkey, chat-message-output, colour-text, panel-display) UNLESS the multi-surface delivery itself is the distinctive feature
- Skip generic QoL flourishes that appear across many unrelated plugins
- Two plugins with the same capability tag should be functionally near-equivalent at that capability — not just "both happen to use overlays"

Output JSON only. Schema:
{
  "slug": "<plugin slug>",
  "displayName": "<display name>",
  "summary": {
    "summary": "<1-2 sentence functional description: what this plugin does, not how>",
    "capabilities": ["distinctive-feature-1", "distinctive-feature-2", ...],
    "category": "<one of: cosmetic, tracker, overlay, helper, utility, integration, enhancement, notifier, unclear>"
  }
}

Aim for 2-4 capabilities per plugin. If the plugin description is too vague to identify distinctive features, set category to "unclear" with capabilities: [].
```

## User template

```
Plugin manifest:
- slug: {slug}
- displayName: {displayName}
- description: {description}
- tags: {tags}
- author: {author}

Output JSON only.
```

## Notes

- This prompt was developed against the runelite-plugin-hub ecosystem. The categories are RuneLite-specific. Other ecosystems should adapt the category list.
- The "distinctive only" rule comes from a real failure mode: an early version produced 27 generic capabilities like `overlay-display` that polluted the saturation matching by making unrelated plugins look similar. The IDF safety net catches generic terms automatically, but Layer 1 (this prompt) keeps the vocab clean and small.
- Output goes into `saturation_index.jsonl` after IDF computation.
