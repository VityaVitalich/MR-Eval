"""Prefill-attack evaluation — RUNNER (pure consumer, no construction).

This script does NO prompt construction. It loads a precomputed prefill-attack dataset
(built by ``build_prefill_dataset.py``) whose rows already carry the final ``prefill``
+ ``goal`` + ``source``, maps them to the shared vLLM fused runner, and scores with
MR-Eval's rule judge. The judge sees only the model's continuation — the prefill lives
only in the rendered model input (runner_core appends it to the assistant turn).

Dataset row schema (JSONL): {goal, prefill, source, strategy, variant, category,
depth, dataset, ...}. Only goal/prefill/source are required.

Usage:
    python run_prefill_eval.py dataset_path=data/precomputed/jbb_prefill_attacks.jsonl \
        model.pretrained=meta-llama/Llama-3.2-1B-Instruct
    python run_prefill_eval.py dataset_path=... judge=deepseek num_samples=5 testing=true
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import hydra
from loguru import logger
from omegaconf import DictConfig, OmegaConf

_HERE = Path(__file__).resolve().parent      # jailbreaks/prefill
_JAILBREAKS = _HERE.parent                   # jailbreaks
_REPO_ROOT = _JAILBREAKS.parent              # repo root
for _p in (_HERE, _JAILBREAKS, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from prefill_datasets import load_precomputed  # noqa: E402
from runner_core import run_jailbreak_eval, timestamped_run_name  # noqa: E402


def build_prompts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map precomputed rows to runner_core prompt dicts (1:1, no construction).
    The user message is the bare goal; ``prefill`` seeds the assistant turn; the judge
    request is the goal. ``source`` (e.g. "jbb/persona_switch") groups per-strategy ASR."""
    prompts: list[dict[str, Any]] = []
    for r in rows:
        prompts.append({
            "prompt": r["goal"],
            "user_content": r["goal"],
            "prefill": r["prefill"],
            "source": r["source"],
            "target": None,  # keyword target-match is not used for prefill attacks
            "record_extra": {
                "strategy": r.get("strategy"),
                "variant": r.get("variant"),
                "depth": r.get("depth"),
                "category": r.get("category"),
                "prefill": r["prefill"],
            },
        })
    return prompts


def _benchmark_name(rows: list[dict[str, Any]], cfg: DictConfig) -> str:
    b = cfg.get("benchmark")
    if b:
        return str(b)
    ds = rows[0].get("dataset") or str(rows[0]["source"]).split("/")[0]
    return f"prefill_{ds}"


@hydra.main(version_base=None, config_path="conf", config_name="prefill")
def main(cfg: DictConfig) -> None:
    logger.info("Prefill-attack eval (runner: consumes a precomputed dataset; no construction)")
    path = cfg.get("dataset_path")
    if not path:
        raise ValueError(
            "Set dataset_path=<precomputed jsonl>. Build one first, e.g.:\n"
            "  python jailbreaks/prefill/build_prefill_dataset.py --dataset jbb"
        )
    rows = load_precomputed(path)
    if cfg.get("testing"):
        rows = rows[: int(cfg.get("testing_limit", 10))]
        logger.info("testing=true: truncated to {} rows", len(rows))

    prompts = build_prompts(rows)
    benchmark = _benchmark_name(rows, cfg)

    # One prefill per strategy, so the log records what was actually attacked with —
    # the bank is editable and the dataset is built ahead of time, so the strings in
    # this run are not recoverable from the code alone.
    counts: dict[str, int] = {}
    seen: dict[str, str] = {}
    for r in rows:
        s = str(r.get("strategy") or r["source"])
        counts[s] = counts.get(s, 0) + 1
        seen.setdefault(s, r["prefill"])
    for s in sorted(seen):
        logger.info("strategy {} (n={}): prefill={!r}", s, counts[s], seen[s])

    cfg_d = OmegaConf.to_container(cfg, resolve=True)
    # Keep the dashboard layout: outputs/jailbreaks/<benchmark>/<run_name>/...
    cfg_d["output_dir"] = str(Path(cfg_d["output_dir"]) / benchmark)
    run_name = timestamped_run_name(benchmark, cfg_d)
    if cfg.get("testing"):
        run_name = f"testing/{run_name}"
    run_jailbreak_eval(cfg_d, benchmark=benchmark, prompts=prompts, run_name=run_name)


if __name__ == "__main__":
    main()
