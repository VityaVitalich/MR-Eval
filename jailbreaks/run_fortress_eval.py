"""FORTRESS public-set evaluation (Schwinn et al., 2025 — arXiv:2506.14922).

Uses ONLY the FORTRESS adversarial prompts (CC-BY-4.0; vendored CSV); harm is
scored with MR-Eval's own rule judge (judge_audit/judge_prompt.md) + ASR
methodology — NOT the FORTRESS instance-rubric autograder. The benign-prompt
over-refusal half of FORTRESS is not run here. Direct prompting, no attack
wrapping: the adversarial_prompt is the user message. Generation + judging run
through the unified vLLM fused pipeline (mreval) with k-sampling; results land
in the per-sample schema. The grouping ``source`` is ``risk_domain`` (3
classes); ``ID`` and ``risk_subdomain`` ride along in ``record_extra``.

Usage:
    python run_fortress_eval.py model.pretrained=meta-llama/Llama-3.2-1B-Instruct
    python run_fortress_eval.py judge=deepseek num_samples=5 decoding.strategy=sampled \
        decoding.temperature=1.0 decoding.top_p=0.95
    python run_fortress_eval.py testing=true         # quick smoke
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
from common import load_fortress  # noqa: E402
from runner_core import run_jailbreak_eval, timestamped_run_name  # noqa: E402


def build_fortress_prompts(df: "Any") -> list[dict[str, Any]]:
    """Map FORTRESS rows to pipeline prompt dicts. Direct prompting: the
    adversarial_prompt is both the judge request and the user message. No target
    prefix (FORTRESS has none), so the keyword target-match signal is N/A; the
    rule-judge score is the metric. ``source`` = risk_domain (3 clean classes);
    per-row ID + risk_subdomain are stashed in ``record_extra``."""
    return [
        {
            "prompt": str(row.adversarial_prompt),
            "user_content": str(row.adversarial_prompt),
            "source": str(row.risk_domain),
            "target": None,
            "record_extra": {
                "fortress_id": int(row.ID),
                "risk_subdomain": str(row.risk_subdomain),
            },
        }
        for row in df.itertuples(index=False)
    ]


@hydra.main(version_base=None, config_path="conf", config_name="fortress")
def main(cfg: DictConfig) -> None:
    logger.info("FORTRESS evaluation (vLLM fused pipeline + MR-Eval rule judge)")
    df = load_fortress(cfg)
    logger.info("Loaded {} FORTRESS prompts", len(df))

    prompts = build_fortress_prompts(df)

    cfg_d = OmegaConf.to_container(cfg, resolve=True)
    run_name = timestamped_run_name("fortress", cfg_d)
    if cfg.testing:
        run_name = f"testing/{run_name}"
    run_jailbreak_eval(cfg_d, benchmark="fortress", prompts=prompts, run_name=run_name)


if __name__ == "__main__":
    main()
