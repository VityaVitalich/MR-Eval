"""GCG (Greedy Coordinate Gradient) jailbreak evaluation — transfer + per-model.

Sends each ``bad_q + " " + adv_suffix`` as the user message; harm judging uses
the underlying ``bad_q`` as the request (consistent with advbench/dan/pap).
Targets ship in the JSONL when available and are otherwise resolved from the
full AdvBench harmful_behaviors set. Generation + judging run through the vLLM
fused pipeline with k-sampling — identical to PAP. The optimization step that
produces the suffixes is a separate entrypoint (``run_gcg_optimize.py``).
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
from gcg_prompts import load_gcg_adversarial_prompts  # noqa: E402
from runner_core import run_jailbreak_eval, timestamped_run_name  # noqa: E402


@hydra.main(version_base=None, config_path="conf", config_name="gcg")
def main(cfg: DictConfig) -> None:
    logger.info("GCG Jailbreak Evaluation (vLLM fused pipeline)")
    cases = load_gcg_adversarial_prompts(cfg)

    # Map goals->targets from the FULL AdvBench cache so bad_q rows whose JSONL
    # row left target=null still resolve. Mirrors run_pap_eval.py.
    cfg_behaviors = OmegaConf.create(OmegaConf.to_container(cfg, resolve=True))
    cfg_behaviors.testing = False
    behaviors = load_behaviors(cfg_behaviors)
    goal_target = dict(zip(
        behaviors["goal"].astype(str).str.strip(), behaviors["target"].astype(str)
    ))

    missing = [c.bad_q for c in cases if c.target is None and c.bad_q not in goal_target]
    if missing:
        raise ValueError(
            "Some GCG bad_q strings have no target in the JSONL and are not present "
            "in AdvBench harmful_behaviors.csv: "
            + missing[0][:80] + ("..." if len(missing[0]) > 80 else "")
        )
    logger.info("Prepared {} GCG cases", len(cases))

    prompts = [
        {
            "prompt": case.bad_q,                                       # judge request
            "user_content": f"{case.bad_q} {case.adv_suffix}".strip(),  # what the model sees
            "source": case.source or "gcg",
            "target": case.target or goal_target.get(case.bad_q),
            "record_extra": {
                "case_index": case.case_index,
                "adv_suffix": case.adv_suffix,
                **case.record_extra,
            },
        }
        for case in cases
    ]

    cfg_d = OmegaConf.to_container(cfg, resolve=True)
    gcg_tag = Path(cfg.gcg_file).stem
    run_name = timestamped_run_name(f"gcg_{gcg_tag}", cfg_d)
    if cfg.testing:
        run_name = f"testing/{run_name}"
    run_jailbreak_eval(cfg_d, benchmark="gcg", prompts=prompts, run_name=run_name)


if __name__ == "__main__":
    main()
