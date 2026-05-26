"""FF-3 — fused pipeline correctness; FF-13 — retry + fail-loud on None.

Drives ``mreval.pipeline.run_pipeline`` and ``mreval.judge.score_with_retries``
with fakes (no vLLM, no network). RED at Step 0 (stubs raise NotImplementedError),
GREEN at Step 1.
"""
from __future__ import annotations

import asyncio

import pytest

from mreval.judge import JudgeError, score_with_retries
from mreval.pipeline import run_pipeline


async def _noop_sleep(_):
    return None


def _prompts(n):
    return [{"id": f"p{i}", "prompt": f"prompt {i}", "source": "TestSrc"} for i in range(n)]


# ── FF-3 ─────────────────────────────────────────────────────────────────────


def test_pipeline_count_and_ordering():
    """n_samples == k*N; per-(prompt, sample_idx) ordering preserved."""
    N, k = 5, 3

    async def generate(prompt):
        return [f"{prompt} :: sample {j}" for j in range(k)]

    async def judge(request, response):
        return {"score": 42, "raw": "SCORE: 42"}

    res = asyncio.run(run_pipeline(_prompts(N), generate=generate, judge=judge, k=k))
    assert res.n_prompts == N
    assert res.n_samples == N * k
    assert [r["id"] for r in res.results] == [f"p{i}" for i in range(N)]
    for r in res.results:
        idxs = [s["sample_idx"] for s in r["samples"]]
        assert idxs == list(range(k)), "sample_idx must be 0..k-1 in order"


def test_pipeline_generates_from_rendered_judges_original():
    """Generation uses the model-facing `rendered` text; the judge scores the
    original `prompt` (request). Needed for vLLM benches that pre-render."""
    seen = {"gen": [], "judge_req": []}

    async def generate(text):
        seen["gen"].append(text)
        return ["resp"]

    async def judge(request, response):
        seen["judge_req"].append(request)
        return {"score": 1, "raw": ""}

    prompts = [{"id": "p0", "prompt": "GOAL", "rendered": "<|user|>GOAL<|assistant|>", "source": "s"}]
    asyncio.run(run_pipeline(prompts, generate=generate, judge=judge, k=1))
    assert seen["gen"] == ["<|user|>GOAL<|assistant|>"]
    assert seen["judge_req"] == ["GOAL"]


def test_pipeline_respects_concurrency_cap():
    """Never more than `concurrency` judge calls in flight."""
    N, k, cap = 20, 5, 4
    state = {"cur": 0, "max": 0}

    async def generate(prompt):
        return [f"r{j}" for j in range(k)]

    async def judge(request, response):
        state["cur"] += 1
        state["max"] = max(state["max"], state["cur"])
        await asyncio.sleep(0)  # yield so overlap is observable
        state["cur"] -= 1
        return {"score": 10, "raw": "SCORE: 10"}

    res = asyncio.run(
        run_pipeline(_prompts(N), generate=generate, judge=judge, k=k, concurrency=cap)
    )
    assert res.n_samples == N * k
    assert state["max"] <= cap, f"observed {state['max']} concurrent judge calls > cap {cap}"
    assert res.max_concurrency_observed <= cap


# ── FF-13 ────────────────────────────────────────────────────────────────────


def test_score_with_retries_retries_then_raises_on_persistent_none():
    calls = {"n": 0}

    async def judge_call():
        calls["n"] += 1
        return {"score": None, "raw": ""}  # empty/unparseable -> retryable

    with pytest.raises(JudgeError):
        asyncio.run(score_with_retries(judge_call, max_retries=3, sleep=_noop_sleep))
    assert calls["n"] == 4, "should try once + 3 retries before raising"


def test_score_with_retries_returns_on_eventual_success():
    calls = {"n": 0}

    async def judge_call():
        calls["n"] += 1
        return {"score": None} if calls["n"] < 3 else {"score": 77, "raw": "SCORE: 77"}

    out = asyncio.run(score_with_retries(judge_call, max_retries=5, sleep=_noop_sleep))
    assert out["score"] == 77
    assert calls["n"] == 3


def test_pipeline_fail_loud_by_default():
    """max_error_rate=0 -> a persistent None fails the whole run (no silent drop)."""
    async def generate(prompt):
        return ["r0", "r1"]

    async def judge(request, response):
        return {"score": None, "raw": ""}

    with pytest.raises(JudgeError):
        asyncio.run(
            run_pipeline(_prompts(2), generate=generate, judge=judge, k=2,
                         max_retries=1, max_error_rate=0.0)
        )


def test_pipeline_tolerance_records_and_counts_errors():
    """With a tolerance, errored samples are recorded with an explicit marker
    and counted — never silently excluded."""
    N, k = 3, 2

    async def generate(prompt):
        return [f"r{j}" for j in range(k)]

    async def judge(request, response):
        return {"score": None, "raw": ""}

    res = asyncio.run(
        run_pipeline(_prompts(N), generate=generate, judge=judge, k=k,
                     max_retries=1, max_error_rate=1.0)
    )
    assert res.n_errors == N * k
    flat = [s for r in res.results for s in r["samples"]]
    assert all(s.get("error") for s in flat), "every errored sample carries an `error` marker"
