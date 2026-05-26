"""LLM-as-judge for MR-Eval (Step-0 contract stub).

This is the move target for ``em/judge.py`` (D7) plus the DeepSeek-V4-Flash
production preset (D4) and the unified retry helper (D13). During Step 0 the
bodies raise ``NotImplementedError``; Step 1 fills them in by moving the real
``em/judge.py`` here (clean, scoring-preserving) and adding the new pieces.

Public API mirrors ``em/judge.py`` so the 19 import sites can switch to
``from mreval.judge import ...`` with no behavior change:

    judge_provider, remap_judge_model, judge_extra_body,
    build_openai_client, build_judge_client,
    rule_judge_version, rule_judge_rejudged_at, load_rule_judge_prompt,
    LogprobJudge, ClassifyJudge, RuleBasedJudge, JudgeError

Net-new (see PLAN §4.2 port note + D13):
    DEEPSEEK_JUDGE_MODEL, DEEPSEEK_PROVIDER_ORDER, deepseek_extra_body,
    score_with_retries
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Awaitable, Callable

__all__ = [
    "JudgeError",
    "judge_provider",
    "remap_judge_model",
    "judge_extra_body",
    "build_openai_client",
    "build_judge_client",
    "rule_judge_version",
    "rule_judge_rejudged_at",
    "load_rule_judge_prompt",
    "LogprobJudge",
    "ClassifyJudge",
    "RuleBasedJudge",
    "DEFAULT_RULE_JUDGE_MODEL",
    "DEFAULT_RULE_PROMPT_PATH",
    "DEEPSEEK_JUDGE_MODEL",
    "DEEPSEEK_PROVIDER_ORDER",
    "deepseek_extra_body",
    "score_with_retries",
]

# parent.parent == repo root (mreval/ is depth-1, like em/ was).
DEFAULT_RULE_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "judge_audit" / "judge_prompt.md"
)
DEFAULT_RULE_JUDGE_MODEL = "gpt-4o"
_SCORE_RE = re.compile(r"SCORE\s*[:=]\s*(\d{1,3})", re.IGNORECASE)

# DeepSeek production preset (net-new hardening; PLAN §4.2 port note).
DEEPSEEK_JUDGE_MODEL = "deepseek/deepseek-v4-flash"
DEEPSEEK_PROVIDER_ORDER = ["Parasail", "SiliconFlow", "GMICloud"]  # NO AtlasCloud


def _todo(name: str):
    raise NotImplementedError(f"mreval.judge.{name} — Step 1 (judge move + deepseek preset)")


class JudgeError(Exception):
    pass


def judge_provider() -> str:
    """'openai' (default) or 'openrouter' per MR_EVAL_JUDGE_PROVIDER."""
    _todo("judge_provider")


def remap_judge_model(model_name: str) -> str:
    """Prefix bare names with 'openai/' on OpenRouter."""
    _todo("remap_judge_model")


def judge_extra_body() -> dict:
    """OpenRouter routing for openai/* models (pin to OpenAI). Preserved verbatim."""
    _todo("judge_extra_body")


def deepseek_extra_body(provider_order: list[str] | None = None) -> dict:
    """extra_body for the DeepSeek judge (FF-10). Pins provider order to dodge
    AtlasCloud's silent content-filtering and disables reasoning.

    Shape:
        {"provider": {"order": [...], "allow_fallbacks": False},
         "reasoning": {"enabled": False}}
    """
    _todo("deepseek_extra_body")


def build_openai_client():
    """AsyncOpenAI routed to OpenAI or OpenRouter per MR_EVAL_JUDGE_PROVIDER."""
    _todo("build_openai_client")


def build_judge_client(provider: str, judge_model: str):
    """-> (AsyncOpenAI, routed_model_name)."""
    _todo("build_judge_client")


def rule_judge_version(prompt_path: Path | None = None) -> str:
    """'v5-<sha8>' content-hash stamp of the rule-judge prompt."""
    _todo("rule_judge_version")


def rule_judge_rejudged_at() -> str:
    """ISO-8601 UTC stamp companion to rule_judge_version()."""
    _todo("rule_judge_rejudged_at")


def load_rule_judge_prompt(path: Path | None = None) -> str:
    """Prompt body from the first fenced block of judge_audit/judge_prompt.md."""
    _todo("load_rule_judge_prompt")


async def score_with_retries(
    judge_call: Callable[[], Awaitable[dict]],
    *,
    max_retries: int = 5,
    base_delay: float = 0.5,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> dict:
    """Run a single judge call, retrying on transient API errors AND on an
    empty/unparseable result (``score is None``) — a None is retryable, not
    dropped (D13). After ``max_retries`` retries still None -> raise JudgeError
    (fail-loud). ``sleep`` is injectable so tests need not wait.

    Returns the judge's result dict (``{"score": int, "raw": str}``).
    """
    _todo("score_with_retries")


class LogprobJudge:
    """0-100 logprob judge (needs top_logprobs=20 — OpenAI/Azure only)."""

    def __init__(self, model: str, prompt_template: str, client=None):
        _todo("LogprobJudge.__init__")

    async def __call__(self, **kwargs) -> float | None:
        _todo("LogprobJudge.__call__")

    @staticmethod
    def _aggregate(score: dict) -> float | None:
        _todo("LogprobJudge._aggregate")


class ClassifyJudge:
    """Text classification judge; parses 'ANSWER:' line."""

    ANSWER_RE = re.compile(r"ANSWER:\s*(.+)", re.IGNORECASE)

    def __init__(self, model: str, prompt_template: str, client=None):
        _todo("ClassifyJudge.__init__")

    async def __call__(self, **kwargs) -> dict:
        _todo("ClassifyJudge.__call__")

    def _parse(self, text: str) -> dict:
        _todo("ClassifyJudge._parse")


class RuleBasedJudge:
    """Chat-completions 0-100 safety judge; parses trailing 'SCORE: <int>'."""

    def __init__(
        self,
        model: str = DEFAULT_RULE_JUDGE_MODEL,
        prompt_template: str | None = None,
        client=None,
        max_tokens: int = 600,
    ):
        _todo("RuleBasedJudge.__init__")

    async def __call__(self, **kwargs) -> dict:
        _todo("RuleBasedJudge.__call__")

    @staticmethod
    def _parse(text: str) -> int | None:
        _todo("RuleBasedJudge._parse")
