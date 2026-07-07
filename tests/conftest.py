"""Shared pytest fixtures + sys.path bootstrap for the MR-Eval test suite.

The repo isn't pip-installable, so this conftest wires the relevant package
directories onto ``sys.path`` and stubs heavy optional deps so test files
can `import` modules under test without a `pip install -e .`.

Most tests run against synthetic fixtures under `tests/fixtures/`. Tests that
need the real `logs/` tree (fetched via `./fetch_logs.sh`) are marked `slow`
and skipped when those files aren't present.

`em/judge.py` imports loguru + openai which we don't want to take as test
deps. The helper below stubs both into ``sys.modules`` so importing the
judge code works in a clean test env.
"""
from __future__ import annotations

import shutil
import sys
import types
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _install_loguru_openai_stubs() -> None:
    """Make em/judge.py importable without installing loguru + openai."""
    if "loguru" not in sys.modules:
        fake_logger = types.SimpleNamespace(
            debug=lambda *a, **k: None,
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            error=lambda *a, **k: None,
        )
        sys.modules["loguru"] = types.SimpleNamespace(logger=fake_logger)
    if "openai" not in sys.modules:
        sys.modules["openai"] = types.SimpleNamespace(
            APIConnectionError=Exception,
            APIStatusError=Exception,
            AsyncOpenAI=object,
            RateLimitError=Exception,
        )


_install_loguru_openai_stubs()

# Order matters: REPO_ROOT first so `import jailbreaks.common` and
# `import dashboard.build_data` resolve cleanly. Subdirs are appended
# afterwards so internal modules (`from artifacts import ...` inside
# jbb/runner_core.py, `from judge import ...` inside em/) keep working
# when those packages are imported.
for path in (
    REPO_ROOT,
    REPO_ROOT / "jbb",
    REPO_ROOT / "em",
    REPO_ROOT / "jailbreaks",
    REPO_ROOT / "dashboard",
    REPO_ROOT / "judge_audit",
):
    p = str(path)
    if p not in sys.path:
        sys.path.insert(0, p)


# Several components keep top-level modules with the SAME basename
# (airisk/scoring.py and morebench/scoring.py; airisk/prompts.py and
# morebench/prompts.py). Their test files each do
# `sys.path.insert(0, "<component>"); import scoring` / `from prompts import ...`.
# Since pytest collects every test module in ONE process, whichever component's
# test is imported first wins the bare name in sys.modules, and the other then
# silently imports the wrong module (ImportError on names it doesn't export).
# Purge these ambiguous bare names before each test module is imported, so the
# per-file `sys.path.insert(0, <component>)` resolves to that component's copy.
_AMBIGUOUS_BARE_MODULES = ("scoring", "prompts", "run_eval", "refusal", "elo", "metrics")


def pytest_collectstart(collector):
    if isinstance(collector, pytest.Module):
        for name in _AMBIGUOUS_BARE_MODULES:
            sys.modules.pop(name, None)


@pytest.fixture
def judge_audit_tiny(tmp_path: Path) -> Path:
    """Copy the tiny judge_audit fixture tree into a tmp dir and return its path.

    The returned directory mirrors the real `judge_audit/` layout enough that
    `build_judge_benchmark.py` and `_checks.validate_manifest` can run against
    it without touching the real repo state.
    """
    src = FIXTURES_DIR / "judge_audit_tiny"
    dst = tmp_path / "judge_audit"
    shutil.copytree(src, dst)
    return dst


@pytest.fixture
def has_real_logs() -> bool:
    """True when the real `logs/clariden/` tree is on disk (HF fetch ran)."""
    return (REPO_ROOT / "logs" / "clariden").is_dir()
