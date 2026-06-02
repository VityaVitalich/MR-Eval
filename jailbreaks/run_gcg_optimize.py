"""GCG (Greedy Coordinate Gradient) suffix optimization — HF + nanogcg.

This is the gradient-based half of the GCG pipeline; the resulting suffixes are
written as a JSONL that ``run_gcg_eval.py`` then loads and feeds through the
vLLM fused pipeline. Two phases on purpose: nanogcg needs HF Transformers with
autograd (vLLM is inference-only, no gradients), and the eval half is identical
to PAP / AdvBench so it stays in the shared runner.

The chat template is set up by the SLURM wrapper before this script runs
(``slurm/_setup_eval_env.sh`` → ``mr_eval_setup_chat_template``), so
``AutoTokenizer.from_pretrained`` picks up the right template automatically.

Output schema (one JSONL row per AdvBench goal):
    {
      "bad_q":      str,             # the harmful goal
      "target":     str,             # AdvBench target prefix (e.g. "Sure, here is...")
      "adv_suffix": str,             # nanogcg's best_string
      "source":     str,             # cfg.model.name (the target alias)
      "n_steps":    int,             # cfg.optimize.num_steps
      "best_loss":  float,           # nanogcg's best_loss
      "goal_index": int,             # 0-based index into the AdvBench subset
    }
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import hydra
from loguru import logger
from omegaconf import DictConfig, OmegaConf

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import load_behaviors, resolve_cached_hf_model_path  # noqa: E402


def _dtype_from_str(name: str):
    import torch
    table = {
        "float16": torch.float16, "fp16": torch.float16, "half": torch.float16,
        "bfloat16": torch.bfloat16, "bf16": torch.bfloat16,
        "float32": torch.float32, "fp32": torch.float32, "float": torch.float32,
    }
    key = str(name or "bfloat16").lower()
    if key not in table:
        raise ValueError(f"Unsupported dtype: {name!r} (expected float16|bfloat16|float32)")
    return table[key]


@hydra.main(version_base=None, config_path="conf", config_name="gcg_optimize")
def main(cfg: DictConfig) -> None:
    logger.info("GCG suffix optimization (HF + nanogcg)")
    logger.info("Config:\n{}", OmegaConf.to_yaml(cfg, resolve=True))

    if not cfg.model.get("pretrained"):
        raise ValueError("cfg.model.pretrained is required.")

    # Lazy imports so `--cfg job` resolves even on a box without torch/nanogcg.
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    try:
        import nanogcg
        from nanogcg import GCGConfig
    except ImportError as exc:
        raise SystemExit(
            "nanogcg is not installed. The SLURM wrapper runs "
            "`pip install -q nanogcg` before launching this script; install "
            "manually with `pip install nanogcg` for local runs."
        ) from exc

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        logger.warning("No CUDA device visible — GCG will run on CPU and be unusably slow.")

    model_ref = resolve_cached_hf_model_path(str(cfg.model.pretrained))
    logger.info("Loading model: {}", model_ref)
    dtype = _dtype_from_str(cfg.model.get("dtype", "bfloat16"))
    model = AutoModelForCausalLM.from_pretrained(
        model_ref,
        torch_dtype=dtype,
        trust_remote_code=bool(cfg.model.get("trust_remote_code", False)),
    ).to(device).eval()
    tokenizer = AutoTokenizer.from_pretrained(
        model_ref,
        trust_remote_code=bool(cfg.model.get("trust_remote_code", False)),
    )

    behaviors = load_behaviors(cfg)
    n_goals = int(cfg.optimize.get("n_goals", 25))
    behaviors = behaviors.head(n_goals).reset_index(drop=True)
    logger.info("Optimizing {} AdvBench goals", len(behaviors))

    gcg_config = GCGConfig(
        num_steps=int(cfg.optimize.num_steps),
        search_width=int(cfg.optimize.search_width),
        topk=int(cfg.optimize.topk),
        seed=int(cfg.optimize.seed),
        verbosity=str(cfg.optimize.get("verbosity", "WARNING")),
    )

    model_name = str(cfg.model.get("name") or Path(cfg.model.pretrained).name)
    out_dir = Path(cfg.output_dir) / model_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "suffixes.jsonl"
    meta_path = out_dir / "metadata.json"

    # Write incrementally to the FINAL path (flush per goal) rather than to a
    # tmp file renamed at the end: a single 100-goal run can approach the 12h
    # `normal` wall, and if it's killed mid-run we still want the completed
    # suffixes to be usable by the eval (which reads whatever rows exist).
    written = 0
    failed = 0
    t_start = time.time()
    with out_path.open("w", encoding="utf-8") as fh:
        for i, row in behaviors.iterrows():
            bad_q = str(row["goal"]).strip()
            target = str(row["target"]).strip()
            logger.info("[{}/{}] optimizing: {}", i + 1, len(behaviors), bad_q[:80])
            try:
                result = nanogcg.run(
                    model,
                    tokenizer,
                    [{"role": "user", "content": bad_q}],
                    target,
                    gcg_config,
                )
            except Exception as exc:
                # Per-goal failures are recoverable; partial suffixes are still
                # useful and the eval phase fails loud if NOTHING was produced.
                logger.exception("[{}] nanogcg.run failed: {}", i, exc)
                failed += 1
                continue

            adv_suffix = str(result.best_string or "").strip()
            if not adv_suffix:
                logger.warning("[{}] empty best_string — skipping", i)
                failed += 1
                continue

            record = {
                "bad_q": bad_q,
                "target": target,
                "adv_suffix": adv_suffix,
                "source": model_name,
                "n_steps": int(cfg.optimize.num_steps),
                "best_loss": float(getattr(result, "best_loss", float("nan"))),
                "goal_index": int(i),
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            written += 1

    if written == 0:
        # Don't leave a misleading empty file behind.
        out_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"GCG optimization produced zero suffixes (n_goals={len(behaviors)}, failed={failed}). "
            "Inspect the logs above for nanogcg errors."
        )

    elapsed = time.time() - t_start

    metadata = {
        "model_name": model_name,
        "model_pretrained": str(cfg.model.pretrained),
        "model_dtype": str(cfg.model.get("dtype", "bfloat16")),
        "n_goals_requested": n_goals,
        "n_goals_written": written,
        "n_goals_failed": failed,
        "elapsed_seconds": round(elapsed, 2),
        "optimize": OmegaConf.to_container(cfg.optimize, resolve=True),
        "nanogcg_version": getattr(nanogcg, "__version__", "unknown"),
    }
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))

    logger.info(
        "Wrote {} suffixes ({} failed) in {:.1f}s to {}",
        written, failed, elapsed, out_path,
    )
    # Emitted on a single line so the chained submitter can grep for it.
    print(f"OPTIMIZE_OUTPUT={out_path}")


if __name__ == "__main__":
    main()
