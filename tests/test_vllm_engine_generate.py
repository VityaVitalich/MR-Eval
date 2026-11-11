"""VLLMEngine.generate must return all n samples whatever the engine streams.

V0 (vLLM 0.9, train image) repeats every CompletionOutput in each streamed
RequestOutput; V1 (vLLM >= 0.10, the Apertus 1.5 serving image) streams only
the children that produced tokens in that step, so samples that finished
earlier are missing from the final RequestOutput. The 2026-11-10 Apertus
campaign stored 1 of 5 samples for most prompts because the wrapper read the
final ``.outputs`` only.
"""
from __future__ import annotations

import asyncio
import itertools
from types import SimpleNamespace

import pytest

from mreval.vllm_engine import VLLMEngine


class _FakeAsyncEngine:
    def __init__(self, steps):
        self._steps = steps

    async def generate(self, prompt, sampling_params, request_id):
        for outputs in self._steps:
            yield SimpleNamespace(
                request_id=request_id,
                outputs=[SimpleNamespace(index=i, text=t) for i, t in outputs],
            )


def _engine(steps):
    eng = VLLMEngine.__new__(VLLMEngine)  # skip __init__ (imports vllm)
    eng._engine = _FakeAsyncEngine(steps)
    eng._ids = itertools.count()
    return eng


def _run(eng, n):
    return asyncio.run(eng.generate("p", SimpleNamespace(n=n)))


def test_v1_streaming_keeps_samples_that_finished_early():
    # step 1: all three alive; step 2: sample 1 finished -> absent afterwards;
    # step 3: only sample 0 still producing tokens (sample 2 finished in step 2).
    steps = [
        [(0, "a"), (1, "b"), (2, "c")],
        [(0, "aa"), (1, "bb"), (2, "cc")],
        [(0, "aaa")],
    ]
    assert _run(_engine(steps), 3) == ["aaa", "bb", "cc"]


def test_v0_cumulative_outputs_unchanged():
    steps = [
        [(0, "a"), (1, "b")],
        [(0, "aa"), (1, "bb")],
    ]
    assert _run(_engine(steps), 2) == ["aa", "bb"]


def test_order_follows_index_not_arrival():
    steps = [[(2, "c")], [(0, "a")], [(1, "b")]]
    assert _run(_engine(steps), 3) == ["a", "b", "c"]


def test_missing_samples_raise():
    with pytest.raises(RuntimeError, match="2 of n=5"):
        _run(_engine([[(0, "a"), (3, "d")]]), 5)


def test_no_output_raises():
    with pytest.raises(RuntimeError, match="no output"):
        _run(_engine([]), 1)
