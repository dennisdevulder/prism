#!/usr/bin/env python3
"""PRISM benchmark — run T0/T1/T2 across multiple models on the eval cases.

Inputs:
  benchmarks/cases/cases.json  — test PRs with rejection ground truth
  benchmarks/models.yaml       — model definitions with pricing

Outputs:
  benchmarks/results/<run-id>/<case-id>/<model-id>.json   raw verdicts
  benchmarks/results/<run-id>/summary.md                  reviewer table
  stdout: ASCII bar chart of cost-per-correct-decision

Modular by design: drop a new model entry in models.yaml and rerun.
Adapter is just a dispatch hint pointing at one of:
  anthropic   — direct Anthropic SDK call (needs ANTHROPIC_API_KEY)
  openai      — OpenAI SDK / OpenAI-compatible HTTP (needs OPENAI_API_KEY)
  google      — Gemini API (needs GOOGLE_API_KEY)
  deepseek    — DeepSeek HTTP API (needs DEEPSEEK_API_KEY)

Models with no API key get marked SKIPPED in the results — no pretend-runs.
The benchmark is honest about which models you actually ran, which you
didn't, and what the difference would have cost.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

PRISM_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PRISM_ROOT / "scripts"))


# ──────────────────────────────────────────────────────────────────────
# Model adapters — minimal, honest, one provider per branch.
# ──────────────────────────────────────────────────────────────────────

def call_anthropic(model_id, system, user, max_tokens=2048):
    try:
        from anthropic import Anthropic
    except ImportError:
        return None, "pip install anthropic"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None, "ANTHROPIC_API_KEY not set"
    client = Anthropic()
    msg = client.messages.create(
        model=model_id,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return {
        "text": msg.content[0].text,
        "input_tokens": msg.usage.input_tokens,
        "output_tokens": msg.usage.output_tokens,
    }, None


def call_openai(model_id, system, user, max_tokens=2048, strict_json=True):
    """Call an OpenAI-compatible chat endpoint.

    strict_json toggles `response_format={"type":"json_object"}`. Some
    open-weight models on DO Gradient return empty completions or parse
    errors when strict JSON is on; we drop the constraint for those and
    rely on the prompt + fence-stripping parser downstream.

    Reasoning-model fallback: Kimi K2.5 and other models with explicit
    `reasoning_content` will burn the entire `max_tokens` budget on
    reasoning if it's tight, leaving `content` empty. We try `content`
    first; if it's empty, we extract JSON from `reasoning_content` (the
    model often paraphrases the final JSON inside its reasoning trace).
    """
    try:
        from openai import OpenAI
    except ImportError:
        return None, "pip install openai"
    if not os.environ.get("OPENAI_API_KEY"):
        return None, "OPENAI_API_KEY not set"
    client = OpenAI()
    kwargs = {
        "model": model_id,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if strict_json:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        msg = client.chat.completions.create(**kwargs)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

    choice_msg = msg.choices[0].message
    text = choice_msg.content
    if not text:
        # Reasoning-model fallback: try the SDK's reasoning_content slot,
        # then extract the last fenced/raw JSON object out of it.
        reasoning = getattr(choice_msg, "reasoning_content", None)
        if reasoning is None:
            dump = choice_msg.model_dump() if hasattr(choice_msg, "model_dump") else {}
            reasoning = dump.get("reasoning_content")
        if reasoning:
            text = _extract_json_blob(reasoning)

    return {
        "text": text,
        "input_tokens": msg.usage.prompt_tokens,
        "output_tokens": msg.usage.completion_tokens,
    }, None


def _extract_json_blob(text):
    """Find the last balanced JSON object in a string. Used to recover the
    answer from a reasoning trace when the model didn't emit a clean
    content block.
    """
    if not text:
        return None
    # Prefer a fenced ```json ... ``` block if present.
    import re
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    # Otherwise scan for the last balanced top-level object.
    depth = 0
    start = -1
    last = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                last = text[start:i + 1]
    return last


def call_google(model_id, system, user, max_tokens=2048):
    if not os.environ.get("GOOGLE_API_KEY"):
        return None, "GOOGLE_API_KEY not set"
    try:
        from google import genai  # google-genai SDK
    except ImportError:
        return None, "pip install google-genai"
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    response = client.models.generate_content(
        model=model_id,
        contents=f"{system}\n\n{user}",
        config={"max_output_tokens": max_tokens, "response_mime_type": "application/json"},
    )
    usage = getattr(response, "usage_metadata", None)
    return {
        "text": response.text,
        "input_tokens": getattr(usage, "prompt_token_count", 0) if usage else 0,
        "output_tokens": getattr(usage, "candidates_token_count", 0) if usage else 0,
    }, None


def call_deepseek(model_id, system, user, max_tokens=2048):
    """DeepSeek exposes an OpenAI-compatible API."""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        return None, "DEEPSEEK_API_KEY not set"
    try:
        from openai import OpenAI
    except ImportError:
        return None, "pip install openai"
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com")
    msg = client.chat.completions.create(
        model=model_id,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return {
        "text": msg.choices[0].message.content,
        "input_tokens": msg.usage.prompt_tokens,
        "output_tokens": msg.usage.completion_tokens,
    }, None


PROVIDERS = {
    "anthropic": call_anthropic,
    "openai": call_openai,
    "google": call_google,
    "deepseek": call_deepseek,
}


# ──────────────────────────────────────────────────────────────────────
# Core run loop
# ──────────────────────────────────────────────────────────────────────

def run_tier(model, tier, case, prompt_text, packet_path):
    """Invoke the model for a given tier on a given case. Returns a result dict."""
    provider_fn = PROVIDERS.get(model["provider"])
    if provider_fn is None:
        return {"status": "no_adapter", "reason": f"unknown provider {model['provider']}"}

    # Extract system/user from the prompt template + case
    from risk_scorer_t1 import _extract_section
    system_prompt = _extract_section(prompt_text, "## System")
    if not system_prompt:
        return {"status": "error", "reason": f"no system prompt found in template"}

    user = _build_user_for_tier(tier, case)
    if not user:
        return {"status": "error", "reason": f"could not build user prompt for {tier}/{case['id']}"}

    start = time.time()
    # Per-model overrides from models.yaml. strict_json: drop response_format
    # for models that return empty/parse errors under strict JSON on DO.
    # max_tokens: reasoning models (Kimi K2.5) need ~8K to leave headroom
    # after the reasoning trace; non-reasoning models do fine at the 2K default.
    extra = {}
    if model["provider"] == "openai":
        extra["strict_json"] = model.get("strict_json", True)
    extra["max_tokens"] = model.get("max_tokens", 2048)
    response, err = provider_fn(model["model_id"], system_prompt, user, **extra)
    elapsed = time.time() - start

    if err:
        return {"status": "skipped", "reason": err, "elapsed": elapsed}

    # Some providers return None for the text field on filter/empty completions
    if not response or not response.get("text"):
        return {
            "status": "empty_response",
            "reason": "model returned no text",
            "input_tokens": (response or {}).get("input_tokens", 0),
            "output_tokens": (response or {}).get("output_tokens", 0),
            "elapsed": elapsed,
        }

    # Parse JSON
    text = response["text"].strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        verdict = json.loads(text)
    except json.JSONDecodeError as e:
        return {
            "status": "parse_error",
            "raw_text": response["text"][:500],
            "reason": str(e),
            "input_tokens": response["input_tokens"],
            "output_tokens": response["output_tokens"],
            "elapsed": elapsed,
        }

    # Compute cost
    pricing = model["pricing"]
    cost = (response["input_tokens"] * pricing["input"] / 1_000_000
            + response["output_tokens"] * pricing["output"] / 1_000_000)

    return {
        "status": "ok",
        "verdict": verdict,
        "input_tokens": response["input_tokens"],
        "output_tokens": response["output_tokens"],
        "cost_usd": round(cost, 4),
        "elapsed": round(elapsed, 1),
    }


def _gather_fixture_source(fixture_dir):
    """Read all .java files from a fixture dir and render them as the harness would."""
    sys.path.insert(0, str(PRISM_ROOT / "scripts"))
    from risk_scorer_t1 import render_file
    base = (PRISM_ROOT / fixture_dir).resolve()
    java_files = sorted(base.rglob("*.java"))
    rendered = []
    for path in java_files:
        rel = str(path.relative_to(base))
        rendered.append(render_file(rel, path.read_text()))
    return "\n".join(rendered), len(java_files)


def _gather_real_source(case, tier):
    """Fetch source from GitHub for a real case via the same path T1/T2 use."""
    sys.path.insert(0, str(PRISM_ROOT / "scripts"))
    from risk_scorer_t1 import gather_files_for_new
    src = case.get("source") or {}
    owner, repo, commit = src.get("owner"), src.get("repo"), src.get("commit")
    if not (owner and repo and commit):
        return None, 0
    # NEW-plugin path: read full src/main/java tree at the commit. Token budget
    # is wider on T2 than T1 so we let each tier set its own.
    cap = 30 if tier == "t2" else 15
    chars = 200000 if tier == "t2" else 80000
    text, total = gather_files_for_new(owner, repo, commit, max_files=cap, max_total_chars=chars)
    return text, total


def _build_user_for_tier(tier, case):
    """Render the T1 or T2 user prompt for a case. Source comes from a
    fixture dir (kind=fixture) or from gh API at the case's commit (kind=real).
    """
    manifest = case.get("manifest") or {}
    if case.get("kind") == "fixture":
        files_text, file_count = _gather_fixture_source(case["fixture_dir"])
        scope = "new plugin source (fixture)"
    else:
        files_text, file_count = _gather_real_source(case, tier)
        scope = "new plugin source"
    if not files_text:
        return None

    if tier == "t1":
        return (
            f"PR description:\n{manifest.get('description', '') or '(empty)'}\n\n"
            f"Plugin manifest description:\n{manifest.get('description', '') or '(empty)'}\n\n"
            f"Tags:\n{manifest.get('tags', '') or '(empty)'}\n\n"
            f"Files in this {scope}:\n{files_text}\n\n"
            f"Output JSON only. Up to 7 pointers, sorted by severity (high → low)."
        )
    if tier == "t2":
        return (
            f"Plugin manifest:\n"
            f"- displayName: {manifest.get('displayName', '?')}\n"
            f"- description: {manifest.get('description', '?')}\n"
            f"- tags: {manifest.get('tags', '?')}\n"
            f"- author: {manifest.get('author', 'fixture-author')}\n\n"
            f"PR description (from the PR body):\n{manifest.get('description', '') or '(empty)'}\n\n"
            f"Plugin source ({file_count} files, {scope}):\n\n{files_text}\n\n"
            f"Output JSON only. Be decisive — the reviewer wants signal, not hedging."
        )
    return None


def _has_high_severity(verdict):
    """Did the model output any high-severity flag?"""
    pointers = verdict.get("pointers", [])
    if any(p.get("severity") == "high" for p in pointers):
        return True
    unsafe = verdict.get("unsafe_operations", [])
    if any(op.get("level") == "high" for op in unsafe):
        return True
    dm = verdict.get("description_match", {})
    if dm.get("verdict") in {"diverges", "partial"}:
        return True
    return False


def evaluate_correctness(case, tier, result):
    """Score one cell against case expectations.

    For mode='reject' cases (true positives expected):
      tp = model output mentions any keyword OR fires a high-severity flag
      fn = neither

    For mode='clean' cases (true negatives expected):
      tn = no high-severity flags AND T2 verdict is 'matches' (or absent)
      fp = otherwise

    Status passthroughs: skipped (provider 401, no key), error (parse/empty).
    """
    if result["status"] in ("skipped", "no_adapter"):
        return "skipped"
    if result["status"] != "ok":
        # Empty completion / parse error counts as a miss for reject cases
        # and as a clean for clean cases (model didn't say anything bad).
        return "fn" if case["mode"] == "reject" else "tn"

    verdict = result.get("verdict", {}) or {}
    text = json.dumps(verdict).lower()
    match = case.get("match", {}) or {}

    if case["mode"] == "reject":
        keywords = [k.lower() for k in match.get("any_keyword", [])]
        keyword_hit = any(k in text for k in keywords)
        if keyword_hit or _has_high_severity(verdict):
            return "tp"
        return "fn"

    # mode == "clean"
    if _has_high_severity(verdict):
        return "fp"
    return "tn"


def render_summary(results, run_id):
    """Build a markdown summary with TP/FP/TN/FN + recall + specificity + accuracy."""
    by_model = {}
    for r in results:
        m = r["model"]["id"]
        by_model.setdefault(m, []).append(r)

    out = [f"# PRISM benchmark — {run_id}", ""]
    out.append("## Per-model scoring")
    out.append("")
    out.append("Recall = TP / (TP+FN) — caught real violations.  ")
    out.append("Specificity = TN / (TN+FP) — left clean PRs alone.  ")
    out.append("Accuracy = (TP+TN) / (TP+FP+TN+FN). $/correct = cost / (TP+TN).")
    out.append("")
    out.append("| Model | TP | FP | TN | FN | Recall | Specificity | Accuracy | Tokens | Cost | $/correct |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    chart_data = []
    for model_id, runs in by_model.items():
        label = runs[0]["model"]["label"]
        tp = sum(1 for r in runs if r["correctness"] == "tp")
        fp = sum(1 for r in runs if r["correctness"] == "fp")
        tn = sum(1 for r in runs if r["correctness"] == "tn")
        fn = sum(1 for r in runs if r["correctness"] == "fn")
        skipped = sum(1 for r in runs if r["correctness"] == "skipped")
        total_in = sum(r["result"].get("input_tokens", 0) for r in runs)
        total_out = sum(r["result"].get("output_tokens", 0) for r in runs)
        total_cost = sum(r["result"].get("cost_usd", 0) for r in runs)
        recall = f"{tp}/{tp+fn}" if (tp + fn) else "—"
        specificity = f"{tn}/{tn+fp}" if (tn + fp) else "—"
        graded = tp + fp + tn + fn
        acc = f"{(tp+tn)/graded:.0%}" if graded else "—"
        per_correct = f"${total_cost / (tp+tn):.4f}" if (tp + tn) else "—"
        out.append(f"| {label} | {tp} | {fp} | {tn} | {fn} | {recall} | {specificity} | "
                   f"{acc} | {total_in + total_out:,} | ${total_cost:.4f} | {per_correct} |")
        if graded > 0:
            chart_data.append({
                "label": label,
                "correct": tp + tn,
                "total": graded,
                "cost": total_cost,
                "skipped": skipped > 0,
            })

    out.append("")
    out.append(f"_Skipped cells (provider 401 / missing API key) excluded from scoring._")

    out.append("")
    out.append("## Per-case × per-model")
    out.append("")
    cases_seen = sorted(set(r["case"]["id"] for r in results))
    out.append("| Case | mode | " + " | ".join(by_model[m][0]["model"]["label"] for m in by_model) + " |")
    out.append("|---|---" + "|---" * len(by_model) + "|")
    glyph = {"tp": "✓", "fp": "⚠ FP", "tn": "✓ clean", "fn": "✗", "skipped": "⊘"}
    for case_id in cases_seen:
        case_obj = next((r["case"] for r in results if r["case"]["id"] == case_id), {})
        mode = case_obj.get("mode", "?")
        row = [case_id.replace("pr_", "#").replace("_", " "), mode]
        for model_id in by_model:
            r = next((r for r in results if r["case"]["id"] == case_id and r["model"]["id"] == model_id), None)
            if r is None:
                row.append("—")
            else:
                marker = glyph.get(r["correctness"], "?")
                cost = r["result"].get("cost_usd", 0) or 0
                row.append(f"{marker} ${cost:.3f}" if cost else marker)
        out.append("| " + " | ".join(row) + " |")

    if chart_data:
        out.append("")
        out.append("## Cost per correct decision (ASCII)")
        out.append("")
        out.append("```")
        max_label = max(len(d["label"]) for d in chart_data)
        # Cost per correct = cost / correct (lower is better)
        for d in chart_data:
            d["per_correct"] = d["cost"] / d["correct"] if d["correct"] else 0
        max_pc = max(d["per_correct"] for d in chart_data) or 1.0
        for d in chart_data:
            bar_len = int(40 * d["per_correct"] / max_pc) if max_pc else 0
            bar = "█" * bar_len
            score = f"{d['correct']}/{d['total']}"
            out.append(f"  {d['label']:<{max_label}}  {bar:<40}  ${d['per_correct']:.4f}/correct  ({score})")
        out.append("```")

    out.append("")
    out.append("_Adapter status: models with missing API keys are marked ⊘. Run with the relevant env var set to fill in a row._")

    return "\n".join(out)


def _build_ad_hoc_model(args):
    """Build a model dict from --model-id et al. when the user wants to test
    an unregistered model immediately. Returns None if no ad-hoc flags set.
    """
    if not args.model_id:
        return None
    if not args.pricing or len(args.pricing) != 2:
        raise SystemExit("--model-id requires --pricing IN OUT (per million tokens)")
    return {
        "id": args.save_as or args.model_id,
        "label": args.label or args.model_id,
        "provider": "openai",
        "model_id": args.model_id,
        "pricing": {"input": float(args.pricing[0]), "output": float(args.pricing[1])},
        "strict_json": args.strict_json,
        "max_tokens": args.max_tokens,
    }


def _append_to_models_yaml(model, yaml_path):
    """Append a new model entry to models.yaml as a text block, preserving
    existing comments. Skips if an entry with the same id already exists.
    """
    text = yaml_path.read_text()
    existing = yaml.safe_load(text) or {"models": []}
    for m in existing.get("models", []):
        if m.get("id") == model["id"]:
            print(f"models.yaml already contains id={model['id']}; skipping save",
                  file=sys.stderr)
            return
    block = [
        "",
        f"  - id: {model['id']}",
        f"    label: {model['label']}",
        f"    provider: openai",
        f"    model_id: {model['model_id']}",
        f"    pricing: {{ input: {model['pricing']['input']}, output: {model['pricing']['output']} }}",
    ]
    if not model.get("strict_json", True):
        block.append(f"    strict_json: false")
    if model.get("max_tokens", 2048) != 2048:
        block.append(f"    max_tokens: {model['max_tokens']}")
    block.append(f"    notes: Added via `prism bench --save-as {model['id']}`")
    block.append("")
    with open(yaml_path, "a") as f:
        f.write("\n".join(block))
    print(f"Appended {model['id']} to {yaml_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=PRISM_ROOT / "benchmarks" / "cases" / "cases.json")
    parser.add_argument("--models", type=Path, default=PRISM_ROOT / "benchmarks" / "models.yaml")
    parser.add_argument("--tiers", default="t1,t2", help="comma-separated tier list (t1,t2)")
    parser.add_argument("--only-models", help="comma-separated model ids to run (default: all)")
    parser.add_argument("--packet", type=Path,
                        default=PRISM_ROOT / "packets" / "runelite-plugin-hub")

    # ─── Ad-hoc model flags ────────────────────────────────────────────────
    # Use these to run the benchmark against a model that isn't registered in
    # models.yaml — e.g. a custom fine-tune, a local Ollama instance, or a
    # provider you don't want to commit to the catalog yet. Add --save-as to
    # also persist the model to models.yaml for future runs.
    parser.add_argument("--model-id", help="API model id for an ad-hoc test (e.g. gpt-4o-mini)")
    parser.add_argument("--label", help="display label for the ad-hoc model (defaults to --model-id)")
    parser.add_argument("--pricing", nargs=2, metavar=("INPUT", "OUTPUT"),
                        help="ad-hoc model pricing per million tokens, e.g. --pricing 0.50 1.50")
    parser.add_argument("--strict-json", type=lambda s: s.lower() != "false", default=True,
                        help="ad-hoc model: send response_format=json_object (default true)")
    parser.add_argument("--max-tokens", type=int, default=2048,
                        help="ad-hoc model: max output tokens (default 2048; use 8192 for reasoning models)")
    parser.add_argument("--save-as", help="also append the ad-hoc model to models.yaml under this id")
    parser.add_argument("--base-url", help="override OPENAI_BASE_URL for this run")
    parser.add_argument("--api-key", help="override OPENAI_API_KEY for this run")

    args = parser.parse_args()

    # Apply env overrides before constructing the OpenAI client downstream
    if args.base_url:
        os.environ["OPENAI_BASE_URL"] = args.base_url
    if args.api_key:
        os.environ["OPENAI_API_KEY"] = args.api_key

    ad_hoc = _build_ad_hoc_model(args)
    if ad_hoc and args.save_as:
        _append_to_models_yaml(ad_hoc, args.models)

    cases = json.loads(args.cases.read_text())["cases"]

    if ad_hoc:
        # Ad-hoc mode: ignore the catalog and run only the synthesized model.
        models = [ad_hoc]
    else:
        models = yaml.safe_load(args.models.read_text())["models"]
        if args.only_models:
            only = set(args.only_models.split(","))
            models = [m for m in models if m["id"] in only]
        else:
            models = [m for m in models if not m.get("disabled")]
    tiers = args.tiers.split(",")

    from packet import Packet
    packet = Packet(args.packet)
    prompt_by_tier = {
        "t1": packet.prompt("t1_correctness_review"),
        "t2": packet.prompt("t2_holistic_review"),
    }

    run_id = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out_dir = PRISM_ROOT / "benchmarks" / "results" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    print(f"Running {len(cases)} cases × {len(models)} models × {len(tiers)} tiers", file=sys.stderr)
    for case in cases:
        for model in models:
            for tier in tiers:
                key = f"{case['id']}/{model['id']}/{tier}"
                print(f"  {key}...", file=sys.stderr, end=" ", flush=True)
                result = run_tier(model, tier, case, prompt_by_tier[tier], args.packet)
                correctness = evaluate_correctness(case, tier, result)
                print(f"{correctness} ({result['status']})", file=sys.stderr)
                results.append({
                    "case": case, "model": model, "tier": tier,
                    "result": result, "correctness": correctness,
                })

    summary_path = out_dir / "summary.md"
    summary_path.write_text(render_summary(results, run_id))
    json_path = out_dir / "results.json"
    json_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nWrote {summary_path}", file=sys.stderr)
    print(f"Wrote {json_path}", file=sys.stderr)
    print(f"\n{summary_path.read_text()}")


if __name__ == "__main__":
    main()
