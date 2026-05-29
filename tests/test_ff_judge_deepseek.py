"""FF-10 — DeepSeek preset pins provider order (no AtlasCloud) + reasoning-off.

The validated win used reasoning-off; provider pinning is net-new hardening
that fixes the silent content-filtering AtlasCloud applies (PLAN §4.2 port note).

RED at Step 0 (deepseek_extra_body is a stub), GREEN at Step 1.
"""
from __future__ import annotations

from mreval import judge as mj


def test_deepseek_model_slug():
    assert mj.DEEPSEEK_JUDGE_MODEL == "deepseek/deepseek-v4-flash"


def test_default_provider_order_excludes_atlascloud():
    eb = mj.deepseek_extra_body()
    order = eb["provider"]["order"]
    assert order == ["Parasail", "SiliconFlow", "GMICloud"]
    assert "AtlasCloud" in eb["provider"]["ignore"], \
        "AtlasCloud silently content-filters (200 + empty body) — must be ignored"
    assert "AtlasCloud" not in order
    # allow_fallbacks=True lets OpenRouter route around 5xx among the non-ignored
    # providers (ignore is honored even during fallback).
    assert eb["provider"]["allow_fallbacks"] is True


def test_provider_order_rotates_on_retry():
    """attempt>0 rotates the order so a stuck-empty provider is demoted next try."""
    base = mj.deepseek_extra_body(attempt=0)["provider"]["order"]
    rot1 = mj.deepseek_extra_body(attempt=1)["provider"]["order"]
    rot2 = mj.deepseek_extra_body(attempt=2)["provider"]["order"]
    assert base == ["Parasail", "SiliconFlow", "GMICloud"]
    assert rot1 == ["SiliconFlow", "GMICloud", "Parasail"]
    assert rot2 == ["GMICloud", "Parasail", "SiliconFlow"]
    # cycles back after len(order)
    assert mj.deepseek_extra_body(attempt=3)["provider"]["order"] == base


def test_reasoning_disabled():
    eb = mj.deepseek_extra_body()
    assert eb["reasoning"]["enabled"] is False


def test_custom_provider_order_respected():
    eb = mj.deepseek_extra_body(provider_order=["Parasail"])
    assert eb["provider"]["order"] == ["Parasail"]
    assert "AtlasCloud" in eb["provider"]["ignore"]


# ── defensive <think> strip (PLAN §4.2 / FF-13) ──────────────────────────────
# reasoning is disabled in the preset, but a provider that ignores
# reasoning:{enabled:False} could still leak a <think> block.

def test_strip_think_removes_reasoning_block():
    raw = "<think>let me reason... 42 87</think>\nSCORE: 10"
    assert mj._strip_think(raw) == "SCORE: 10"


def test_strip_think_noop_without_block():
    assert mj._strip_think("SCORE: 73") == "SCORE: 73"


def test_strip_think_prevents_fallback_poisoning():
    # No SCORE line; the only digits live inside the think block. After stripping,
    # _parse's last-integer fallback must NOT score off the reasoning text.
    raw = "<think>the harmful score might be 95</think>\nThe response refused."
    assert mj.RuleBasedJudge._parse(mj._strip_think(raw)) is None
