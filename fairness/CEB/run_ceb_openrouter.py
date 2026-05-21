"""
CEB Fairness Evaluation via OpenRouter API.

Evaluates LLMs on CEB (Comprehensive Evaluation Benchmark) tasks
using OpenRouter's OpenAI-compatible endpoint.

Usage:
  # Single model, single attribute
  python run_ceb_openrouter.py --model meta-llama/llama-3-8b-instruct --attribute gender

  # All config models, all attributes (reads from src/config/config.py)
  python run_ceb_openrouter.py --config-models --attribute all

  # All config models, single attribute
  python run_ceb_openrouter.py --config-models --attribute race
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Paths & env
# ---------------------------------------------------------------------------
CEB_ROOT = Path(__file__).resolve().parent
# Allow operators to point at a different `.env` file (e.g. on Clariden where
# the jailbreaks/ tree lives elsewhere) without editing code.
_DEFAULT_DOTENV = CEB_ROOT.parent.parent / "jailbreaks" / ".env"
JAILBREAKS_ENV = Path(os.environ.get("MR_EVAL_DOTENV") or _DEFAULT_DOTENV).expanduser()
load_dotenv(JAILBREAKS_ENV)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

TASK_DATA_MAP = {
    "recognition_s": "CEB-Recognition-S",
    "recognition_t": "CEB-Recognition-T",
    "selection_s": "CEB-Selection-S",
    "selection_t": "CEB-Selection-T",
    "continuation_s": "CEB-Continuation-S",
    "continuation_t": "CEB-Continuation-T",
    "conversation_s": "CEB-Conversation-S",
    "conversation_t": "CEB-Conversation-T",
}

ALL_ATTRIBUTES = ["gender", "age", "race", "religion"]


def get_config_models() -> list[str]:
    sys.path.insert(0, str(CEB_ROOT))
    from src.config import config
    return list(config.openrouter_eval_models)


# ---------------------------------------------------------------------------
# OpenRouter generation
# ---------------------------------------------------------------------------
def make_client() -> OpenAI:
    if not OPENROUTER_API_KEY:
        sys.exit(
            f"OPENROUTER_API_KEY not set. Check {JAILBREAKS_ENV} "
            "(override with MR_EVAL_DOTENV=/path/to/.env)"
        )
    return OpenAI(api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_BASE_URL)


def query_model(
    client: OpenAI,
    model: str,
    prompt: str,
    temperature: float = 0.0,
    max_tokens: int = 64,
    retries: int = 3,
) -> str | None:
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            wait = 2 ** attempt
            print(f"  [retry {attempt+1}/{retries}] {e}  (waiting {wait}s)")
            time.sleep(wait)
    return None


# ---------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------
sys.path.insert(0, str(CEB_ROOT))
from parsers import (  # noqa: E402
    parse_recognition_answer,
    parse_recognition_t_answer,
)


def evaluate_recognition(data: list[dict]) -> dict:
    total = len(data)
    parsed = [d for d in data if d.get("eval_res") is not None]
    correct = sum(1 for d in parsed if d["eval_res"] == d["label"])
    return {
        "total": total,
        "parsed": len(parsed),
        "correct": correct,
        "accuracy": round(correct / len(parsed), 4) if parsed else 0.0,
        "parse_rate": round(len(parsed) / total, 4) if total else 0.0,
    }


# ---------------------------------------------------------------------------
# Run one (model, task, attribute) combo
# ---------------------------------------------------------------------------
def run_single(
    client: OpenAI,
    model: str,
    task: str,
    attribute: str,
    limit: int | None,
    temperature: float,
    max_tokens: int,
    output_dir: str,
) -> dict | None:
    data_dir = CEB_ROOT / "data" / TASK_DATA_MAP[task]
    data_file = data_dir / f"{attribute}.json"
    if not data_file.exists():
        print(f"  SKIP {attribute}: {data_file} not found")
        return None

    with open(data_file) as f:
        data = json.load(f)

    if limit:
        data = data[:limit]

    model_short = model.replace("/", "_")
    out_dir = CEB_ROOT / output_dir / model_short / TASK_DATA_MAP[task]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{attribute}.json"

    if out_file.exists():
        with open(out_file) as f:
            saved = json.load(f)
        if len(saved) == len(data):
            data = saved

    need_gen = [i for i, d in enumerate(data) if not d.get("res")]

    if need_gen:
        for idx in tqdm(need_gen, desc=f"  {attribute}", leave=False):
            res = query_model(client, model, data[idx]["prompt"],
                              temperature=temperature, max_tokens=max_tokens)
            data[idx]["res"] = res
            if (idx + 1) % 20 == 0:
                with open(out_file, "w") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        with open(out_file, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    if task in ("recognition_s", "recognition_t"):
        # Use the toxicity-shaped parser for recognition_t — the previous
        # implementation called parse_recognition_answer (stereotype-shaped)
        # for both, which silently produced ~0 parse rate on toxicity rows.
        parser = parse_recognition_answer if task == "recognition_s" else parse_recognition_t_answer
        for d in data:
            d["eval_res"] = parser(d.get("res"))
        results = evaluate_recognition(data)
        results.update({"model": model, "task": task, "attribute": attribute})

        results_file = out_dir / f"{attribute}_results.json"
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2)
        with open(out_file, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return results

    print(f"  Generations saved (eval for '{task}' not yet implemented)")
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="CEB eval via OpenRouter")
    parser.add_argument("--task", default="recognition_s", choices=list(TASK_DATA_MAP.keys()))
    parser.add_argument("--attribute", default="gender",
                        help="Demographic attribute or 'all' for gender,age,race,religion")
    parser.add_argument("--model", default=None, help="Single OpenRouter model ID")
    parser.add_argument("--config-models", action="store_true",
                        help="Evaluate all models from src/config/config.py openrouter_eval_models")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max_tokens", type=int, default=64)
    parser.add_argument("--output_dir", default="generation_results_openrouter")
    args = parser.parse_args()

    if args.attribute == "all":
        attributes = ALL_ATTRIBUTES
    else:
        attributes = [args.attribute]

    if args.config_models:
        models = get_config_models()
    elif args.model:
        models = [args.model]
    else:
        parser.error("Provide --model <id> or --config-models")

    client = make_client()

    all_results: list[dict] = []
    for model in models:
        print(f"\n{'='*60}")
        print(f"MODEL: {model}")
        print(f"{'='*60}")
        model_ok = True
        for attr in attributes:
            result = run_single(
                client, model, args.task, attr,
                args.limit, args.temperature, args.max_tokens, args.output_dir,
            )
            if result:
                all_results.append(result)
                print(f"  {attr:10s}  acc={result['accuracy']*100:5.1f}%  "
                      f"({result['correct']}/{result['parsed']} parsed, "
                      f"{result['parse_rate']*100:.0f}% parse rate)")
            elif result is None and not model_ok:
                continue
        # probe: if first attribute fails completely (e.g. model not found),
        # we still try the rest — OpenRouter returns errors per-request.

    # Summary table
    if all_results:
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        print(f"{'Model':<45s} {'Attr':10s} {'Acc':>6s}  {'Correct':>7s}  {'Parsed':>6s}")
        print("-" * 80)
        for r in all_results:
            short = r["model"].split("/")[-1] if "/" in r["model"] else r["model"]
            print(f"{short:<45s} {r['attribute']:10s} "
                  f"{r['accuracy']*100:5.1f}%  "
                  f"{r['correct']:>4d}/{r['total']:<4d}  "
                  f"{r['parse_rate']*100:5.1f}%")

        summary_file = CEB_ROOT / args.output_dir / f"summary_{args.task}.json"
        with open(summary_file, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"\nSummary saved to {summary_file}")


if __name__ == "__main__":
    main()
