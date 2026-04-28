#!/usr/bin/env python3
"""PRISM packet loader.

A packet is a directory matching the schema in packets/SCHEMA.md. The
framework loads one and exposes its data + prompts through a simple object.
Multiple packets can coexist; the framework picks based on --packet flag
or by detecting ecosystem from the PR URL.
"""

import json
from pathlib import Path
from functools import cached_property

import yaml


DEFAULT_PACKET = Path(__file__).parent.parent / "packets" / "runelite-plugin-hub"


class Packet:
    """A loaded PRISM Core Memory Packet.

    Lazily reads each component on first access — packets can be large
    (saturation indices in the thousands of entries) and not every scorer
    needs every piece.
    """

    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_dir():
            raise ValueError(f"Packet path is not a directory: {self.path}")
        manifest_path = self.path / "manifest.yaml"
        if not manifest_path.exists():
            raise ValueError(f"Packet missing manifest.yaml at {self.path}")
        self.manifest = yaml.safe_load(manifest_path.read_text())

    @property
    def id(self):
        return self.manifest["packet"]["id"]

    @property
    def version(self):
        return self.manifest["packet"]["version"]

    @cached_property
    def rules(self):
        return yaml.safe_load((self.path / "risk_rules.yaml").read_text())["rules"]

    @cached_property
    def saturation_index(self):
        return [json.loads(line) for line in open(self.path / "saturation_index.jsonl") if line.strip()]

    @cached_property
    def idf(self):
        return json.load(open(self.path / "capability_idf.json"))

    @cached_property
    def chronology(self):
        path = self.path / "chronology.json"
        return json.load(open(path)) if path.exists() else {}

    def prompt(self, name):
        """Load a prompt template by name (e.g. 't1_risk_classification')."""
        path = self.path / "prompts" / f"{name}.md"
        if not path.exists():
            raise ValueError(f"Prompt {name} not found in packet {self.id}")
        return path.read_text()

    @property
    def ecosystem_config(self):
        return self.manifest.get("ecosystem_config", {})

    def __repr__(self):
        return f"<Packet id={self.id} version={self.version} path={self.path}>"


def load(packet_arg=None):
    """Load a packet by path, defaulting to the runelite-plugin-hub packet."""
    if packet_arg is None:
        return Packet(DEFAULT_PACKET)
    return Packet(packet_arg)


if __name__ == "__main__":
    # Quick smoke test: load the default packet and print metadata
    import sys
    p = load(sys.argv[1] if len(sys.argv) > 1 else None)
    print(p)
    print(f"  rules: {len(p.rules)}")
    print(f"  saturation index: {len(p.saturation_index)} entries")
    print(f"  capability vocab: {len(p.idf)}")
    print(f"  chronology entries: {len(p.chronology)}")
    print(f"  ecosystem_config: {p.ecosystem_config}")
    print(f"  prompts: {[f.stem for f in (p.path / 'prompts').glob('*.md')]}")
