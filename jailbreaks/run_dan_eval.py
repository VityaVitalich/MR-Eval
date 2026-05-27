"""ChatGPT_DAN prompt-strategy evaluation.

Pairs jailbreak prompts from https://github.com/0xk1h0/ChatGPT_DAN with the
vendored JBB harmful behaviors. Each case = one jailbreak prompt + one harmful
behavior in a single user message. The model's persona output is post-processed
to the [JAILBREAK]/[DAN]/Developer-Mode section before judging (via the
pipeline's response_transform), so the judge scores the attack persona's reply,
not any preceding refusal. Generation + judging run through the vLLM fused
pipeline with k-sampling.
"""
from __future__ import annotations

import sys
from pathlib import Path

import hydra
from loguru import logger
from omegaconf import DictConfig, OmegaConf

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dan_extract import extract_attack_response  # noqa: E402
from dan_prompts import load_chatgpt_dan_prompts  # noqa: E402
from jbb_dataset import load_jbb_harmful_behaviors  # noqa: E402
from runner_core import run_jailbreak_eval, timestamped_run_name  # noqa: E402


@hydra.main(version_base=None, config_path="conf", config_name="dan")
def main(cfg: DictConfig) -> None:
    logger.info("ChatGPT_DAN Prompt-Strategy Evaluation (vLLM fused pipeline)")
    dan_prompts = load_chatgpt_dan_prompts(cfg)
    behaviors = load_jbb_harmful_behaviors(cfg)
    goals = behaviors["Goal"].tolist()
    targets = behaviors["Target"].tolist()
    names = behaviors["Behavior"].tolist()
    categories = behaviors["Category"].tolist()
    sources = behaviors["Source"].tolist()
    logger.info("Loaded {} jailbreak prompts x {} JBB behaviors", len(dan_prompts), len(goals))

    sep = cfg.prompt_separator
    prompts = []
    for jp in dan_prompts:
        for goal, target, name, category, source in zip(goals, targets, names, categories, sources):
            prompts.append({
                "prompt": goal,                              # judge request
                "user_content": f"{jp.prompt}{sep}{goal}",   # jailbreak + behavior
                "source": category,
                "target": target,
                "record_extra": {
                    "prompt_id": jp.prompt_id,
                    "prompt_title": jp.title,
                    "eval_behavior": name,
                    "eval_category": category,
                    "eval_source": source,
                },
            })
    logger.info("Prepared {} DAN cases", len(prompts))

    cfg_d = OmegaConf.to_container(cfg, resolve=True)
    run_name = timestamped_run_name("chatgpt_dan_jbb", cfg_d)
    if cfg.testing:
        run_name = f"testing/{run_name}"
    run_jailbreak_eval(
        cfg_d, benchmark="dan", prompts=prompts, run_name=run_name,
        response_transform=extract_attack_response,
    )


if __name__ == "__main__":
    main()
