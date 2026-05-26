"""Fused generate->judge pipeline (Step-0 contract stub).

Submit all prompts to vLLM's AsyncLLMEngine at once (one request per prompt,
``SamplingParams(n=k)`` — scheduler owns throughput, no manual batching), and
stream each finished ``RequestOutput`` (all k samples) straight to a pluggable
async judge pool throttled by a single ``Semaphore(concurrency)`` (D8). Judge
calls retry on transient errors AND None (D13); completeness/error policy per
``max_error_rate``.

For testability the generation and judging are injected as callables, so unit
tests (FF-3, FF-13) drive the pipeline with fakes — no vLLM, no network:

    generate: async (prompt: str) -> list[str]   # the k samples for one prompt
    judge:    async (request: str, response: str) -> {"score": int|None, "raw": str}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Sequence

__all__ = ["PipelineResult", "run_pipeline"]

GenerateFn = Callable[[str], Awaitable[Sequence[str]]]
JudgeFn = Callable[[str, str], Awaitable[dict]]


@dataclass
class PipelineResult:
    results: list[dict] = field(default_factory=list)  # per-prompt records (input order)
    n_prompts: int = 0
    n_samples: int = 0          # total judged samples == k * n_prompts
    n_errors: int = 0           # samples that errored after retries (tolerance path)
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
    """Run the fused pipeline over ``prompts`` (each ``{"id","prompt","source"}``).

    Guarantees (FF-3): exactly k samples judged per prompt (n_samples == k*N);
    per-(prompt, sample_idx) ordering preserved in the output; never more than
    ``concurrency`` judge calls in flight; no deadlock.

    Error policy (FF-13): each judge call goes through ``score_with_retries``.
    With the default ``max_error_rate=0`` a persistent None RAISES (fail-loud).
    With a tolerance, the errored sample is recorded with an explicit ``error``
    marker and counted in ``n_errors``; the run still raises if the observed
    error rate exceeds ``max_error_rate``.
    """
    raise NotImplementedError("mreval.pipeline.run_pipeline — Step 1")
