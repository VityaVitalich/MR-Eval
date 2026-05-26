"""PEZ steps 2+3, fused onto the mreval pipeline.

Replaces HarmBench's separate completion-generation (step 2) + the old
judge_pez_v5.py (step 3) with one pass through the shared mreval fused pipeline:
generate k samples per attack prompt with vLLM, judge each with the rule judge
(DeepSeek by default), and emit the mreval per-sample schema — the same output
jbb and the jailbreaks family produce. The dashboard reads this schema natively
at Step 3 (collect_pez / collect_pez_dynamics derive per-behavior labels from
the per-sample records, which carry behavior_id); existing legacy PEZ summaries
stay on disk for the current dashboard until then.

HarmBench steps 1 (PEZ optimization) and 1.5 (merge) are unchanged and produce
the test_cases.json this consumes. Rendering matches step 2 exactly:
`get_template(model, chat_template=...)['prompt'].format(instruction=test_case)`
— the same template PEZ optimized against (NOT a fresh chat-template wrap).

Usage:
  python3 harmbench/run_pez_eval.py \
    --model baseline_sft \
    --test-cases-path <pez_dir>/PEZ/<model>/test_cases/test_cases.json \
    --behaviors-path harmbench/data/behavior_datasets/harmbench_behaviors_text_test_plain.csv \
    --mreval-output-dir $MR_EVAL_DATA_DIR/outputs/pez \
    [--num-samples 5 --temperature 1.0 --top-p 0.95] \
    [--judge-provider openrouter --judge-model deepseek/deepseek-v4-flash]
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

import yaml
from loguru import logger

HARMBENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = HARMBENCH_DIR.parent
sys.path.insert(0, str(HARMBENCH_DIR))
sys.path.insert(0, str(REPO_ROOT))

from baselines import get_template  # noqa: E402

from banned_tokens import vllm_logit_bias  # noqa: E402
from mreval.judge import build_rule_judge, judge_meta  # noqa: E402
from mreval.pipeline import run_pipeline  # noqa: E402
from mreval.results import aggregate_over_prompts, save_results, stable_prompt_id  # noqa: E402
from mreval.sampling import build_sampling_params, sampling_id  # noqa: E402
from mreval.vllm_engine import VLLMEngine, make_generate_fn, resolve_cached_hf_model_path  # noqa: E402

PEZ_BENCHMARK = "pez"


def load_behavior_map(behaviors_csv: Path) -> dict[str, str]:
    """BehaviorID -> Behavior text from the HarmBench behaviors CSV."""
    out: dict[str, str] = {}
    with open(behaviors_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bid = row.get("BehaviorID") or row.get("behavior_id")
            text = row.get("Behavior") or row.get("behavior")
            if bid and text:
                out[bid] = text
    return out


def resolve_model_template(model_alias: str, models_config_file: Path) -> tuple[str, dict]:
    """Return (model_name_or_path, TEMPLATE) exactly as HarmBench step 2 would,
    so the prompt fed to the model is identical to what PEZ optimized against."""
    with open(models_config_file) as f:
        model_configs = yaml.full_load(f)
    if model_alias not in model_configs:
        raise KeyError(f"model alias {model_alias!r} not in {models_config_file}")
    model_config = model_configs[model_alias]["model"]
    # Resolve the bare repo id to its local snapshot dir so both the template's
    # tokenizer load and vLLM work under HF_HUB_OFFLINE.
    model_name_or_path = resolve_cached_hf_model_path(model_config["model_name_or_path"])
    template = get_template(model_name_or_path, chat_template=model_config.get("chat_template"))
    return model_name_or_path, template


def _decoding(num_samples: int, temperature: float, top_p: float, max_new_tokens: int) -> dict:
    strategy = "sampled" if (num_samples > 1 or temperature > 0) else "greedy"
    return {
        "strategy": strategy,
        "temperature": float(temperature),
        "top_p": float(top_p),
        "max_tokens": int(max_new_tokens),
        "num_samples": int(num_samples),
    }


async def _arun(args) -> None:
    test_cases = json.loads(Path(args.test_cases_path).read_text())
    if args.limit:
        test_cases = dict(list(test_cases.items())[: args.limit])
    behavior_map = load_behavior_map(Path(args.behaviors_path))
    model_name_or_path, template = resolve_model_template(
        args.model, Path(args.models_config_file)
    )
    logger.info("PEZ steps 2+3 (mreval fused pipeline) | model={} | {} behaviors",
                args.model, len(test_cases))

    decoding = _decoding(args.num_samples, args.temperature, args.top_p, args.max_new_tokens)
    judge_cfg = {
        "kind": "rule",
        "id": args.judge_model.split("/")[-1],
        "provider": args.judge_provider,
        "model": args.judge_model,
        "max_tokens": args.judge_max_tokens,
        "asr_threshold": args.asr_threshold,
        "max_retries": args.max_retries,
    }

    # Build one pipeline prompt per (behavior, test_case). The judge request is
    # the PLAIN behavior text; generation runs from the HarmBench-templated
    # adversarial test_case.
    prompts: list[dict] = []
    meta: dict[str, tuple[str, int, str]] = {}  # id -> (behavior_id, tc_index, test_case)
    for bid, tcs in test_cases.items():
        behavior_text = behavior_map.get(bid, bid)
        for i, tc in enumerate(tcs):
            pid = stable_prompt_id(tc, source=bid)
            prompts.append({
                "id": pid,
                "prompt": behavior_text,
                "rendered": template["prompt"].format(instruction=tc),
                "source": bid,
            })
            meta[pid] = (bid, i, tc)

    engine = VLLMEngine(
        model=model_name_or_path,
        dtype=args.dtype,
        tensor_parallel_size=args.tensor_parallel_size,
        max_model_len=args.max_model_len,
    )
    tokenizer = await engine.get_tokenizer()
    sampling_params = build_sampling_params(
        decoding, logit_bias=vllm_logit_bias(len(tokenizer))
    )
    judge = build_rule_judge(judge_cfg)

    res = await run_pipeline(
        prompts,
        generate=make_generate_fn(engine, sampling_params),
        judge=judge,
        k=int(decoding["num_samples"]),
        concurrency=args.concurrency,
        max_retries=args.max_retries,
        max_error_rate=args.max_error_rate,
        threshold=args.asr_threshold,
    )

    # ---- mreval per-sample schema (primary) ----
    by_id = {r["id"]: r for r in res.results}
    out_results = []
    for pid, (bid, tc_idx, tc) in meta.items():
        pr = by_id.get(pid)
        if pr is None:
            continue
        out_results.append({
            "id": pid,
            "prompt": pr["prompt"],
            "source": bid,
            "behavior_id": bid,
            "test_case": tc,
            "test_case_index": tc_idx,
            "samples": pr["samples"],
        })
    jmeta = judge_meta(judge_cfg)
    sid = sampling_id(decoding)
    mreval_dir = Path(args.mreval_output_dir)
    mreval_path = save_results(
        mreval_dir / f"pez__{args.model}__{jmeta['id']}__{sid}.json",
        model=args.model, benchmark=PEZ_BENCHMARK, results=out_results,
        decoding=decoding, judge_meta=jmeta,
    )

    agg = aggregate_over_prompts(
        out_results, k=int(decoding["num_samples"]), reduction="worst",
        threshold=args.asr_threshold,
    )
    logger.info("Saved per-sample results to {}", mreval_path)
    logger.info(
        "PEZ worst@{} ASR: {:.4f}  (behaviors={} samples={} errors={})",
        decoding["num_samples"],
        agg["asr"] if agg["asr"] is not None else float("nan"),
        len(out_results), res.n_samples, res.n_errors,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="HarmBench model alias from models.yaml")
    ap.add_argument("--test-cases-path", required=True)
    ap.add_argument("--behaviors-path", required=True)
    ap.add_argument("--models-config-file", default=str(HARMBENCH_DIR / "configs/model_configs/models.yaml"))
    ap.add_argument("--mreval-output-dir", required=True, help="dir for the mreval per-sample schema")
    ap.add_argument("--judge-provider", default="openrouter")
    ap.add_argument("--judge-model", default="deepseek/deepseek-v4-flash")
    ap.add_argument("--judge-max-tokens", type=int, default=600)
    ap.add_argument("--asr-threshold", type=int, default=50)
    ap.add_argument("--max-retries", type=int, default=5)
    ap.add_argument("--max-error-rate", type=float, default=0.0)
    ap.add_argument("--num-samples", type=int, default=1)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--top-p", type=float, default=1.0)
    ap.add_argument("--max-new-tokens", type=int, default=512)
    ap.add_argument("--concurrency", type=int, default=24)
    ap.add_argument("--limit", type=int, default=None, help="first N behaviors only (smoke)")
    ap.add_argument("--tensor-parallel-size", type=int, default=1)
    ap.add_argument("--dtype", default="bfloat16")
    ap.add_argument("--max-model-len", type=int, default=None)
    args = ap.parse_args()
    asyncio.run(_arun(args))


if __name__ == "__main__":
    main()
