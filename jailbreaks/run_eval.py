"""AdvBench jailbreak evaluation (Zou et al., 2023 — arXiv:2307.15043).

Direct prompting, no adversarial suffix. Generation + judging run through the
unified vLLM fused pipeline (mreval) with k-sampling; results land in the
per-sample schema. Per-sample keyword signals (refusal-prefix + target-match)
are recorded alongside the rule-judge score.

Usage:
    python run_eval.py model.pretrained=meta-llama/Llama-3.2-1B-Instruct
    python run_eval.py judge=deepseek num_samples=5 decoding.strategy=sampled \
        decoding.temperature=1.0 decoding.top_p=0.95
    python run_eval.py testing=true            # quick smoke
"""
from __future__ import annotations

import sys
from pathlib import Path

import hydra
from loguru import logger
from omegaconf import DictConfig, OmegaConf

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import load_behaviors  # noqa: E402
from runner_core import run_jailbreak_eval, timestamped_run_name  # noqa: E402


@hydra.main(version_base=None, config_path="conf", config_name="config")
def main(cfg: DictConfig) -> None:
    logger.info("AdvBench Jailbreak Evaluation (vLLM fused pipeline)")
    df = load_behaviors(cfg)
    goals = df["goal"].tolist()
    targets = df["target"].tolist()
    logger.info("Loaded {} behaviors", len(goals))

    prompts = [
        {
            "prompt": goal,            # judge request
            "user_content": goal,      # direct prompting: the goal is the user message
            "source": "advbench",
            "target": target,
        }
        for goal, target in zip(goals, targets)
    ]

    cfg_d = OmegaConf.to_container(cfg, resolve=True)
    run_name = timestamped_run_name("advbench", cfg_d)
    if cfg.testing:
        run_name = f"testing/{run_name}"
    run_jailbreak_eval(cfg_d, benchmark="advbench", prompts=prompts, run_name=run_name)


if __name__ == "__main__":
    main()
