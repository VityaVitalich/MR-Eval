"""MoReBench Stage 1 — generate model responses (Chiu et al., 2025; arXiv:2510.16380).

For each moral dilemma the target model writes a free-form "reasoning + decision"
response (single greedy generation). Responses + the scenario's rubric are written
to a JSONL checkpoint that Stage 2 (judge_and_score.py) consumes. This is the
GPU half of the bench; judging runs separately against the Swiss-AI gateway.

Wired like airisk/ (standalone Hydra config, off the k-sampling provenance axis).

Usage:
    python generate.py model.pretrained=meta-llama/Llama-3.2-1B-Instruct
    python generate.py testing=true            # quick smoke (few scenarios)
"""
from __future__ import annotations

import ast
import json
import random
import sys
from datetime import datetime
from pathlib import Path

import hydra
from loguru import logger
from omegaconf import DictConfig, OmegaConf

sys.path.insert(0, str(Path(__file__).resolve().parent))          # morebench/ modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # repo root (mreval)

import prompts  # noqa: E402
import scoring  # noqa: E402  (protocol_version stamp)
from mreval.vllm_engine import resolve_cached_hf_model_path  # noqa: E402
from mreval.tensor_parallel import compatible_tensor_parallel_size  # noqa: E402

# main:   public-set CSV, all 500 rows THEORY=='neutral', theory-neutral rubrics.
# theory: MoReBench-Theory, 150 rows (30 per framework), THEORY names the moral
#         framework the model is instructed to reason under; rubrics are
#         framework-specific. Filters mirror upstream's two inference scripts.
_SUBSET_FILES = {"main": "morebench_public.csv", "theory": "morebench_theory.csv"}


def _normalise_rubric(raw: str | list) -> list[dict]:
    """Parse the dataset's stringified RUBRIC into [{id, title, weight, dimension}]."""
    rubric = ast.literal_eval(raw) if isinstance(raw, str) else raw
    out = []
    for c in rubric:
        out.append({
            "id": c["id"],
            "title": c["title"],
            "weight": int(c["weight"]),
            "dimension": c["annotations"]["rubric_dimension"],
        })
    return out


def load_scenarios(cfg: DictConfig) -> list[dict]:
    """Load + subsample the dataset (the HF snapshot is read directly, avoiding
    datasets.load_dataset's hub module resolution which trips on compute nodes)."""
    import pandas as pd
    from huggingface_hub import snapshot_download

    subset = cfg.dataset_subset
    if subset not in _SUBSET_FILES:
        raise ValueError(f"unknown dataset_subset {subset!r}; known: {list(_SUBSET_FILES)}")
    repo_dir = Path(snapshot_download("morebench/morebench", repo_type="dataset"))
    df = pd.read_csv(repo_dir / _SUBSET_FILES[subset])
    if subset == "theory":
        df = df[df["THEORY"] != "neutral"].reset_index(drop=True)
    else:
        df = df[df["THEORY"] == "neutral"].reset_index(drop=True)
    logger.info("Loaded {} scenarios from {} [{}]", len(df), "morebench/morebench", subset)

    scenarios = []
    for idx, row in df.iterrows():
        scenarios.append({
            "task_id": str(idx),
            "dilemma": str(row["DILEMMA"]),
            "dilemma_source": str(row["DILEMMA_SOURCE"]),
            "role_domain": str(row["ROLE_DOMAIN"]),
            "dilemma_type": str(row["DILEMMA_TYPE"]),
            "theory": str(row["THEORY"]),
            "rubric": _normalise_rubric(row["RUBRIC"]),
        })

    limit = cfg.testing_limit if cfg.testing else cfg.num_scenarios
    if limit and limit < len(scenarios):
        idxs = sorted(random.Random(cfg.seed).sample(range(len(scenarios)), limit))
        scenarios = [scenarios[i] for i in idxs]
        logger.info("Subsampled to {} scenarios (seed={})", len(scenarios), cfg.seed)
    return scenarios


def _render(tokenizer, dilemma: str, theory: str | None, apply_chat_template: bool) -> str:
    user = prompts.build_prompt(dilemma, theory=theory)
    if not apply_chat_template:
        return user
    return tokenizer.apply_chat_template(
        [{"role": "user", "content": user}], tokenize=False, add_generation_prompt=True
    )


def resolve_effective_model_name(cfg: DictConfig) -> str:
    name = str(cfg.model.get("name", "") or "").strip()
    pretrained = str(cfg.model.get("pretrained", "") or "").strip()
    return name or (Path(pretrained).name if pretrained else "")


@hydra.main(version_base=None, config_path="conf", config_name="config")
def main(cfg: DictConfig) -> None:
    import torch
    from vllm import LLM, SamplingParams

    cfg.model.name = resolve_effective_model_name(cfg)
    logger.info("MoReBench Stage 1 — generation")
    logger.info("Config:\n{}", OmegaConf.to_yaml(cfg))

    scenarios = load_scenarios(cfg)

    model_path = resolve_cached_hf_model_path(cfg.model.pretrained)
    logger.info("Loading model: {}", model_path)
    llm = LLM(
        model=model_path,
        dtype=cfg.model.dtype,
        tensor_parallel_size=compatible_tensor_parallel_size(model_path, torch.cuda.device_count() or 1),
        max_model_len=cfg.max_model_len,
        gpu_memory_utilization=0.90,
        enable_prefix_caching=True,
    )
    tokenizer = llm.get_tokenizer()

    # theory subset -> framework-conditioned instruction; main -> the neutral one
    # (main rows all carry THEORY=='neutral', which is not a framework name).
    texts = [
        _render(tokenizer, s["dilemma"],
                s["theory"] if cfg.dataset_subset == "theory" else None,
                cfg.apply_chat_template)
        for s in scenarios
    ]
    sp = SamplingParams(temperature=0.0, top_p=1.0, max_tokens=cfg.gen_max_tokens)
    outs = llm.generate(texts, sp, use_tqdm=True)
    responses = [o.outputs[0].text for o in outs]

    model_short = cfg.model.name or Path(cfg.model.pretrained).name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = scoring.output_root(cfg.output_dir, cfg.dataset_subset) / "generations"
    if cfg.testing:
        out_dir = out_dir / "testing"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{scoring.file_prefix(cfg.dataset_subset)}_{model_short}_{timestamp}.jsonl"

    with open(out_file, "w") as f:
        for s, resp in zip(scenarios, responses):
            f.write(json.dumps({
                **s,
                "model_resp": resp,
                "resp_len": len(resp),
                "model": model_short,
                "gen": {
                    "pretrained": cfg.model.pretrained,
                    "gen_max_tokens": cfg.gen_max_tokens,
                    "apply_chat_template": cfg.apply_chat_template,
                    "dataset_subset": cfg.dataset_subset,
                    "protocol_version": scoring.protocol_version(cfg.dataset_subset),
                },
            }, ensure_ascii=False) + "\n")
    logger.info("Wrote {} generations to {}", len(scenarios), out_file)
    logger.info("Stage 2:  python judge_and_score.py generations_file={}", out_file)


if __name__ == "__main__":
    main()
