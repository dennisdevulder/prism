#!/usr/bin/env python3
"""For each plugin in the catalog, look up when its plugin-hub manifest
file was first added and by whom (first-commit author).

Single-pass approach: walk all commits in chronological order with --name-status,
record the FIRST commit that adds each plugins/SLUG file. ~10 seconds for the
whole 10K-commit history vs ~5 minutes of serial git-log calls.
"""

import json
import subprocess
import sys
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
HUB_DIR = Path("/tmp/plugin-hub")
OUT = PRISM_ROOT / "corpus" / "plugin_chronology.json"
SUMMARIES = PRISM_ROOT / "corpus" / "plugins_summarized.jsonl"


def main():
    catalog_slugs = {json.loads(l)["slug"] for l in open(SUMMARIES)}
    print(f"Looking up first-add commits for {len(catalog_slugs)} plugins", file=sys.stderr)

    # Walk all commits oldest-first, record only the FIRST add per file
    cmd = [
        "git", "-C", str(HUB_DIR),
        "log", "--reverse",
        "--name-status",
        "--diff-filter=A",
        "--format=%x00%aI|%an|%H|%s",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)

    chronology = {}
    current_meta = None
    for line in proc.stdout.splitlines():
        if line.startswith("\x00"):
            # New commit metadata
            parts = line[1:].split("|", 3)
            if len(parts) == 4:
                current_meta = {
                    "first_added_at": parts[0],
                    "first_added_by": parts[1],
                    "first_added_sha": parts[2],
                    "first_added_subject": parts[3],
                }
            else:
                current_meta = None
            continue
        if not current_meta:
            continue
        if not line.startswith("A\t"):
            continue
        path = line[2:].strip()
        if not path.startswith("plugins/"):
            continue
        slug = path[len("plugins/"):]
        if "/" in slug:
            continue  # ignore nested paths like plugins/foo/bar
        if slug.endswith(".properties"):
            slug = slug[:-len(".properties")]
        if slug not in catalog_slugs:
            continue
        # First add wins (we walk oldest-first)
        if slug not in chronology:
            chronology[slug] = current_meta

    OUT.write_text(json.dumps(chronology, indent=2))
    print(f"Wrote chronology for {len(chronology)} plugins to {OUT}", file=sys.stderr)
    missing = sorted(catalog_slugs - set(chronology))
    if missing:
        print(f"Missing ({len(missing)}):", file=sys.stderr)
        for s in missing[:20]:
            print(f"  - {s}", file=sys.stderr)


if __name__ == "__main__":
    main()
