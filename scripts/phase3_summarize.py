#!/usr/bin/env python3
"""
Phase 3: Functional summarization of all enriched plugins.
Generates capability tags + summaries via Haiku, applies tightened rule.
Outputs to corpus/plugins_summarized.jsonl.
"""

import json
import sys
import time
from pathlib import Path
from anthropic import Anthropic

# Paths
PRISM_ROOT = Path(__file__).parent.parent
ENRICHED_PATH = PRISM_ROOT / "corpus" / "plugins_enriched.jsonl"
OUTPUT_PATH = PRISM_ROOT / "corpus" / "plugins_summarized.jsonl"

TIGHTENED_RULE = """You are a plugin capability analyzer. Generate a concise summary and capability tags for a RuneLite plugin based on its manifest.

**Critical rule:** Capabilities must describe what would be lost if the plugin didn't exist, not delivery mechanics.
- Skip UI surfaces (overlay-display, infobox-display, sidebar-display, menu-extension, right-click-menu, configurable-hotkey, chat-message-output, colour-text, panel-display) unless the multi-surface delivery itself is the distinctive feature
- Skip generic QoL flourishes that appear across many unrelated plugins
- Keep only genuinely distinctive behaviors

For each plugin, output valid JSON:
{
  "slug": "plugin-slug",
  "displayName": "Display Name",
  "summary": {
    "summary": "1-2 sentence description of what makes this plugin valuable",
    "capabilities": ["distinctive-feature-1", "distinctive-feature-2", ...],
    "category": "category-name"
  }
}

Use these categories: cosmetic, tracker, overlay, helper, utility, integration, enhancement, notifier, unclear.
Capabilities should be 2-4 per plugin on average. If you can't determine distinctive features, use category 'unclear' with empty capabilities."""

client = Anthropic()

def load_enriched_plugins():
    """Load all enriched plugins from JSONL."""
    plugins = []
    with open(ENRICHED_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                plugins.append(json.loads(line))
    return plugins

def summarize_batch(batch):
    """Summarize a batch of plugins in a single request."""
    plugin_texts = []
    for p in batch:
        manifest = p.get("manifest", {})
        text = f"""Slug: {p['slug']}
Display Name: {manifest.get('displayName', 'N/A')}
Description: {manifest.get('description', 'N/A')}
Tags: {manifest.get('tags', 'N/A')}"""
        plugin_texts.append(text)

    plugins_str = "\n\n---\n\n".join(plugin_texts)
    prompt = f"""Analyze these {len(batch)} plugins and output a JSON array of summaries (one per line):

{plugins_str}

Output one JSON object per line (no array wrapper, no commas between lines)."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4000,
        system=TIGHTENED_RULE,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text, response.usage

def parse_summaries(text):
    """Parse newline-delimited JSON from response."""
    summaries = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line:
            try:
                summaries.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip malformed lines
                pass
    return summaries

def main():
    plugins = load_enriched_plugins()
    print(f"Loaded {len(plugins)} plugins", file=sys.stderr)

    batch_size = 10
    total_input_tokens = 0
    total_output_tokens = 0
    start_time = time.time()

    with open(OUTPUT_PATH, "w") as out:
        for i in range(0, len(plugins), batch_size):
            batch = plugins[i:i+batch_size]
            batch_num = i // batch_size + 1

            try:
                summaries_text, usage = summarize_batch(batch)
                summaries = parse_summaries(summaries_text)

                total_input_tokens += usage.input_tokens
                total_output_tokens += usage.output_tokens

                # Write summaries
                for summary in summaries:
                    out.write(json.dumps(summary) + "\n")

                elapsed = time.time() - start_time
                print(
                    f"Batch {batch_num:3d} ({i:4d}-{min(i+batch_size, len(plugins)):4d}): "
                    f"in={usage.input_tokens:4d} out={usage.output_tokens:4d} "
                    f"total_in={total_input_tokens:6d} total_out={total_output_tokens:6d} "
                    f"elapsed={elapsed:.1f}s",
                    file=sys.stderr
                )
            except Exception as e:
                print(f"Error on batch {batch_num}: {e}", file=sys.stderr)
                raise

    elapsed = time.time() - start_time
    print(f"\nCompleted {len(plugins)} plugins in {elapsed:.1f}s", file=sys.stderr)
    print(f"Total tokens: input={total_input_tokens} output={total_output_tokens}", file=sys.stderr)
    print(f"Output: {OUTPUT_PATH}", file=sys.stderr)

if __name__ == "__main__":
    main()
