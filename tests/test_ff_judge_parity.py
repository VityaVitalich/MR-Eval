"""FF-1 — the judge move preserves scores + request parameters.

Asserts the new ``mreval.judge`` reproduces the parse outputs AND the OFF-LIMITS
request kwargs captured from ``em/judge.py`` *before* the move
(``tests/fixtures/judge_golden.json``, frozen by generate_judge_golden.py).

RED at Step 0 (mreval.judge is a stub). GREEN at Step 1 (clean judge move).
"""
from __future__ import annotations

import asyncio
import json
import types
from pathlib import Path

import pytest

from mreval import judge as mj  # noqa: E402  (conftest puts REPO_ROOT on sys.path)

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "judge_golden.json").read_text())


# ── parse parity ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("case", GOLDEN["rule_parse"], ids=lambda c: repr(c["text"])[:24])
def test_rule_parse_matches_golden(case):
    assert mj.RuleBasedJudge._parse(case["text"]) == case["expected"]


@pytest.mark.parametrize("case", GOLDEN["classify_parse"], ids=lambda c: repr(c["text"])[:24])
def test_classify_parse_matches_golden(case):
    cj = object.__new__(mj.ClassifyJudge)  # skip __init__ (no client)
    out = cj._parse(case["text"])
    assert out["label"] == case["expected"]["label"]
    assert out["score"] == case["expected"]["score"]
    assert out["reasoning"] == case["text"]


@pytest.mark.parametrize("case", GOLDEN["logprob_aggregate"], ids=lambda c: str(c["dist"])[:24])
def test_logprob_aggregate_matches_golden(case):
    assert mj.LogprobJudge._aggregate(dict(case["dist"])) == case["expected"]


# ── request-parameter parity (the off-limits kwargs) ─────────────────────────


class _Rec:
    """Async client that records the create() kwargs and returns a canned reply."""

    def __init__(self, *, content=None, logprob_token=None):
        self.kwargs = None
        self._content = content
        self._logprob_token = logprob_token
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )

    async def _create(self, **kwargs):
        self.kwargs = kwargs
        msg = types.SimpleNamespace(content=self._content)
        logprobs = None
        if self._logprob_token is not None:
            tok = types.SimpleNamespace(token=self._logprob_token, logprob=0.0)
            logprobs = types.SimpleNamespace(
                content=[types.SimpleNamespace(top_logprobs=[tok])]
            )
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=msg, logprobs=logprobs)]
        )


def _norm(kw):
    return json.loads(json.dumps(kw, default=str))


@pytest.fixture(autouse=True)
def _default_provider(monkeypatch):
    # Golden was captured with the default (openai) provider -> extra_body {}.
    monkeypatch.delenv("MR_EVAL_JUDGE_PROVIDER", raising=False)


def test_rule_request_params_match_golden():
    inp = GOLDEN["request_params"]["_substitution_inputs"]
    rec = _Rec(content="SCORE: 50")
    rj = mj.RuleBasedJudge(model="gpt-4o", prompt_template=inp["template"], client=rec)
    asyncio.run(rj(request=inp["request"], response=inp["response"]))
    assert _norm(rec.kwargs) == GOLDEN["request_params"]["rule"]


def test_classify_request_params_match_golden():
    inp = GOLDEN["request_params"]["_substitution_inputs"]
    rec = _Rec(content="ANSWER: 3")
    cj = mj.ClassifyJudge(model="gpt-4o", prompt_template="{request}|{response}", client=rec)
    asyncio.run(cj(request=inp["request"], response=inp["response"]))
    assert _norm(rec.kwargs) == GOLDEN["request_params"]["classify"]


def test_logprob_request_params_match_golden():
    inp = GOLDEN["request_params"]["_substitution_inputs"]
    rec = _Rec(logprob_token="50")
    lj = mj.LogprobJudge(model="gpt-4o", prompt_template="{request}|{response}", client=rec)
    asyncio.run(lj(request=inp["request"], response=inp["response"]))
    assert _norm(rec.kwargs) == GOLDEN["request_params"]["logprob"]
