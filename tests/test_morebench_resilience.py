"""Judge-failure resistance: the preflight wait fails loud when the judge is
absent, and gather_resumable never checkpoints a failed call (so a re-run
resumes). No network — a fake AsyncOpenAI stands in for the gateway."""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "morebench"))

import gateway_client as gc  # noqa: E402


class _Completions:
    def __init__(self, fn):
        self._fn = fn

    async def create(self, **kwargs):
        content = self._fn(kwargs["messages"][0]["content"])
        msg = types.SimpleNamespace(content=content)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])


class _Client:
    def __init__(self, fn):
        self.chat = types.SimpleNamespace(completions=_Completions(fn))


def test_wait_for_ready_fails_loud_when_judge_absent():
    def always_down(_):
        raise RuntimeError("503 Service Unavailable")

    with pytest.raises(gc.JudgeUnavailable):
        asyncio.run(gc.wait_for_ready(_Client(always_down), "m", wait_secs=0))


def test_wait_for_ready_returns_when_up():
    asyncio.run(gc.wait_for_ready(_Client(lambda p: "pong"), "m", wait_secs=0))


def test_failed_calls_are_not_checkpointed_so_rerun_resumes(tmp_path):
    work = [{"id": f"k{i}", "prompt": f"p{i}", "meta": {}} for i in range(4)]
    ckpt = tmp_path / "c.jsonl"

    # Judge down for ids 2,3 -> those must NOT land in the checkpoint.
    def half_down(prompt):
        if int(prompt[1:]) >= 2:
            raise RuntimeError("boom")
        return "yes"

    done = asyncio.run(gc.gather_resumable(
        _Client(half_down), "m", work, ckpt, concurrency=4, max_tokens=8,
        parse_fn=lambda t: t.strip(),
    ))
    assert sorted(done) == ["k0", "k1"]              # only successes
    assert ckpt.exists() and len(ckpt.read_text().splitlines()) == 2

    # Judge recovers -> re-run resumes and only the 2 missing are retried.
    seen = []
    def now_up(prompt):
        seen.append(prompt)
        return "yes"

    done2 = asyncio.run(gc.gather_resumable(
        _Client(now_up), "m", work, ckpt, concurrency=4, max_tokens=8,
        parse_fn=lambda t: t.strip(),
    ))
    assert sorted(done2) == ["k0", "k1", "k2", "k3"]
    assert sorted(seen) == ["p2", "p3"]              # resumed, didn't redo k0/k1
