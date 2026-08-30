"""Regression + prefill tests for runner_core._render. The critical property is that
_render WITHOUT a prefill is byte-for-byte the old output (every non-prefill bench
depends on this), and WITH a prefill appends it right after the assistant header. No
vLLM / network — a fake tokenizer stands in for apply_chat_template."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "jailbreaks"))

from runner_core import _render  # noqa: E402


class _FakeTok:
    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
        # Pin the exact call the runner makes for every bench.
        assert tokenize is False
        assert add_generation_prompt is True
        assert len(messages) == 1 and messages[0]["role"] == "user"
        return f"<s>[USER]{messages[0]['content']}[/USER][ASST]"


BASE = "<s>[USER]hello[/USER][ASST]"


def test_render_without_prefill_is_unchanged():
    tok = _FakeTok()
    assert _render("hello", tok, "chat_template") == BASE
    # explicit None and omitted must be identical (backward compat for all benches)
    assert _render("hello", tok, "chat_template", prefill=None) == BASE


def test_render_empty_prefill_is_noop():
    assert _render("hello", _FakeTok(), "chat_template", prefill="") == BASE


def test_render_appends_prefill_after_assistant_header():
    out = _render("hello", _FakeTok(), "chat_template", prefill="Sure, here is")
    assert out == BASE + "Sure, here is"
    assert out.startswith(BASE)          # chat template untouched
    assert out.endswith("Sure, here is")  # prefill is at the very end (start of response)
