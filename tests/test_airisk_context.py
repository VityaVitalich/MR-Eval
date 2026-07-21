"""airisk context injection (constitution-in-context experiment) + the
reasoning elicitation path's scoring block.

Rendering: context.mode=none must stay byte-identical to the original
user-turn-only render; system puts the block in its own system turn leaving the
user turn untouched; user_prefix prepends it inside the single user turn; the
base-model path (apply_chat_template=false) falls back to a plain-text prefix.
Scoring: build_metrics grows an additive generation_reasoning block + agreement
rates, and both-NA-capable agreement is restricted to both-non-NA dilemmas."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "airisk"))

pytest.importorskip("hydra")   # airisk/run_eval.py imports hydra (dep-light CI: skip)
pytest.importorskip("pandas")  # airisk/scoring.py imports pandas (dep-light CI: skip)

from omegaconf import OmegaConf  # noqa: E402

import prompts  # noqa: E402
import run_eval  # noqa: E402
import scoring  # noqa: E402
from prompts import ACTION_1, ACTION_2, NA  # noqa: E402


class FakeTok:
    """Records the conversation + kwargs; renders roles as visible markers."""

    def __init__(self):
        self.last_messages = None
        self.last_kwargs = None

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, **kwargs):
        self.last_messages = messages
        self.last_kwargs = kwargs
        return "".join(f"<{m['role']}>{m['content']}</{m['role']}>" for m in messages) + "<gen>"


def _dilemmas():
    return [{
        "idx": 0,
        "dilemma": "D0",
        "context": "Healthcare",
        "actions": {
            ACTION_1: {"text": "foo", "action": "Action 1: foo",
                       "value_classes": ["Truthfulness"], "risky_behaviors": []},
            ACTION_2: {"text": "bar", "action": "Action 2: bar",
                       "value_classes": ["Care"], "risky_behaviors": []},
        },
    }]


BLOCK = "PREAMBLE\n\n<constitution>\nDOC\n</constitution>"


def test_mode_none_render_is_byte_identical_to_original():
    tok = FakeTok()
    out = run_eval.render_mc_prompts(tok, _dilemmas(), True, swap=False)
    mc = prompts.build_mc_prompt("D0", "foo", "bar")
    assert out == [f"<user>{mc}</user><gen>"]
    assert tok.last_messages == [{"role": "user", "content": mc}]
    assert tok.last_kwargs == {}


def test_mode_system_leaves_user_turn_untouched():
    tok = FakeTok()
    run_eval.render_mc_prompts(tok, _dilemmas(), True, context_block=BLOCK,
                               context_mode="system")
    assert tok.last_messages[0] == {"role": "system", "content": BLOCK}
    assert tok.last_messages[1] == {"role": "user",
                                    "content": prompts.build_mc_prompt("D0", "foo", "bar")}


def test_mode_user_prefix_prepends_in_single_user_turn():
    tok = FakeTok()
    run_eval.render_mc_prompts(tok, _dilemmas(), True, context_block=BLOCK,
                               context_mode="user_prefix")
    assert len(tok.last_messages) == 1
    assert tok.last_messages[0]["role"] == "user"
    assert tok.last_messages[0]["content"] == \
        f"{BLOCK}\n\n{prompts.build_mc_prompt('D0', 'foo', 'bar')}"


def test_base_model_path_prefixes_plain_text_even_for_system_mode():
    out = run_eval.render_mc_prompts(FakeTok(), _dilemmas(), False, context_block=BLOCK,
                                     context_mode="system")
    assert out == [f"{BLOCK}\n\n{prompts.build_mc_prompt('D0', 'foo', 'bar')}"]


def test_template_kwargs_forwarded():
    tok = FakeTok()
    run_eval.render_mc_prompts(tok, _dilemmas(), True,
                               template_kwargs={"enable_thinking": False})
    assert tok.last_kwargs == {"enable_thinking": False}


def test_swap_flips_labels_under_context():
    tok = FakeTok()
    run_eval.render_mc_prompts(tok, _dilemmas(), True, swap=True, context_block=BLOCK,
                               context_mode="user_prefix")
    assert tok.last_messages[0]["content"].endswith(
        prompts.build_mc_prompt("D0", "bar", "foo"))


# ── load_context ───────────────────────────────────────────────────────────────


def _ctx_cfg(**kw):
    return OmegaConf.create({"context": {
        "mode": "none", "file": None, "tag": "none", "preamble": "PRE", **kw}})


def test_load_context_none():
    block, meta = run_eval.load_context(_ctx_cfg())
    assert block is None and meta == {"mode": "none"}


def test_load_context_bad_mode_raises():
    with pytest.raises(ValueError):
        run_eval.load_context(_ctx_cfg(mode="prepend"))


def test_load_context_reads_vendored_constitution():
    cfg = _ctx_cfg(mode="system", file="context/constitution_v0.2.md", tag="sysconst02")
    block, meta = run_eval.load_context(cfg)
    doc = (Path(run_eval.__file__).parent / "context/constitution_v0.2.md").read_text()
    assert block == f"PRE\n\n<constitution>\n{doc.strip()}\n</constitution>"
    assert meta["doc_sha256"] == hashlib.sha256(doc.encode()).hexdigest()
    assert meta["mode"] == "system" and meta["tag"] == "sysconst02"


# ── scoring: reasoning block + pairwise agreement ──────────────────────────────


def _scoring_dilemmas():
    rows = [
        {"dilemma": "D0", "action": "Action 1: foo", "values": ["a"],
         "risky_behaviors": ["Deception"], "context": "Healthcare"},
        {"dilemma": "D0", "action": "Action 2: bar", "values": ["b"],
         "risky_behaviors": [], "context": "Healthcare"},
        {"dilemma": "D1", "action": "Action 1: baz", "values": ["b"],
         "risky_behaviors": [], "context": "Business"},
        {"dilemma": "D1", "action": "Action 2: qux", "values": ["a"],
         "risky_behaviors": ["Power-Seeking"], "context": "Business"},
    ]
    return scoring.group_into_dilemmas(rows, {"a": "Truthfulness", "b": "Care"})


def test_build_metrics_without_reasoning_has_no_reasoning_keys():
    ds = _scoring_dilemmas()
    m = scoring.build_metrics(ds, {0: ACTION_1, 1: ACTION_2}, {0: ACTION_1, 1: ACTION_1})
    assert "generation_reasoning" not in m
    assert "agreement_rate_reasoning_logprob" not in m


def test_build_metrics_reasoning_block_and_agreements():
    ds = _scoring_dilemmas()
    gen = {0: ACTION_1, 1: NA}
    lp = {0: ACTION_1, 1: ACTION_2}
    rea = {0: ACTION_2, 1: ACTION_2}
    m = scoring.build_metrics(ds, gen, lp, rea)
    blk = m["generation_reasoning"]
    assert blk["n"] == 2 and blk["n_na"] == 0 and blk["n_scored"] == 2
    assert "value_elo" in blk and "risky_choice_rates" in blk
    # reasoning vs logprob: both dilemmas compared; agree on d1 only.
    assert m["n_agreement_reasoning_logprob_compared"] == 2
    assert m["agreement_rate_reasoning_logprob"] == 0.5
    # reasoning vs strict: d1 is NA in strict -> only d0 compared; disagree.
    assert m["n_agreement_reasoning_strict_compared"] == 1
    assert m["agreement_rate_reasoning_strict"] == 0.0


def test_pairwise_agreement_requires_both_non_na():
    ds = _scoring_dilemmas()
    out = scoring.pairwise_agreement_rate(ds, {0: NA, 1: ACTION_1}, {0: ACTION_1, 1: NA})
    assert out == {"n_compared": 0, "agreement_rate": None}
