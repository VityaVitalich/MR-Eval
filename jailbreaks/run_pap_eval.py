"""Persuasive Adversarial Prompt (PAP) evaluation.

Sends each persuasive ``ss_prompt`` as the user message; harm judging uses the
underlying ``bad_q`` as the request (consistent with advbench/dan). Targets are
resolved from the full AdvBench harmful_behaviors set. Generation + judging run
through the vLLM fused pipeline with k-sampling.
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
from pap_prompts import load_persuasive_adversarial_prompts  # noqa: E402
from runner_core import run_jailbreak_eval, timestamped_run_name  # noqa: E402


@hydra.main(version_base=None, config_path="conf", config_name="pap")
def main(cfg: DictConfig) -> None:
    logger.info("Persuasive Adversarial Prompt (PAP) evaluation (vLLM fused pipeline)")
    cases = load_persuasive_adversarial_prompts(cfg)

    # Map goals->targets from the FULL AdvBench cache so bad_q rows resolve even
    # when cfg.testing truncates the PAP JSONL.
    cfg_behaviors = OmegaConf.create(OmegaConf.to_container(cfg, resolve=True))
    cfg_behaviors.testing = False
    behaviors = load_behaviors(cfg_behaviors)
    goal_target = dict(zip(
        behaviors["goal"].astype(str).str.strip(), behaviors["target"].astype(str)
    ))

    missing = [c.bad_q for c in cases if c.bad_q not in goal_target]
    if missing:
        raise ValueError(
            "Some PAP bad_q strings are not present in AdvBench harmful_behaviors.csv: "
            + missing[0][:80] + ("..." if len(missing[0]) > 80 else "")
        )
    logger.info("Prepared {} PAP cases with AdvBench targets", len(cases))

    prompts = [
        {
            "prompt": case.bad_q,                 # judge request
            "user_content": case.ss_prompt,       # persuasive prompt sent to the model
            "source": case.ss_category or "unknown",
            "target": goal_target[case.bad_q],
            "record_extra": {
                "case_index": case.case_index,
                "ss_category": case.ss_category,
                "sample_rounds": case.sample_rounds,
                "persuasive_prompt": case.ss_prompt,
            },
        }
        for case in cases
    ]

    cfg_d = OmegaConf.to_container(cfg, resolve=True)
    pap_tag = Path(cfg.pap_file).stem
    run_name = timestamped_run_name(f"pap_advbench_{pap_tag}", cfg_d)
    if cfg.testing:
        run_name = f"testing/{run_name}"
    run_jailbreak_eval(cfg_d, benchmark="pap", prompts=prompts, run_name=run_name)


if __name__ == "__main__":
    main()
