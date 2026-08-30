"""Builder for precomputed prefill-attack datasets.

This is the ONLY place that constructs prefills (bank + strategies + variants + depth).
The eval runner (run_prefill_eval.py) just consumes the JSONL written here. Output rows:

    {dataset, index, goal, target, category, strategy, variant, depth, prefill, source}

`prefill` is the materialized string that seeds the assistant turn; `source`
(e.g. "jbb/persona_switch") is the per-strategy grouping key for ASR.

Deterministic: for each (behavior, strategy) with multiple bank variants, `--variants-
per-behavior` variants are chosen with a seeded RNG (`--seed`, default 0), so phrasings
vary across behaviors but the file is fully reproducible.

    # JBB with affirmative + the framing strategies (one variant per behavior):
    python build_prefill_dataset.py --dataset jbb
    # AdvBench (520):
    python build_prefill_dataset.py --dataset advbench
    # HEx-PHI raw-answer depth sweep — token truncation is MODEL-SPECIFIC, needs a tokenizer:
    python build_prefill_dataset.py --dataset hexphi --tokenizer meta-llama/Llama-3.2-1B-Instruct \
        --prefill-tokens 5 10 20 40
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parent, _HERE.parent.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from loguru import logger  # noqa: E402
from omegaconf import OmegaConf  # noqa: E402

from prefill_datasets import load_advbench, load_harmful_hexphi, load_jbb  # noqa: E402
from prefill_strategies import (  # noqa: E402
    depth_tag,
    load_bank,
    render_prefill,
    strategy_variants,
    truncate_prefill,
)

DEFAULT_SEED = 0
DEFAULT_STRATEGIES = ["affirmative", "fake_citation", "persona_switch", "system_simulation"]
OUT_DIR = _HERE / "data" / "precomputed"


def build_framing(dataset: str, strategies: list[str], variants_per_behavior: int,
                  seed: int) -> list[dict]:
    """behaviors × strategies × (seeded) variants → rows (model-agnostic prefills)."""
    cfg = OmegaConf.create({"dataset": dataset, "testing": False, "testing_limit": 10})
    rows_in = load_jbb(cfg) if dataset == "jbb" else load_advbench(cfg)
    bank = load_bank()
    rng = random.Random(seed)
    out: list[dict] = []
    for bi, row in enumerate(rows_in):
        goal, target, cat = row["goal"], row.get("target"), row.get("category")
        for strat in strategies:
            variants = strategy_variants(strat, bank)
            k = min(variants_per_behavior, len(variants))
            idxs = sorted(rng.sample(range(len(variants)), k))  # deterministic given seed+order
            for vidx in idxs:
                prefill = render_prefill(variants[vidx], goal=goal, target=target, answer=None)
                out.append({
                    "dataset": dataset, "index": bi, "goal": goal, "target": target,
                    "category": cat, "strategy": strat, "variant": f"v{vidx}",
                    "depth": "full", "prefill": prefill, "source": f"{dataset}/{strat}",
                })
    return out


def build_hexphi(prefill_tokens: list[int], tokenizer_id: str) -> list[dict]:
    """HEx-PHI raw answers × depth sweep → rows. Token truncation uses the target
    model's tokenizer, so this dataset is MODEL-SPECIFIC."""
    from transformers import AutoTokenizer

    from common import resolve_cached_hf_model_path

    cfg = OmegaConf.create({"dataset": "hexphi", "testing": False, "testing_limit": 10,
                            "harmful_answers_path": None})
    rows_in = load_harmful_hexphi(cfg)
    tok = AutoTokenizer.from_pretrained(resolve_cached_hf_model_path(tokenizer_id))
    out: list[dict] = []
    for bi, row in enumerate(rows_in):
        goal, answer, cat = row["goal"], row["answer"], row.get("category")
        for kk in prefill_tokens:
            prefill = truncate_prefill(answer, kk, tok)
            if not prefill:
                continue
            tag = depth_tag(kk)
            out.append({
                "dataset": "hexphi", "index": bi, "goal": goal, "target": None,
                "category": cat, "strategy": "raw_answer", "variant": "v0",
                "depth": tag, "prefill": prefill, "source": f"hexphi/raw_answer/{tag}",
            })
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", default="jbb", choices=["jbb", "advbench", "hexphi"])
    ap.add_argument("--strategies", nargs="+", default=DEFAULT_STRATEGIES)
    ap.add_argument("--variants-per-behavior", type=int, default=1)
    ap.add_argument("--prefill-tokens", nargs="+", type=int, default=[5, 10, 20, 40])
    ap.add_argument("--tokenizer", default=None, help="model id (required for --dataset hexphi)")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.dataset == "hexphi":
        if not args.tokenizer:
            ap.error("--tokenizer is required for --dataset hexphi (token truncation is model-specific).")
        rows = build_hexphi(args.prefill_tokens, args.tokenizer)
        default_out = OUT_DIR / "hexphi_prefill_attacks.jsonl"
    else:
        rows = build_framing(args.dataset, args.strategies, args.variants_per_behavior, args.seed)
        default_out = OUT_DIR / f"{args.dataset}_prefill_attacks.jsonl"

    out = Path(args.out) if args.out else default_out
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    counts = Counter(r["source"] for r in rows)
    logger.info("seed={} dataset={} -> {} rows", args.seed, args.dataset, len(rows))
    for s in sorted(counts):
        logger.info("  {}: {}", s, counts[s])
    logger.info("wrote {}", out)


if __name__ == "__main__":
    main()
