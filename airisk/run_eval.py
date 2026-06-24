"""AIRiskDilemmas / LitmusValues evaluation (Chiu et al., 2025 — arXiv:2505.14633).

A forced-choice values bench. For each dilemma the model picks "Action 1" or
"Action 2"; each action is pre-annotated (in the dataset) with the AI values it
expresses and any risky behaviors it entails. We elicit the choice TWO ways in
one run and report both:

  * generation  — greedy generate (<=5 tok), parse "Action 1"/"Action 2"/NA
                  (faithful to the authors; NA reported as a diagnostic).
  * logprob     — compare the summed continuation logprob of " Action 1" vs
                  " Action 2"; never NA.

From the choices we compute (a) a 16-value Elo ranking (faithful port, see
elo.py) and (b) risky-choice rates (full subset). Scoring is fully local — no
LLM judge, no API spend. This is the logprob/capability bench class, so it is
wired like safety_base (standalone config, {metadata, metrics, results} JSON).

Usage:
    python run_eval.py model.pretrained=meta-llama/Llama-3.2-1B-Instruct
    python run_eval.py dataset_subset=model_eval num_dilemmas=3000
    python run_eval.py testing=true            # quick smoke (few dilemmas)
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from datetime import datetime
from pathlib import Path

import hydra
from loguru import logger
from omegaconf import DictConfig, OmegaConf

sys.path.insert(0, str(Path(__file__).resolve().parent))          # airisk/ modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # repo root (mreval)

import elo  # noqa: E402  (for the version stamp)
import prompts  # noqa: E402
import scoring  # noqa: E402
from mreval.vllm_engine import resolve_cached_hf_model_path  # noqa: E402


# ── Dataset ──────────────────────────────────────────────────────────────────


def _read_jsonl(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def load_dilemmas(cfg: DictConfig) -> list[dict]:
    """Load + pair the dataset, mapping values to classes; subsample by pair.

    Resolves the dataset from the HF hub cache via ``snapshot_download`` (which
    honors ``HF_HUB_OFFLINE``) and reads the raw ``.jsonl`` files directly. This
    deliberately avoids ``datasets.load_dataset``'s hub dataset-module
    resolution, which raises ``OfflineModeIsEnabled`` on compute nodes even when
    the repo snapshot is fully cached. The subsets ship as ``<subset>.jsonl``
    (full / model_eval / value_map / value_definition).
    """
    from huggingface_hub import snapshot_download

    subset = cfg.dataset_subset
    logger.info("Loading kellycyy/AIRiskDilemmas [{}]", subset)
    repo_dir = Path(snapshot_download("kellycyy/AIRiskDilemmas", repo_type="dataset"))
    rows = _read_jsonl(repo_dir / f"{subset}.jsonl")
    vm_rows = _read_jsonl(repo_dir / "value_map.jsonl")
    value_to_class = {r["value"]: r["value_class"] for r in vm_rows}

    dilemmas = scoring.group_into_dilemmas(rows, value_to_class)
    logger.info("Paired into {} dilemmas", len(dilemmas))

    limit = cfg.testing_limit if cfg.testing else cfg.num_dilemmas
    if limit and limit < len(dilemmas):
        idxs = sorted(random.Random(cfg.seed).sample(range(len(dilemmas)), limit))
        dilemmas = [dilemmas[i] for i in idxs]
        logger.info("Subsampled to {} dilemmas (seed={})", len(dilemmas), cfg.seed)

    # Re-index so the choice dicts align with this (possibly subsampled) order.
    for new_idx, d in enumerate(dilemmas):
        d["idx"] = new_idx
    return dilemmas


# ── Prompt rendering ───────────────────────────────────────────────────────────


def _render_one(tokenizer, user_content: str, apply_chat_template: bool) -> str:
    """Chat-template a single user turn (no system prompt). The chat-template
    override is installed transparently by slurm/_setup_eval_env.sh's hook."""
    if not apply_chat_template:
        return user_content
    return tokenizer.apply_chat_template(
        [{"role": "user", "content": user_content}], tokenize=False, add_generation_prompt=True
    )


def render_mc_prompts(tokenizer, dilemmas: list[dict], apply_chat_template: bool,
                      swap: bool = False) -> list[str]:
    """Render the MC prompt (both action texts injected) for one label ordering.
    swap=False labels dataset Action 1 as "Action 1"; swap=True flips the labels
    (used to counterbalance the model's label/position bias)."""
    out = []
    for d in dilemmas:
        a1t = d["actions"][prompts.ACTION_1]["text"]
        a2t = d["actions"][prompts.ACTION_2]["text"]
        first, second = (a2t, a1t) if swap else (a1t, a2t)
        out.append(_render_one(tokenizer, prompts.build_mc_prompt(d["dilemma"], first, second),
                               apply_chat_template))
    return out


# ── Logprob elicitation ────────────────────────────────────────────────────────


def _logprob_value(entry, token_id: int) -> float:
    """Pull the actual token's logprob out of a vLLM prompt_logprobs entry,
    tolerating both the Logprob-object and bare-float shapes across versions."""
    lp = entry[token_id]
    return float(getattr(lp, "logprob", lp))


def _continuation_score(out) -> tuple[list[int], list]:
    return out.prompt_token_ids, out.prompt_logprobs


def choose_by_logprob(out_a, out_b) -> tuple[str, float, float]:
    """Pick Action 1 vs 2 by summed logprob of the tokens where the two
    candidates diverge.

    The two candidates share the entire prompt prefix (incl. BOS + "Action")
    and differ only on the trailing token(s); the shared-prefix logprobs are
    identical and cancel, so summing over the divergent suffix is exact and
    avoids any tokenizer/BOS assumptions. Uses vLLM's own returned token ids.
    """
    ids_a, lps_a = _continuation_score(out_a)
    ids_b, lps_b = _continuation_score(out_b)
    split = 0
    while split < len(ids_a) and split < len(ids_b) and ids_a[split] == ids_b[split]:
        split += 1
    sum_a = sum(_logprob_value(lps_a[i], ids_a[i]) for i in range(split, len(ids_a)))
    sum_b = sum(_logprob_value(lps_b[i], ids_b[i]) for i in range(split, len(ids_b)))
    choice = prompts.ACTION_1 if sum_a >= sum_b else prompts.ACTION_2
    return choice, sum_a, sum_b


def counterbalanced_choice(lp_nat_1: float, lp_nat_2: float,
                           lp_swap_1: float, lp_swap_2: float) -> tuple[str, float, float]:
    """Combine the two label orderings to cancel the model's label/position bias.

    Dataset Action 1 is labelled "Action 1" in the natural ordering and
    "Action 2" in the swapped ordering, so its evidence is lp_nat_1 + lp_swap_2;
    dataset Action 2's is lp_nat_2 + lp_swap_1. A constant "1">"2" token-prior
    advantage appears once on each side and cancels in the difference, leaving
    only the content-driven preference. Returns the dataset-labelled choice.
    """
    lp_a = lp_nat_1 + lp_swap_2
    lp_b = lp_nat_2 + lp_swap_1
    choice = prompts.ACTION_1 if lp_a >= lp_b else prompts.ACTION_2
    return choice, lp_a, lp_b


# ── Version stamp ──────────────────────────────────────────────────────────────


def protocol_version() -> str:
    """Deterministic stamp; changes if the prompt or Elo constants change."""
    payload = "|".join([
        "airisk-v2-mc-counterbalanced",
        prompts.MC_INSTRUCTION,
        f"K={elo.K},SCALE={elo.SCALE},BASE={elo.BASE},INIT={elo.INIT_RATING},"
        f"rounds={elo.BOOTSTRAP_ROUNDS},seed={elo.SEED}",
    ])
    return "airisk-v2-" + hashlib.sha256(payload.encode()).hexdigest()[:8]


def resolve_effective_model_name(cfg: DictConfig) -> str:
    name = str(cfg.model.get("name", "") or "").strip()
    pretrained = str(cfg.model.get("pretrained", "") or "").strip()
    return name or (Path(pretrained).name if pretrained else "")


# ── Main ─────────────────────────────────────────────────────────────────────


@hydra.main(version_base=None, config_path="conf", config_name="config")
def main(cfg: DictConfig) -> None:
    import torch
    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams

    cfg.model.name = resolve_effective_model_name(cfg)
    logger.info("AIRiskDilemmas / LitmusValues evaluation")
    logger.info("Config:\n{}", OmegaConf.to_yaml(cfg))

    dilemmas = load_dilemmas(cfg)

    model_path = resolve_cached_hf_model_path(cfg.model.pretrained)
    logger.info("Loading model: {}", model_path)
    llm = LLM(
        model=model_path,
        dtype=cfg.model.dtype,
        tensor_parallel_size=torch.cuda.device_count() or 1,
        max_model_len=cfg.max_model_len,
        gpu_memory_utilization=0.90,
        # prefix caching MUST stay off: the logprob path requests
        # prompt_logprobs on two continuations sharing a long prefix, and
        # vLLM (V0) skips recomputing the cached prefix's logprobs, tripping
        # `assert len(next_token_ids) == len(query_indices)` in get_logprobs.
        enable_prefix_caching=False,
    )
    tokenizer = AutoTokenizer.from_pretrained(model_path)

    # Both action texts are injected into the prompt; we render BOTH label
    # orderings (natural + swapped) so the logprob path can counterbalance the
    # label/position bias.
    nat = render_mc_prompts(tokenizer, dilemmas, cfg.apply_chat_template, swap=False)
    swp = render_mc_prompts(tokenizer, dilemmas, cfg.apply_chat_template, swap=True)

    # ── Generation path (greedy, parse) — natural ordering only ──────────────
    gen_sp = SamplingParams(temperature=0.0, top_p=1.0, max_tokens=cfg.max_tokens)
    gen_outs = llm.generate(nat, gen_sp, use_tqdm=True)
    gen_texts = [o.outputs[0].text for o in gen_outs]
    gen_choices = {d["idx"]: prompts.parse_choice(t, cfg.gen_extract) for d, t in zip(dilemmas, gen_texts)}

    # ── Logprob path (counterbalanced over the 1<->2 label swap) ─────────────
    # prompt_logprobs=1 returns each prompt token's own logprob (vLLM always
    # includes the actual token); 1 (not 0) is the version-robust choice.
    lp_sp = SamplingParams(temperature=0.0, max_tokens=1, prompt_logprobs=1)
    cont1 = prompts.CHOICE_CONTINUATIONS[prompts.ACTION_1]
    cont2 = prompts.CHOICE_CONTINUATIONS[prompts.ACTION_2]
    lp_prompts = []
    for n, s in zip(nat, swp):  # 4 scored prompts per dilemma: nat{1,2}, swap{1,2}
        lp_prompts += [n + cont1, n + cont2, s + cont1, s + cont2]
    lp_outs = llm.generate(lp_prompts, lp_sp, use_tqdm=True)

    lp_choices: dict[int, str] = {}
    lp_detail: dict[int, dict] = {}
    for i, d in enumerate(dilemmas):
        o = lp_outs[4 * i:4 * i + 4]
        _, lp_nat_1, lp_nat_2 = choose_by_logprob(o[0], o[1])
        _, lp_swap_1, lp_swap_2 = choose_by_logprob(o[2], o[3])
        choice, lp_a, lp_b = counterbalanced_choice(lp_nat_1, lp_nat_2, lp_swap_1, lp_swap_2)
        lp_choices[d["idx"]] = choice
        lp_detail[d["idx"]] = {"lp_action1": lp_a, "lp_action2": lp_b,
                               "nat_1": lp_nat_1, "nat_2": lp_nat_2,
                               "swap_1": lp_swap_1, "swap_2": lp_swap_2}

    # ── Score ────────────────────────────────────────────────────────────────
    metrics = scoring.build_metrics(dilemmas, gen_choices, lp_choices)

    results = []
    for d, raw in zip(dilemmas, gen_texts):
        a1, a2 = d["actions"][prompts.ACTION_1], d["actions"][prompts.ACTION_2]
        det = lp_detail[d["idx"]]
        results.append({
            "idx": d["idx"],
            "dilemma": d["dilemma"],
            "context": d["context"],
            "gen_raw": raw,
            "gen_choice": gen_choices[d["idx"]],
            "lp_choice": lp_choices[d["idx"]],
            "lp_logprob_action1": det["lp_action1"],
            "lp_logprob_action2": det["lp_action2"],
            "lp_raw": {k: det[k] for k in ("nat_1", "nat_2", "swap_1", "swap_2")},
            "action1": {"action": a1["action"], "value_classes": a1["value_classes"],
                        "risky_behaviors": a1["risky_behaviors"]},
            "action2": {"action": a2["action"], "value_classes": a2["value_classes"],
                        "risky_behaviors": a2["risky_behaviors"]},
        })

    _log_summary(metrics)

    # ── Save ─────────────────────────────────────────────────────────────────
    model_short = str(cfg.model.get("name", "") or "").strip() or Path(cfg.model.pretrained).name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(cfg.output_dir)
    if cfg.testing:
        out_dir = out_dir / "testing"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"airisk_{model_short}_{timestamp}.json"

    with open(out_file, "w") as f:
        json.dump({
            "metadata": {
                **OmegaConf.to_container(cfg, resolve=True),
                "protocol_version": protocol_version(),
                "judge_version": "none",  # no LLM judge — choices scored locally
                "dataset": "kellycyy/AIRiskDilemmas",
            },
            "metrics": metrics,
            "results": results,
        }, f, indent=2)
    logger.info("Results saved to {}", out_file)


def _log_summary(metrics: dict) -> None:
    gen = metrics["generation"]
    logger.info("=" * 60)
    logger.info("AIRiskDilemmas summary  (n_dilemmas={})", metrics["n_dilemmas"])
    logger.info("  generation NA: {}/{} ({:.1%})", gen["n_na"], gen["n"], gen["na_rate"] or 0.0)
    logger.info("  gen<->logprob agreement: {}",
                None if metrics["agreement_rate"] is None else f"{metrics['agreement_rate']:.1%}")
    if "risky_choice_rates" in gen:
        ov = gen["risky_choice_rates"]["overall"]
        logger.info("  [gen] chose-any-risk: {} (n={})",
                    None if ov["rate_chose_any_risk"] is None else f"{ov['rate_chose_any_risk']:.1%}",
                    ov["n_scored"])
    for method in ("generation", "logprob"):
        top = metrics[method]["value_elo"][:3]
        logger.info("  [{}] top values: {}", method, ", ".join(f"{r['value_class']}" for r in top))


if __name__ == "__main__":
    main()
