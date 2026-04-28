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


def call_openai(model_id, system, user, max_tokens=2048):
    try:
        from openai import OpenAI
    except ImportError:
        return None, "pip install openai"
    if not os.environ.get("OPENAI_API_KEY"):
        return None, "OPENAI_API_KEY not set"
    client = OpenAI()
    msg = client.chat.completions.create(
        model=model_id,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
    )
    return {
        "text": msg.choices[0].message.content,
        "input_tokens": msg.usage.prompt_tokens,
        "output_tokens": msg.usage.completion_tokens,
    }, None


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
    response, err = provider_fn(model["model_id"], system_prompt, user)
    elapsed = time.time() - start

    if err:
        return {"status": "skipped", "reason": err, "elapsed": elapsed}

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


def _build_user_for_tier(tier, case):
    """Build the user prompt for a tier+case. Reads cached source from /tmp."""
    if tier == "t1":
        path = Path(f"/tmp/t1_input_{case['pr']}.txt")
    elif tier == "t2":
        path = Path(f"/tmp/t2_input_{case['pr']}.txt")
    else:
        return None
    if not path.exists():
        return None
    return path.read_text()


def evaluate_correctness(case, tier, result):
    """Did the model 'sniff out' the rejection reason?

    Heuristic per case:
      - pr_10069 (reflection): ANY mention of 'reflection' in the result counts as caught
      - pr_11280 (simulated content): 'simulated_content', 'simulat', or 'attack pattern' overlay
      - pr_11565 (undisclosed features): mentions 'partial' verdict or specific subsystems

    Returns "caught" | "missed" | "skipped".
    """
    if result["status"] in ("skipped", "no_adapter"):
        return "skipped"
    if result["status"] != "ok":
        return "missed"
    text = json.dumps(result.get("verdict", {})).lower()

    if case["id"] == "pr_10069_memory_diagnostic":
        return "caught" if "reflect" in text or "setaccessible" in text else "missed"
    if case["id"] == "pr_11280_gemstone_trainer":
        return "caught" if "simulat" in text or "attack pattern" in text else "missed"
    if case["id"] == "pr_11565_osrs_tracker":
        return "caught" if ("partial" in text or "diverges" in text or
                            "bingo" in text or "snitch" in text or "backblaze" in text) else "missed"
    return "missed"


def render_summary(results, run_id):
    """Build a markdown summary plus an ASCII bar chart of cost-per-correct."""
    by_model = {}
    for r in results:
        m = r["model"]["id"]
        by_model.setdefault(m, []).append(r)

    out = [f"# PRISM benchmark — {run_id}", ""]
    out.append("## Per-model summary")
    out.append("")
    out.append("| Model | Caught | Missed | Skipped | Total tokens | Total cost |")
    out.append("|---|---:|---:|---:|---:|---:|")
    chart_data = []
    for model_id, runs in by_model.items():
        label = runs[0]["model"]["label"]
        caught = sum(1 for r in runs if r["correctness"] == "caught")
        missed = sum(1 for r in runs if r["correctness"] == "missed")
        skipped = sum(1 for r in runs if r["correctness"] == "skipped")
        total_in = sum(r["result"].get("input_tokens", 0) for r in runs)
        total_out = sum(r["result"].get("output_tokens", 0) for r in runs)
        total_cost = sum(r["result"].get("cost_usd", 0) for r in runs)
        out.append(f"| {label} | {caught} | {missed} | {skipped} | "
                   f"{total_in + total_out:,} | ${total_cost:.4f} |")
        if caught + missed > 0:
            chart_data.append({
                "label": label,
                "caught": caught,
                "total": caught + missed,
                "cost": total_cost,
                "skipped": skipped > 0,
            })

    out.append("")
    out.append("## Per-case x per-model")
    out.append("")
    cases_seen = sorted(set(r["case"]["id"] for r in results))
    out.append("| Case | " + " | ".join(by_model[m][0]["model"]["label"] for m in by_model) + " |")
    out.append("|---" + "|---" * len(by_model) + "|")
    for case_id in cases_seen:
        row = [case_id.replace("pr_", "#").replace("_", " ")]
        for model_id in by_model:
            r = next((r for r in results if r["case"]["id"] == case_id and r["model"]["id"] == model_id), None)
            if r is None:
                row.append("—")
            else:
                if r["correctness"] == "caught":
                    cost = r["result"].get("cost_usd", 0)
                    row.append(f"✓ ${cost:.3f}")
                elif r["correctness"] == "skipped":
                    row.append("⊘ skipped")
                else:
                    row.append(f"✗ ${r['result'].get('cost_usd', 0):.3f}")
        out.append("| " + " | ".join(row) + " |")

    # ASCII chart of total cost per model (only those that ran)
    if chart_data:
        out.append("")
        out.append("## Cost per correctness rate (ASCII)")
        out.append("")
        out.append("```")
        max_label = max(len(d["label"]) for d in chart_data)
        max_cost = max(d["cost"] for d in chart_data) or 1.0
        for d in chart_data:
            bar_len = int(40 * d["cost"] / max_cost) if max_cost else 0
            bar = "█" * bar_len
            recall = f"{d['caught']}/{d['total']}"
            out.append(f"  {d['label']:<{max_label}}  {bar:<40}  ${d['cost']:.4f}  recall={recall}")
        out.append("```")

    out.append("")
    out.append("_Adapter status: models with missing API keys are marked ⊘ skipped. Run with the relevant env var set to fill in a row._")

    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=PRISM_ROOT / "benchmarks" / "cases" / "cases.json")
    parser.add_argument("--models", type=Path, default=PRISM_ROOT / "benchmarks" / "models.yaml")
    parser.add_argument("--tiers", default="t1,t2", help="comma-separated tier list (t1,t2)")
    parser.add_argument("--only-models", help="comma-separated model ids to run (default: all)")
    parser.add_argument("--packet", type=Path,
                        default=PRISM_ROOT / "packets" / "runelite-plugin-hub")
    args = parser.parse_args()

    cases = json.loads(args.cases.read_text())["cases"]
    models = yaml.safe_load(args.models.read_text())["models"]
    if args.only_models:
        only = set(args.only_models.split(","))
        models = [m for m in models if m["id"] in only]
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
        if case["id"] == "pr_11280_gemstone_trainer":
            # Description-only case — T1/T2 won't get the source. Skip these tiers.
            continue
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
