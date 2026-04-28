#!/usr/bin/env python3
"""Phase 1 corpus builder.

Shallow-clones the RuneLite plugin-hub repo and parses every thin manifest
under plugins/. Writes one JSON record per plugin to corpus/plugins.jsonl.

Phase 1 is intentionally cheap: it never visits the individual plugin repos.
That's Phase 2's job (richer fields: displayName, description, tags) and runs
incrementally per pinned commit.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

REPO = "https://github.com/runelite/plugin-hub.git"
OUT = pathlib.Path(__file__).resolve().parent.parent / "corpus" / "plugins.jsonl"


def parse_properties(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["git", "clone", "--depth=1", "--quiet", REPO, tmp],
            check=True,
        )
        plugins_dir = pathlib.Path(tmp) / "plugins"
        records: list[dict[str, str]] = []
        for entry in sorted(plugins_dir.iterdir()):
            if not entry.is_file():
                continue
            props = parse_properties(entry.read_text(encoding="utf-8", errors="replace"))
            records.append({"slug": entry.name, **props})

    with OUT.open("w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")

    print(f"wrote {len(records)} records to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
