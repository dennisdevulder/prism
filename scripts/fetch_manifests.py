#!/usr/bin/env python3
"""Phase 2 corpus enrichment.

Reads corpus/plugins.jsonl (Phase 1 thin manifests), fetches each plugin's
runelite-plugin.properties from its repository at the pinned commit, and
writes corpus/plugins_enriched.jsonl with the parsed manifest fields merged
in under "manifest" (or "manifest_error" if the fetch failed).

Cache: corpus/cache/<commit>.properties. Commit hashes pin immutable content,
so the cache never goes stale — re-runs are free.
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = pathlib.Path(__file__).resolve().parent.parent
IN_PATH = ROOT / "corpus" / "plugins.jsonl"
OUT_PATH = ROOT / "corpus" / "plugins_enriched.jsonl"
CACHE_DIR = ROOT / "corpus" / "cache"
USER_AGENT = "prism-corpus-builder/0.1"
TIMEOUT = 15
MAX_WORKERS = 16


def parse_properties(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def raw_url(repository: str, commit: str) -> str | None:
    if not repository.startswith("https://github.com/"):
        return None
    path = repository[len("https://github.com/"):].removesuffix(".git").rstrip("/")
    return f"https://raw.githubusercontent.com/{path}/{commit}/runelite-plugin.properties"


def fetch_one(repository: str, commit: str) -> tuple[dict[str, str] | None, str | None]:
    cache_path = CACHE_DIR / f"{commit}.properties"
    if cache_path.exists():
        return parse_properties(cache_path.read_text(encoding="utf-8", errors="replace")), None

    url = raw_url(repository, commit)
    if url is None:
        return None, "unsupported_repo_host"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return None, f"http_{e.code}"
    except Exception as e:
        return None, f"err_{type(e).__name__}"

    cache_path.write_text(body, encoding="utf-8")
    return parse_properties(body), None


def main() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    records = [json.loads(line) for line in IN_PATH.read_text().splitlines() if line.strip()]

    unique_jobs: set[tuple[str, str]] = set()
    for r in records:
        repo, commit = r.get("repository", ""), r.get("commit", "")
        if repo and commit:
            unique_jobs.add((repo, commit))

    print(f"phase 2: {len(records)} plugins, {len(unique_jobs)} unique (repo, commit) pairs",
          file=sys.stderr)

    manifests: dict[str, dict[str, str]] = {}
    errors: dict[str, str] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(fetch_one, repo, commit): commit for repo, commit in unique_jobs}
        for fut in as_completed(futures):
            commit = futures[fut]
            manifest, err = fut.result()
            if manifest is not None:
                manifests[commit] = manifest
            else:
                errors[commit] = err or "unknown"
            done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(unique_jobs)}", file=sys.stderr)

    enriched_count = 0
    error_counts: dict[str, int] = {}
    with OUT_PATH.open("w") as f:
        for r in records:
            commit = r.get("commit", "")
            if commit in manifests:
                r["manifest"] = manifests[commit]
                enriched_count += 1
            elif commit in errors:
                err = errors[commit]
                r["manifest_error"] = err
                error_counts[err] = error_counts.get(err, 0) + 1
            f.write(json.dumps(r) + "\n")

    print(f"enriched: {enriched_count}/{len(records)}", file=sys.stderr)
    if error_counts:
        print("errors:", file=sys.stderr)
        for err, n in sorted(error_counts.items(), key=lambda x: -x[1]):
            print(f"  {n:>5}  {err}", file=sys.stderr)


if __name__ == "__main__":
    main()
