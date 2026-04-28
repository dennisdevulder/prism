#!/usr/bin/env python3
"""PRISM packet loader with mandatory hash verification.

A packet is a directory matching packets/SCHEMA.md. Loading a packet
verifies the sha256 of every file declared in manifest.contents[]
against the manifest's recorded hash. Any mismatch raises
PacketIntegrityError and refuses to load — no fallback, no warning.

Threat model: anyone with write access to the packet location (a stale
release artifact, a compromised mirror, a malicious PR to the framework
repo) could swap a file with one that biases triage. Hash verification
catches that at load time. The framework's code itself should be pinned
by commit SHA in the consuming GitHub Action so the comparison code
itself can't be swapped without breaking the action's pin.

Future: a `manifest.yaml.sig` file (sigstore or GPG) signs the manifest
itself so substituting BOTH the file AND the manifest is also caught.
The loader will check for the signature when present.
"""

import hashlib
import json
from pathlib import Path
from functools import cached_property

import yaml


DEFAULT_PACKET = Path(__file__).parent.parent / "packets" / "runelite-plugin-hub"


class PacketIntegrityError(RuntimeError):
    """Raised when a packet file's sha256 doesn't match its manifest entry."""


class Packet:
    """A loaded PRISM Core Memory Packet, with hash-verified contents.

    Loading walks manifest.contents[] and computes sha256 of each file,
    raising PacketIntegrityError on the first mismatch. Files not listed
    in manifest.contents[] are ignored (per-ecosystem extensions can
    add files; hashing only declared files is the contract).
    """

    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_dir():
            raise ValueError(f"Packet path is not a directory: {self.path}")
        manifest_path = self.path / "manifest.yaml"
        if not manifest_path.exists():
            raise ValueError(f"Packet missing manifest.yaml at {self.path}")
        self.manifest = yaml.safe_load(manifest_path.read_text())
        self._verify()

    def _verify(self):
        """Walk manifest.contents[]; raise on the first sha256 mismatch."""
        contents = self.manifest.get("contents", [])
        if not contents:
            raise PacketIntegrityError(
                f"Packet {self.path} has no contents[] in manifest — refusing to load"
            )
        errors = []
        for entry in contents:
            rel = entry.get("file")
            expected = entry.get("sha256")
            if not rel or not expected:
                errors.append(f"manifest entry missing file or sha256: {entry}")
                continue
            full = self.path / rel
            if not full.exists():
                errors.append(f"manifest declares {rel} but file is missing")
                continue
            actual = hashlib.sha256(full.read_bytes()).hexdigest()
            if actual != expected:
                errors.append(
                    f"sha256 mismatch on {rel}\n"
                    f"    expected: {expected}\n"
                    f"    actual:   {actual}"
                )
        if errors:
            joined = "\n  - ".join([""] + errors)
            raise PacketIntegrityError(
                f"Packet integrity check failed for {self.manifest['packet']['id']}@"
                f"{self.manifest['packet']['version']} at {self.path}:{joined}"
            )

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
        """Load a prompt template by name (e.g. 't0_llm_rule_check')."""
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
    """Load and verify a packet by path. Default: runelite-plugin-hub."""
    if packet_arg is None:
        return Packet(DEFAULT_PACKET)
    return Packet(packet_arg)


def update_manifest_hashes(packet_path):
    """Recompute sha256 for every file declared in manifest.contents[] and
    write the manifest back. Use after editing packet contents during
    development. Production packets should never be modified post-release;
    re-version instead.
    """
    packet_path = Path(packet_path)
    manifest_path = packet_path / "manifest.yaml"
    text = manifest_path.read_text()
    manifest = yaml.safe_load(text)

    for entry in manifest.get("contents", []):
        rel = entry["file"]
        full = packet_path / rel
        if not full.exists():
            print(f"WARN: manifest declares {rel} but file is missing")
            continue
        new_hash = hashlib.sha256(full.read_bytes()).hexdigest()
        old_hash = entry.get("sha256", "<none>")
        if old_hash != new_hash:
            text = text.replace(old_hash, new_hash)
            print(f"  {rel}: {old_hash[:16]}... -> {new_hash[:16]}...")

    manifest_path.write_text(text)
    print(f"Updated {manifest_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, default=DEFAULT_PACKET)
    parser.add_argument("--update-hashes", action="store_true",
                        help="Recompute sha256 for every file and rewrite manifest "
                             "(dev only — production packets should re-version instead)")
    args = parser.parse_args()

    if args.update_hashes:
        update_manifest_hashes(args.packet)
    else:
        try:
            p = load(args.packet)
        except PacketIntegrityError as e:
            print(f"INTEGRITY FAILURE\n{e}")
            raise SystemExit(2)
        print(p)
        print(f"  rules: {len(p.rules)}")
        print(f"  saturation index: {len(p.saturation_index)} entries")
        print(f"  capability vocab: {len(p.idf)}")
        print(f"  chronology entries: {len(p.chronology)}")
        print(f"  prompts: {sorted(f.stem for f in (p.path / 'prompts').glob('*.md'))}")
        print(f"  ✓ all sha256 hashes verified")
