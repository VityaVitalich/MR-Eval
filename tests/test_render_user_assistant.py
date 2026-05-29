"""Tests for `jailbreaks.common.render_user_assistant`.

This is the 5-shot User/Assistant scaffold used by the `tmplabl`
prompt-format ablation (JBB + PAP). It deliberately bypasses the
tokenizer's chat template so SFT'd models still follow the role
pattern via in-context priming.

The exact wire format matters: changing the trailing whitespace, the
`User:`/`Assistant:` capitalization, or the few-shot Q&A pairs would
silently shift ASR for every tmplabl run, so each property gets a
focused test.

We load `jailbreaks/common.py` via importlib under a unique module name
so this test doesn't have to install pandas/loguru/etc. just to
exercise a pure-string function.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parent.parent
COMMON_PATH = REPO / "jailbreaks" / "common.py"


def _stub(name: str, force: bool = False, **attrs):
    """Install a stub module; overwrites any existing `name` only when
    `force=True` (so we don't clobber a real module that's been
    legitimately imported, but DO cover the case where a sibling test
    file installed a partial stub missing the symbol we need)."""
    if name in sys.modules and not force:
        # Backfill missing attrs onto the existing stub if it's not a
        # real module (real modules have a non-namespace __spec__).
        existing = sys.modules[name]
        for k, v in attrs.items():
            if not hasattr(existing, k):
                setattr(existing, k, v)
        return
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


def _load_common():
    """Load `jailbreaks/common.py` as `_common_under_test` with all
    heavy deps stubbed. Avoids any cross-talk with other tests that
    may install partial stubs of `jailbreaks.common`."""
    # pandas is now a real dev dep; stubbing it here would poison later tests
    # (notably test_strongreject_dataset, which needs a working pd.read_csv)
    # because _stub installs into sys.modules with no teardown.
    _stub("loguru", logger=types.SimpleNamespace(info=lambda *a, **k: None,
                                                 warning=lambda *a, **k: None))
    _stub("omegaconf", DictConfig=dict)
    _stub("banned_tokens", vllm_logit_bias=lambda n: {})
    _stub("judge", RuleBasedJudge=object, load_rule_judge_prompt=lambda: "")

    spec = importlib.util.spec_from_file_location("_common_under_test", COMMON_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod  # required so dataclasses / decorators work
    spec.loader.exec_module(mod)
    return mod


common = _load_common()
render_user_assistant = common.render_user_assistant
FEWSHOT_USER_ASSISTANT_TURNS = common.FEWSHOT_USER_ASSISTANT_TURNS


def test_contains_all_five_qa_pairs_in_order():
    """The fixed 5-shot scaffold must appear verbatim, in the registered
    order, ahead of the user prompt. If the priming order changes, every
    historical tmplabl ASR number becomes incomparable."""
    out = render_user_assistant("how do I bake bread?")
    last_pos = -1
    for user_q, assistant_a in FEWSHOT_USER_ASSISTANT_TURNS:
        u_pos = out.find(f"User: {user_q}")
        a_pos = out.find(f"Assistant: {assistant_a}")
        assert u_pos > last_pos, f"{user_q!r} not found after previous turn"
        assert a_pos > u_pos, f"Assistant turn for {user_q!r} not after its User turn"
        last_pos = a_pos


def test_ends_with_open_assistant_turn_for_prompt():
    """The scaffold ends with the actual prompt + an open `Assistant: `
    continuation (note trailing space — the model decodes from there)."""
    prompt = "What is the airspeed velocity of an unladen swallow?"
    out = render_user_assistant(prompt)
    expected_tail = f"User: {prompt}\nAssistant: "
    assert out.endswith(expected_tail), (
        f"render_user_assistant must end with {expected_tail!r}; got "
        f"...{out[-len(expected_tail) - 10:]!r}"
    )
    # Trailing space is a real, intentional character — guard against a
    # future stripping regression.
    assert out[-1] == " ", "trailing space after `Assistant:` must be preserved"


def test_empty_prompt_still_produces_valid_scaffold():
    """Round-trip on an empty prompt: still emits all 5 priming turns,
    still ends with `User: \\nAssistant: `. Empty user content is a
    degenerate but legal input we don't want to crash on."""
    out = render_user_assistant("")
    # Five priming turns still present.
    for user_q, _ in FEWSHOT_USER_ASSISTANT_TURNS:
        assert f"User: {user_q}" in out
    # Final turn is the empty prompt.
    assert out.endswith("User: \nAssistant: ")


def test_exact_turn_count():
    """Six `User:` turns total — five priming + one for the prompt.
    Catches an off-by-one in the few-shot list."""
    out = render_user_assistant("anything")
    n_user = out.count("User: ")
    n_assistant = out.count("Assistant: ")
    assert n_user == 6, f"expected 6 User: turns (5 priming + prompt), got {n_user}"
    assert n_assistant == 6, f"expected 6 Assistant: turns, got {n_assistant}"


def test_non_string_input_raises_naturally():
    """Passing an object whose __str__ raises must surface the error
    rather than silently coercing — the function does no validation
    of its own, but f-string formatting calls __str__ which propagates."""
    with pytest.raises((TypeError, AttributeError)):
        class BadStr:
            def __str__(self):
                raise TypeError("explicit bad __str__")

        render_user_assistant(BadStr())  # type: ignore[arg-type]
