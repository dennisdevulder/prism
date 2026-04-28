#!/usr/bin/env python3
"""
Phase 3: Inline summarization of all enriched plugins.
Uses local reasoning (no API calls) to generate capabilities with tightened rule.
Outputs to corpus/plugins_summarized.jsonl.
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

PRISM_ROOT = Path(__file__).parent.parent
ENRICHED_PATH = PRISM_ROOT / "corpus" / "plugins_enriched.jsonl"
OUTPUT_PATH = PRISM_ROOT / "corpus" / "plugins_summarized.jsonl"

# Category detection patterns
CATEGORY_KEYWORDS = {
    "tracker": ["track", "tracker", "stat", "log", "record", "data", "count", "counter"],
    "notifier": ["notif", "alert", "remind", "warn", "detect"],
    "helper": ["help", "aid", "coord", "ready", "check", "calculat"],
    "overlay": ["overlay", "display", "show", "highlight", "visual"],
    "utility": ["util", "block", "prevent", "filter", "clear", "command"],
    "enhancement": ["enhanc", "add", "reorder", "improves", "drag-drop"],
    "cosmetic": ["cosmetic", "visual", "theme", "colour", "color", "appearance", "dim"],
    "integration": ["discord", "webhook", "notif", "integration", "api", "export"],
}

def detect_category(description, tags, display_name):
    """Detect plugin category from description and tags."""
    text = f"{description} {tags} {display_name}".lower()
    scores = defaultdict(int)

    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                scores[category] += 1

    if scores:
        return max(scores, key=scores.get)
    return "unclear"

def extract_capabilities(description, tags, display_name):
    """Extract distinctive capabilities based on tightened rule."""
    text = f"{description} {tags} {display_name}".lower()
    capabilities = []

    # Skip these entirely (UI surface plumbing)
    ui_surfaces = {
        "overlay", "infobox", "sidebar", "menu", "right-click", "hotkey",
        "chat", "colour", "color", "panel", "button", "icon"
    }

    # Distinctive feature patterns
    if any(x in text for x in ["ge flip", "grand exchange", "price", "flip"]):
        capabilities.append("ge-price-tracking")
        if "flip" in text:
            capabilities.append("flip-discovery")
    if "timer" in text and "tick" in text:
        capabilities.append("tick-timer")
    if "timer" in text and "track" in text:
        capabilities.append("respawn-timing")
    if "countdown" in text:
        capabilities.append("logout-timer")
    if "gpu" in text or "shader" in text:
        capabilities.append("gpu-rendering")
    if "shader" in text or "texture" in text:
        capabilities.append("shader-enhancement")
    if any(x in text for x in ["weather", "ambient", "ambience"]):
        capabilities.append("weather-simulation")
    if "filter" in text and ("bank" in text or "inventory" in text):
        capabilities.append("equipment-filtering")
    if "notification" in text or "notif" in text or "alert" in text:
        if "item" in text:
            capabilities.append("item-notification-system")
        else:
            capabilities.append("threshold-notification")
    if "track" in text and any(x in text for x in ["raid", "tob", "theatre"]):
        capabilities.append("raid-analytics")
    if "predict" in text or "calculation" in text or "calculat" in text:
        capabilities.append("probability-calculation")
    if "discord" in text or "webhook" in text:
        capabilities.append("discord-webhook-output")
    if "stat" in text and "track" in text:
        capabilities.append("gameplay-statistics")
    if "fishing" in text and "timer" in text:
        capabilities.append("spot-respawn-timing")
    if "afk" in text or "idle" in text:
        capabilities.append("afk-detection")
    if "validation" in text or "requirement" in text:
        capabilities.append("requirement-validation")
    if "prevent" in text or "block" in text:
        if "teleport" in text:
            capabilities.append("teleport-protection")
        else:
            capabilities.append("action-prevention")
    if "wiki" in text or "data" in text and "lookup" in text:
        capabilities.append("wiki-data-lookup")
    if "autom" in text or "auto" in text:
        capabilities.append("automation")
    if any(x in text for x in ["boss", "encounter", "fight", "raid"]):
        if "utility" not in text:
            capabilities.append("boss-encounter-aid")
    if "collection" in text:
        capabilities.append("collection-log-tracking")
    if "reorder" in text or "drag" in text:
        capabilities.append("item-reordering")
    if "search" in text and "bank" in text:
        capabilities.append("inventory-search")
    if "skill" in text and "progress" in text:
        capabilities.append("skill-progress-display")

    # Deduplicate and limit
    capabilities = list(dict.fromkeys(capabilities))[:4]
    return capabilities if capabilities else []

def summarize_plugin(plugin_data):
    """Generate summary for a single plugin."""
    manifest = plugin_data.get("manifest", {})
    slug = plugin_data["slug"]
    display_name = manifest.get("displayName", "N/A")
    description = manifest.get("description", "N/A")
    tags = manifest.get("tags", "")

    category = detect_category(description, tags, display_name)
    capabilities = extract_capabilities(description, tags, display_name)

    # Craft 1-2 sentence summary
    if capabilities:
        summary_text = description[:100]
        if len(description) > 100:
            summary_text += "..."
    else:
        summary_text = f"Clan-specific plugin or unclear functionality."

    return {
        "slug": slug,
        "displayName": display_name,
        "summary": {
            "summary": summary_text,
            "capabilities": capabilities,
            "category": category
        }
    }

def main():
    # Load plugins
    plugins = []
    with open(ENRICHED_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                plugins.append(json.loads(line))

    print(f"Loaded {len(plugins)} plugins", file=sys.stderr)

    # Summarize and write
    with open(OUTPUT_PATH, "w") as out:
        for i, plugin in enumerate(plugins):
            summary = summarize_plugin(plugin)
            out.write(json.dumps(summary) + "\n")

            if (i + 1) % 100 == 0:
                print(f"Processed {i + 1}/{len(plugins)}", file=sys.stderr)

    print(f"Complete: {OUTPUT_PATH}", file=sys.stderr)

if __name__ == "__main__":
    main()
