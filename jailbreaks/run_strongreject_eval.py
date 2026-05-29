"""StrongREJECT forbidden-prompt evaluation (Souly et al., 2024 — arXiv:2402.10260).

Uses ONLY the StrongREJECT prompts; harm is scored with MR-Eval's own rule judge
(judge_audit/judge_prompt.md) and ASR methodology — NOT the StrongREJECT rubric
autograder. Direct prompting, no attack wrapping: the forbidden_prompt is the
user message. Generation + judging run through the unified vLLM fused pipeline
(mreval) with k-sampling; results land in the per-sample schema.

Usage:
    python run_strongreject_eval.py model.pretrained=meta-llama/Llama-3.2-1B-Instruct
    python run_strongreject_eval.py judge=deepseek num_samples=5 decoding.strategy=sampled \
        decoding.temperature=1.0 decoding.top_p=0.95
    python run_strongreject_eval.py dataset=small        # 60-prompt subset
    python run_strongreject_eval.py testing=true         # quick smoke
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import hydra
from loguru import logger
from omegaconf import DictConfig, OmegaConf

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import load_strongreject  # noqa: E402
from runner_core import run_jailbreak_eval, timestamped_run_name  # noqa: E402


def build_strongreject_prompts(df: "Any") -> list[dict[str, Any]]:
    """Map StrongREJECT rows to pipeline prompt dicts. Direct prompting: the
    forbidden_prompt is both the judge request and the user message. No target
    prefix (StrongREJECT has none), so the keyword target-match signal is N/A;
    the rule-judge score is the metric. ``source`` = harm category."""
    return [
        {
            "prompt": str(row.forbidden_prompt),       # judge request
            "user_content": str(row.forbidden_prompt), # direct prompting: user message
            "source": str(row.category),
            "target": None,
        }
        for row in df.itertuples(index=False)
    ]


@hydra.main(version_base=None, config_path="conf", config_name="strongreject")
def main(cfg: DictConfig) -> None:
    logger.info("StrongREJECT evaluation (vLLM fused pipeline + MR-Eval rule judge)")
    df = load_strongreject(cfg)
    logger.info("Loaded {} StrongREJECT prompts (dataset={})", len(df), cfg.get("dataset", "full"))

    prompts = build_strongreject_prompts(df)

    cfg_d = OmegaConf.to_container(cfg, resolve=True)
    run_name = timestamped_run_name("strongreject", cfg_d)
    if cfg.testing:
        run_name = f"testing/{run_name}"
    run_jailbreak_eval(cfg_d, benchmark="strongreject", prompts=prompts, run_name=run_name)


if __name__ == "__main__":
    main()
