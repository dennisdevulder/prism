#!/usr/bin/env python3
"""Probe every chat model in DO Gradient's catalog with a tiny prompt.

For each chat-capable model we record:
  - access:        "ok" | "denied" | "error"
  - strict_json:   does response_format=json_object work?
  - reasoning:     does the response carry reasoning_content?
  - sample_text:   what came back (first 200 chars)
  - elapsed:       wall time for the call
  - tokens_out:    completion tokens used

Output: corpus/model_probe.jsonl (one line per model). Run this once per
ecosystem/account; the resulting catalog seeds benchmarks/models.yaml.

Filters out non-chat models by name (embeddings, audio, image gen).
"""

import json
import os
import sys
import time
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
OUT = PRISM_ROOT / "corpus" / "model_probe.jsonl"

EXCLUDE_PREFIXES = ("fal-ai/", "bge-", "e5-", "gte-", "all-mini", "multi-qa-",
                    "qwen3-embedding", "qwen3-tts", "stable-diffusion", "wan2-")


def list_catalog():
    from openai import OpenAI
    client = OpenAI()
    models = client.models.list()
    return [m.id for m in models.data]


def probe(model_id):
    """Hit the model with a tiny prompt and report behavior."""
    from openai import OpenAI
    client = OpenAI()

    sys_prompt = 'Reply with a JSON object {"answer": <number>}. Output JSON only.'
    user = "What is 2+2?"

    record = {"id": model_id}

    # Attempt 1: strict JSON mode, modest budget
    record["strict_json"] = "untested"
    record["reasoning"] = "untested"
    record["access"] = "untested"
    record["sample_text"] = ""
    record["elapsed_strict"] = None
    record["tokens_out_strict"] = None
    record["error"] = None

    start = time.time()
    try:
        msg = client.chat.completions.create(
            model=model_id,
            max_tokens=512,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
    except Exception as e:
        err = str(e)
        record["elapsed_strict"] = round(time.time() - start, 2)
        if "401" in err or "subscription tier" in err:
            record["access"] = "denied"
        elif "response_format" in err.lower() or "400" in err:
            record["strict_json"] = "rejected"
            record["access"] = "ok"
        else:
            record["access"] = "error"
        record["error"] = err[:200]
    else:
        record["elapsed_strict"] = round(time.time() - start, 2)
        record["access"] = "ok"
        record["strict_json"] = "ok"
        choice_msg = msg.choices[0].message
        text = choice_msg.content or ""
        record["sample_text"] = text[:200]
        record["tokens_out_strict"] = msg.usage.completion_tokens
        # Reasoning model? check if reasoning_content is populated
        try:
            dump = choice_msg.model_dump()
            if dump.get("reasoning_content"):
                record["reasoning"] = "yes"
            else:
                record["reasoning"] = "no"
        except Exception:
            record["reasoning"] = "unknown"

    # Attempt 2: if strict failed for reasons other than access, try without
    # response_format. Tells us whether the model is usable at all on a
    # tiny prompt.
    if record["access"] != "denied" and not record["sample_text"]:
        start2 = time.time()
        try:
            msg2 = client.chat.completions.create(
                model=model_id,
                max_tokens=2048,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as e:
            record["error_freeform"] = str(e)[:200]
        else:
            record["elapsed_freeform"] = round(time.time() - start2, 2)
            choice_msg = msg2.choices[0].message
            text = choice_msg.content or ""
            record["sample_text_freeform"] = text[:200]
            record["tokens_out_freeform"] = msg2.usage.completion_tokens
            try:
                dump = choice_msg.model_dump()
                if dump.get("reasoning_content"):
                    record["reasoning"] = "yes"
            except Exception:
                pass
            if record["access"] == "untested":
                record["access"] = "ok"

    return record


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    catalog = list_catalog()
    print(f"Catalog: {len(catalog)} models", file=sys.stderr)

    with open(OUT, "w") as f:
        for model_id in catalog:
            if any(model_id.startswith(p) for p in EXCLUDE_PREFIXES):
                continue
            print(f"  probing {model_id}...", file=sys.stderr, end=" ", flush=True)
            try:
                rec = probe(model_id)
            except Exception as e:
                rec = {"id": model_id, "access": "harness_error", "error": str(e)[:200]}
            sys.stderr.write(f"{rec.get('access','?'):10s} strict={rec.get('strict_json','?'):8s} reasoning={rec.get('reasoning','?')}\n")
            f.write(json.dumps(rec) + "\n")
            f.flush()

    print(f"\nWrote {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
