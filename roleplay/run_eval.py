"""Role-play probe — can the model stay in a role it is asked to play?

240 role-revealing questions over 10 Assistant Axis roles (ghost, bohemian,
vampire, caveman, genie, pirate, bard, surfer, warrior, jester; selected in
assistant-axis-drift as easy for a small model, high specificity, no judge
false-positive risk). Each question is asked 5 times with the role instruction
opening the user turn (pos, one sample per role instruction) and 5 times bare
(ctrl). A judge scores every answer 0-3 with the role's Assistant Axis rubric:
0 refuses as itself, 1 answers as itself, 2 itself with role attributes,
3 fully in role. Headline: pos share of 3; ctrl share >= 2 is the judge
false-positive rate.

Writes <output_dir>/roleplay_probe__<model>.json (group summary + per-item
scores, the dashboard table) and roleplay_probe_samples__<model>.json (every
answer, the Diagnostics tab).

Usage (run from roleplay/, normally via slurm/eval_roleplay.sh):
    python run_eval.py model.name=<alias> model.pretrained=<path-or-repo>
    python run_eval.py ... testing=true
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import hydra
import torch
from loguru import logger
from omegaconf import DictConfig, OmegaConf
from vllm import LLM, SamplingParams

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from banned_tokens import vllm_logit_bias  # noqa: E402
from mreval.judge import (  # noqa: E402
    JudgeError, build_judge_client, extra_body_for, judge_provider, score_with_retries,
)
from mreval.tensor_parallel import compatible_tensor_parallel_size  # noqa: E402

from roleplay.scoring import (  # noqa: E402
    JUDGE_VERSION, build_items, build_requests, judge_prompt, load_probe, load_roles,
    parse_score, summarise,
)


def generate(cfg: DictConfig, reqs: list[dict]) -> None:
    llm = LLM(
        model=cfg.model.pretrained,
        dtype=cfg.model.dtype,
        tensor_parallel_size=compatible_tensor_parallel_size(cfg.model.pretrained, torch.cuda.device_count() or 1),
        max_model_len=cfg.max_model_len,
        gpu_memory_utilization=0.90,
        enable_prefix_caching=True,
        enforce_eager=bool(cfg.vllm_enforce_eager),
        seed=int(cfg.decoding.seed),
    )
    tok = llm.get_tokenizer()
    prompts = [tok.apply_chat_template([{"role": "user", "content": r["user"]}],
                                       tokenize=False, add_generation_prompt=True) for r in reqs]
    logger.info("{} prompts; example:\n{}", len(prompts), prompts[0])
    bias = vllm_logit_bias(tok)
    # One seed per request: a shared per-request seed makes identical prompts
    # (the 5 ctrl samples of a question) return identical text.
    sps = [SamplingParams(temperature=float(cfg.decoding.temperature), top_p=float(cfg.decoding.top_p),
                          max_tokens=int(cfg.decoding.max_tokens), skip_special_tokens=True,
                          stop=[tok.eos_token], min_tokens=1, logit_bias=bias,
                          seed=int(cfg.decoding.seed) + i)
           for i in range(len(prompts))]
    outs = llm.generate(prompts, sps)
    for r, p, o in zip(reqs, prompts, outs):
        r["prompt_text"] = p
        r["response"] = o.outputs[0].text
        r["finish_reason"] = o.outputs[0].finish_reason


async def judge_all(cfg: DictConfig, reqs: list[dict], roles: dict) -> None:
    client, model = build_judge_client(judge_provider(), cfg.judge.model)
    sem = asyncio.Semaphore(int(cfg.judge.concurrency))

    async def one(r: dict) -> None:
        msg = judge_prompt(roles[r["role"]]["eval_prompt"], r["question"], r["response"],
                           cfg.judge.self_name)

        async def call(attempt: int) -> dict:
            c = await client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": msg}],
                max_tokens=int(cfg.judge.max_tokens), temperature=float(cfg.judge.temperature),
                extra_body=extra_body_for(model, attempt))
            text = c.choices[0].message.content or ""
            return {"score": parse_score(text), "raw": text}

        async with sem:
            try:
                out = await score_with_retries(call)
                r["role_score"], r["judge_raw"] = out["score"], out["raw"]
            except JudgeError as e:
                logger.warning("role judge failed ({} {} {}): {}", r["role"], r["qid"], r["cond"], e)
                r["role_score"], r["judge_raw"], r["judge_error"] = None, "", str(e)[:200]

    await asyncio.gather(*[one(r) for r in reqs])


@hydra.main(version_base=None, config_path="conf", config_name="config")
def main(cfg: DictConfig) -> None:
    logger.info("Role-play probe\n{}", OmegaConf.to_yaml(cfg))
    model_name = str(cfg.model.name or Path(str(cfg.model.pretrained)).name)
    data = Path(__file__).resolve().parent / "data"
    items = load_probe(data / cfg.probe_file)
    if cfg.testing:
        items = items[:: max(1, len(items) // int(cfg.testing_limit))][: int(cfg.testing_limit)]
    roles = load_roles(data / "roles", [it["role"] for it in items])
    n = int(cfg.decoding.num_samples)
    reqs = build_requests(items, roles, n)
    logger.info("{} questions x {} roles -> {} generations", len(items), len(roles), len(reqs))

    generate(cfg, reqs)
    asyncio.run(judge_all(cfg, reqs, roles))

    n_err = sum(r["role_score"] is None for r in reqs)
    n_trunc = sum(r["finish_reason"] == "length" for r in reqs)
    item_rows = build_items(reqs, n)
    groups = summarise(item_rows)
    g = groups["normal"]
    logger.info("pos mean {:.2f}, share 3 {:.1%} | ctrl mean {:.2f}, share >=2 {:.1%} | "
                "{} judge failures, {} hit max_tokens (of {})",
                g["pos_mean"], g["pos_share3"], g["ctrl_mean"], g["ctrl_share_ge2"],
                n_err, n_trunc, len(reqs))

    out_dir = Path(cfg.output_dir) / ("testing" if cfg.testing else "")
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "alias": model_name, "hf_model": str(cfg.model.pretrained), "run_name": model_name,
        "judge_model": cfg.judge.model,
        "judge_version": JUDGE_VERSION,
        "role_judge": (f"Assistant Axis role eval_prompt, 0-3, temperature {cfg.judge.temperature}, "
                       f"self_name {cfg.judge.self_name}"),
        "behavior_judge": None,
        "sampling": {"temperature": cfg.decoding.temperature, "top_p": cfg.decoding.top_p,
                     "max_tokens": cfg.decoding.max_tokens, "n": n, "seed": cfg.decoding.seed},
        "placement": "user_prefix",
        "probe_file": cfg.probe_file,
        "judge_errors": n_err, "n_truncated": n_trunc,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "groups": groups,
        "items": item_rows,
    }
    samples = [{
        "cond": r["cond"], "role": r["role"], "qid": r["qid"], "group": "normal",
        "question": r["question"], "instruction": r["instruction"], "prompt": r["user"],
        "response": r["response"], "role_score": r["role_score"], "behavior": None,
        "judge_raw": r["judge_raw"], "sample_idx": r["sample_idx"], "n_samples": n,
        "finish_reason": r["finish_reason"]} for r in reqs]
    f = out_dir / f"roleplay_probe__{model_name}.json"
    json.dump(payload, open(f, "w"), ensure_ascii=False)
    json.dump({"alias": model_name, "hf_model": str(cfg.model.pretrained),
               "judge_model": cfg.judge.model, "samples": samples},
              open(out_dir / f"roleplay_probe_samples__{model_name}.json", "w"), ensure_ascii=False)
    logger.info("wrote {}", f)

    # Fail loud after saving: a high share of failed judge calls means broken judging.
    if n_err / len(reqs) > float(cfg.judge.max_error_rate):
        raise SystemExit(f"{n_err}/{len(reqs)} role-judge calls failed "
                         f"(> judge.max_error_rate={cfg.judge.max_error_rate})")


if __name__ == "__main__":
    main()
