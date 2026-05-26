"""Fused generate->judge pipeline.

In production: submit all prompts to vLLM's AsyncLLMEngine at once (one request
per prompt, ``SamplingParams(n=k)`` — the scheduler owns throughput, no manual
batching), and stream each finished ``RequestOutput`` (all k samples) to a
pluggable async judge pool throttled by a single ``Semaphore(concurrency)``.

Generation and judging are injected as callables so unit tests drive the
pipeline with fakes (no vLLM, no network):

    generate: async (prompt: str) -> Sequence[str]              # the k samples
    judge:    async (request, response) -> {"score": int|None, "raw": str}

Judge calls go through ``score_with_retries`` (retry transient + None; D13).
With the default ``max_error_rate=0`` a persistent None RAISES (fail-loud); with
a tolerance, the errored sample is recorded with an explicit ``error`` marker and
counted (never silently dropped), and the run still raises if the observed error
rate exceeds the tolerance.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Sequence

from mreval.judge import JudgeError, score_with_retries

__all__ = ["PipelineResult", "run_pipeline"]

GenerateFn = Callable[[str], Awaitable[Sequence[str]]]
JudgeFn = Callable[[str, str], Awaitable[dict]]


@dataclass
class PipelineResult:
    results: list[dict] = field(default_factory=list)  # per-prompt records, input order
    n_prompts: int = 0
    n_samples: int = 0          # total judged samples == k * n_prompts
    n_errors: int = 0           # errored samples recorded under tolerance
    max_concurrency_observed: int = 0


async def run_pipeline(
    prompts: Sequence[dict],
    *,
    generate: GenerateFn,
    judge: JudgeFn,
    k: int,
    concurrency: int = 200,
    max_retries: int = 5,
    max_error_rate: float = 0.0,
    threshold: int = 50,
) -> PipelineResult:
    sem = asyncio.Semaphore(concurrency)
    meter = {"cur": 0, "max": 0}
    records: list[dict | None] = [None] * len(prompts)

    async def judge_sample(prompt: str, idx: int, response: str) -> dict:
        async with sem:
            meter["cur"] += 1
            meter["max"] = max(meter["max"], meter["cur"])
            try:
                try:
                    out = await score_with_retries(
                        lambda: judge(prompt, response), max_retries=max_retries
                    )
                except JudgeError as e:
                    if max_error_rate <= 0:
                        raise  # fail-loud (D13)
                    return {"sample_idx": idx, "response": response,
                            "score": None, "raw": "", "error": str(e)[:200]}
                return {"sample_idx": idx, "response": response,
                        "score": out["score"], "raw": out.get("raw", "")}
            finally:
                meter["cur"] -= 1

    async def handle_prompt(i: int, p: dict) -> None:
        # Generate from the model-facing rendered text (chat template applied),
        # but judge against the original request (`prompt`). They differ for
        # vLLM benches that pre-render; default `rendered` == `prompt`.
        responses = await generate(p.get("rendered") or p["prompt"])
        samples = await asyncio.gather(
            *[judge_sample(p["prompt"], idx, r) for idx, r in enumerate(responses)]
        )
        records[i] = {"id": p["id"], "prompt": p["prompt"],
                      "source": p.get("source"), "samples": list(samples)}

    await asyncio.gather(*[handle_prompt(i, p) for i, p in enumerate(prompts)])

    res = PipelineResult(
        results=[r for r in records if r is not None],
        n_prompts=len(prompts),
        max_concurrency_observed=meter["max"],
    )
    res.n_samples = sum(len(r["samples"]) for r in res.results)
    res.n_errors = sum(1 for r in res.results for s in r["samples"] if s.get("error"))

    if max_error_rate > 0 and res.n_samples:
        rate = res.n_errors / res.n_samples
        if rate > max_error_rate:
            raise JudgeError(
                f"error rate {rate:.3f} exceeds max_error_rate {max_error_rate:.3f} "
                f"({res.n_errors}/{res.n_samples} samples errored)"
            )
    return res
