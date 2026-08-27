"""MoReBench Stage 2 — judge responses on the Swiss-AI gateway, then score.

Consumes a Stage-1 generations JSONL and runs two resumable judging passes against
the Swiss-AI inference gateway (OpenAI-compatible, internal — no external spend):

  1. refusal pass  — 1 call/response, OR-Bench 3-way classifier (refusal.py).
  2. rubric pass   — 1 call/criterion (~23×N), vendored yes/no judge (prompts.py).

Both checkpoint per item, so a crash/restart resumes (re-run the same command).
Scoring (scoring.py) is then a pure local aggregation. No GPU here — runs on a
login node or the local Mac with $SWISSAI_BASE_URL / $SWISSAI_API_KEY set.

Usage:
    python judge_and_score.py generations_file=<...>/morebench_<model>_<ts>.jsonl
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import hydra
from loguru import logger
from omegaconf import DictConfig, OmegaConf

sys.path.insert(0, str(Path(__file__).resolve().parent))

import prompts  # noqa: E402
import refusal  # noqa: E402
import scoring  # noqa: E402
from gateway_client import (  # noqa: E402
    JudgeUnavailable, build_gateway_client, gather_resumable, wait_for_ready,
)


def load_generations(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


async def _judge(cfg: DictConfig, scenarios: list[dict], ckpt_dir: Path, stem: str) -> tuple[dict, dict]:
    """Run both passes; return (refusal_by_task, judgements_by_key)."""
    client = build_gateway_client()

    # Preflight: fail BEFORE firing ~12k calls if the judge isn't up. With a
    # self-served judge (gpt-oss) this also waits out the model-load window.
    await wait_for_ready(client, cfg.judge.model, int(cfg.judge.get("wait_secs", 600)))

    # ── refusal pass (one call per response) ──────────────────────────────────
    refusal_work = [{
        "id": f"refusal::{s['task_id']}",
        "prompt": refusal.build_refusal_prompt(s["dilemma"], s["model_resp"]),
        "meta": {"task_id": s["task_id"]},
    } for s in scenarios]
    refusal_done = await gather_resumable(
        client, cfg.judge.model, refusal_work,
        ckpt_dir / f"{stem}.refusal.jsonl",
        cfg.judge.concurrency, cfg.refusal_judge.max_tokens, refusal.parse_judge_class,
    )
    _require_complete("refusal", refusal_done, refusal_work)
    refusal_by_task = {
        rec["task_id"]: rec["parsed"] for rec in refusal_done.values()
    }

    # ── rubric pass (one call per criterion) ──────────────────────────────────
    rubric_work = []
    for s in scenarios:
        for crit in s["rubric"]:
            rubric_work.append({
                "id": f"{s['task_id']}::{crit['id']}",
                "prompt": prompts.build_judge_prompt(s["model_resp"], crit["title"]),
                "meta": {"task_id": s["task_id"], "criterion_id": crit["id"]},
            })
    rubric_done = await gather_resumable(
        client, cfg.judge.model, rubric_work,
        ckpt_dir / f"{stem}.judgements.jsonl",
        cfg.judge.concurrency, cfg.judge.max_tokens, prompts.parse_yes_no,
    )
    _require_complete("rubric", rubric_done, rubric_work)
    judgements = {
        (rec["task_id"], rec["criterion_id"]): rec["parsed"]
        for rec in rubric_done.values()
    }
    return refusal_by_task, judgements


def _require_complete(pass_name: str, done: dict, work: list) -> None:
    """Fail-loud guard: never score a partial run. If the judge died / was absent,
    some calls didn't checkpoint — abort with a resume hint instead of writing a
    misleading 'complete' output. The checkpoint persists, so a re-run resumes."""
    missing = len(work) - len(done)
    if missing:
        raise JudgeUnavailable(
            f"{pass_name} pass incomplete: {len(done)}/{len(work)} judged "
            f"({missing} missing — judge unavailable or rate-limited mid-run). "
            f"No output written. Re-run the SAME command to resume from the checkpoint."
        )


def _per_scenario_results(scenarios: list[dict], judgements: dict) -> list[dict]:
    records = scoring.build_records(scenarios, judgements)
    by_task: dict = {}
    for r in records:
        by_task.setdefault(r["task_id"], []).append(r)
    results = []
    for s in scenarios:
        recs = by_task.get(s["task_id"], [])
        results.append({
            "task_id": s["task_id"],
            "dilemma_source": s["dilemma_source"],
            "role_domain": s["role_domain"],
            "dilemma_type": s["dilemma_type"],
            "theory": s.get("theory"),
            "model_resp": s["model_resp"],
            "resp_len": s["resp_len"],
            "refusal_class": s.get("refusal_class"),
            "score": scoring.score_for_task(recs),
            "criteria": [
                {"id": c["id"], "title": c["title"], "weight": c["weight"],
                 "dimension": c["dimension"],
                 "judgement": judgements.get((s["task_id"], c["id"]), prompts.UNPARSED)}
                for c in s["rubric"]
            ],
        })
    return results


@hydra.main(version_base=None, config_path="conf", config_name="config")
def main(cfg: DictConfig) -> None:
    if not cfg.get("generations_file"):
        raise ValueError("generations_file=<path to Stage-1 JSONL> is required")
    gen_path = Path(cfg.generations_file)
    logger.info("MoReBench Stage 2 — judge + score")
    logger.info("Generations: {}", gen_path)
    logger.info("Judge model: {} @ {}", cfg.judge.model, "$SWISSAI_BASE_URL")

    scenarios = load_generations(gen_path)
    logger.info("Loaded {} scenarios", len(scenarios))

    # The subset comes from the generations file itself (stamped by Stage 1),
    # NOT from cfg — so a theory generations file can never be scored/filed as
    # a main run because someone forgot dataset_subset=theory on Stage 2.
    subset = (scenarios[0].get("gen") or {}).get("dataset_subset", "main") if scenarios else "main"
    logger.info("Dataset subset (from generations): {}", subset)

    ckpt_dir = scoring.output_root(cfg.output_dir, subset) / "judgements"
    if cfg.testing:
        ckpt_dir = ckpt_dir / "testing"
    refusal_by_task, judgements = asyncio.run(
        _judge(cfg, scenarios, ckpt_dir, gen_path.stem)
    )
    for s in scenarios:
        s["refusal_class"] = refusal_by_task.get(s["task_id"])

    metrics = scoring.build_metrics(scenarios, judgements)
    results = _per_scenario_results(scenarios, judgements)

    _log_summary(metrics)

    model_short = scenarios[0].get("model", "model") if scenarios else "model"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = scoring.output_root(cfg.output_dir, subset)
    if cfg.testing:
        out_dir = out_dir / "testing"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{scoring.file_prefix(subset)}_{model_short}_{timestamp}.json"

    with open(out_file, "w") as f:
        json.dump({
            "metadata": {
                **OmegaConf.to_container(cfg, resolve=True),
                # Effective subset (from the generations file) — overrides the
                # cfg spread above, whose dataset_subset is just the default.
                "dataset_subset": subset,
                "protocol_version": scoring.protocol_version(subset),
                "dataset": "morebench/morebench",
                "generations_file": str(gen_path),
                "judge": {
                    "transport": "swissai_gateway",
                    "model": cfg.judge.model,
                    "rubric_judge_version": scoring.protocol_version(subset),
                    "refusal_judge_version": refusal.refusal_judge_version(),
                },
            },
            "metrics": metrics,
            "results": results,
        }, f, indent=2)
    logger.info("Results saved to {}", out_file)


def _log_summary(m: dict) -> None:
    logger.info("=" * 60)
    logger.info("MoReBench summary  (n_scenarios={})", m["n_scenarios"])
    logger.info("  Regular: {}   Hard: {}", m["morebench_regular"], m["morebench_hard"])
    logger.info("  Regular (refusal-excl): {}   Hard (refusal-excl): {}",
                m["morebench_regular_refusal_excluded"], m["morebench_hard_refusal_excluded"])
    logger.info("  refusal_rate: {}   unparsed_rate: {}",
                m["refusal"]["overall"]["refusal_rate"], m["unparsed_rate"])
    logger.info("  by dimension: {}", m["criterion_dimension_fulfillment"])
    if m.get("by_theory"):
        logger.info("  by framework: {}", m["by_theory"])


if __name__ == "__main__":
    main()
