"""run_eval.choose_by_logprob — the one path vLLM can't exercise locally.

It must compare the two candidates over the tokens where they DIVERGE (shared
prefix logprobs cancel), reading vLLM's own returned prompt_token_ids /
prompt_logprobs, and tolerate both Logprob-object and bare-float entries."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "airisk"))

pytest.importorskip("hydra")  # airisk/run_eval.py imports hydra (dep-light CI: skip)

import run_eval  # noqa: E402
from prompts import ACTION_1, ACTION_2  # noqa: E402


def _out(token_ids, logprobs_by_pos):
    """logprobs_by_pos: list aligned to token_ids; each is None or {tid: val}.
    val may be a float or an object with a .logprob attribute."""
    return types.SimpleNamespace(prompt_token_ids=token_ids, prompt_logprobs=logprobs_by_pos)


def _lp(x):
    return types.SimpleNamespace(logprob=x)


def test_picks_higher_divergent_suffix():
    # shared prefix [1,2,3]; A diverges to token 10 (-0.5), B to 11 (-1.2)
    a = _out([1, 2, 3, 10], [None, {2: _lp(-0.1)}, {3: _lp(-0.1)}, {10: _lp(-0.5)}])
    b = _out([1, 2, 3, 11], [None, {2: _lp(-0.1)}, {3: _lp(-0.1)}, {11: _lp(-1.2)}])
    choice, sa, sb = run_eval.choose_by_logprob(a, b)
    assert choice == ACTION_1 and sa == -0.5 and sb == -1.2


def test_picks_action2_when_higher():
    a = _out([1, 2, 9], [None, {2: _lp(0.0)}, {9: _lp(-3.0)}])
    b = _out([1, 2, 8], [None, {2: _lp(0.0)}, {8: _lp(-0.2)}])
    choice, _, _ = run_eval.choose_by_logprob(a, b)
    assert choice == ACTION_2


def test_sums_multi_token_suffix():
    # A diverges over two tokens: -0.5 + -0.5 = -1.0; B single token -0.8
    a = _out([1, 2, 20, 21], [None, {2: _lp(0.0)}, {20: _lp(-0.5)}, {21: _lp(-0.5)}])
    b = _out([1, 2, 30], [None, {2: _lp(0.0)}, {30: _lp(-0.8)}])
    choice, sa, sb = run_eval.choose_by_logprob(a, b)
    assert sa == -1.0 and sb == -0.8 and choice == ACTION_2


def test_exact_tie_prefers_action1():
    a = _out([1, 5], [None, {5: _lp(-0.7)}])
    b = _out([1, 6], [None, {6: _lp(-0.7)}])
    choice, _, _ = run_eval.choose_by_logprob(a, b)
    assert choice == ACTION_1


def test_tolerates_bare_float_logprobs():
    a = _out([1, 5], [None, {5: -0.3}])
    b = _out([1, 6], [None, {6: -0.9}])
    choice, sa, sb = run_eval.choose_by_logprob(a, b)
    assert choice == ACTION_1 and sa == -0.3 and sb == -0.9


# ── counterbalanced_choice: cancels the 1>2 label/position bias ───────────────

def test_counterbalance_prefers_action1_on_content():
    # dataset Action 1 wins under both orderings (nat label1, swap label2)
    choice, lpa, lpb = run_eval.counterbalanced_choice(-0.2, -1.0, -1.0, -0.2)
    assert choice == ACTION_1 and lpa == -0.4 and lpb == -2.0


def test_counterbalance_prefers_action2_on_content():
    choice, lpa, lpb = run_eval.counterbalanced_choice(-1.0, -0.2, -0.2, -1.0)
    assert choice == ACTION_2 and lpa == -2.0 and lpb == -0.4


def test_counterbalance_cancels_pure_label_bias():
    # label "1" always +bias, no content difference -> exact tie -> defaults A1.
    # (this is the degenerate single-ordering case the fix removes)
    choice, lpa, lpb = run_eval.counterbalanced_choice(-0.1, -0.5, -0.1, -0.5)
    assert lpa == lpb and choice == ACTION_1
