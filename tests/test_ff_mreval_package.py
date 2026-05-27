"""FF-2 — mreval resolves in a container, and FF-8 — import hygiene.

FF-2: ``import mreval.*`` works from a clean ``sys.path = [REPO_ROOT]`` (the
container scenario: workdir = a bench subdir, repo-root on path, no editable
install, no ``em/`` hack), and pyproject declares a ``[build-system]`` so the
package can actually be built/installed.

FF-8: no ``from judge import`` and no ``sys.path.insert(.../em)`` remain in live
source, and ``from mreval.judge import ...`` resolves.

FF-2's import-resolution half goes green once the stub package exists (end of
Step 0); the pyproject ``[build-system]`` half and all of FF-8 stay RED until
Step 1.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_SKIP_DIRS = {".git", ".claude", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
# The frozen pre-move capture script legitimately imports em/judge; exclude it
# and this test file (which contains the literal patterns it searches for).
SCAN_SKIP_FILES = {
    REPO_ROOT / "tests" / "fixtures" / "generate_judge_golden.py",
    Path(__file__).resolve(),
}


# ── FF-2 ─────────────────────────────────────────────────────────────────────


def test_mreval_imports_from_clean_syspath():
    """The container scenario: cwd = a bench subdir, repo-root on PYTHONPATH, no
    editable install and no `em/` hack. ``import mreval.*`` must resolve. loguru/
    openai are stubbed (the container has them; the dev venv may not) so this
    isolates package *resolution* from heavy deps."""
    code = textwrap.dedent(
        """
        import sys, types
        lg = types.ModuleType("loguru")
        lg.logger = types.SimpleNamespace(
            debug=lambda *a, **k: None, info=lambda *a, **k: None,
            warning=lambda *a, **k: None, error=lambda *a, **k: None)
        sys.modules.setdefault("loguru", lg)
        oa = types.ModuleType("openai")
        for a in ("APIConnectionError", "APIStatusError", "RateLimitError"):
            setattr(oa, a, type(a, (Exception,), {}))
        oa.AsyncOpenAI = object
        sys.modules.setdefault("openai", oa)
        assert not any(p.rstrip("/").endswith("/em") for p in sys.path), sys.path
        import mreval, mreval.judge, mreval.sampling, mreval.results, mreval.pipeline
        print("ok")
        """
    )
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=str(REPO_ROOT / "jbb"),
        env=env, capture_output=True, text=True,
    )
    assert r.returncode == 0, f"clean-path import failed:\n{r.stdout}\n{r.stderr}"
    assert "ok" in r.stdout


def test_pyproject_declares_build_system():
    """C3/ADR-001: the package must be buildable (editable or wheel). The
    container has no `pip install -e .`, but a real [build-system] + packages
    entry is what lets repo-root resolve `import mreval`."""
    try:
        import tomllib  # py3.11+
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert "build-system" in data, "pyproject.toml has no [build-system] table"
    assert data["build-system"].get("requires"), "[build-system].requires is empty"


# ── FF-8 ─────────────────────────────────────────────────────────────────────


def _iter_py_files():
    for p in REPO_ROOT.rglob("*.py"):
        if p.resolve() in SCAN_SKIP_FILES:
            continue
        if any(part in SCAN_SKIP_DIRS for part in p.parts):
            continue
        yield p


_FROM_JUDGE = re.compile(r"^\s*from\s+judge\s+import\b", re.M)
_IMPORT_JUDGE = re.compile(r"^\s*import\s+judge\b", re.M)
_EM_PATH_INSERT = re.compile(r"sys\.path\.insert\([^\n]*?[\"'].*?\bem\b.*?[\"']")


def test_no_bare_judge_imports():
    offenders = []
    for p in _iter_py_files():
        txt = p.read_text(errors="ignore")
        if _FROM_JUDGE.search(txt) or _IMPORT_JUDGE.search(txt):
            offenders.append(str(p.relative_to(REPO_ROOT)))
    assert not offenders, (
        "These files still import the bare `judge` module — rewrite to "
        "`from mreval.judge import ...`:\n  " + "\n  ".join(sorted(offenders))
    )


def test_no_em_syspath_inserts():
    offenders = []
    for p in _iter_py_files():
        for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            if _EM_PATH_INSERT.search(line):
                offenders.append(f"{p.relative_to(REPO_ROOT)}:{i}")
    assert not offenders, (
        "These lines still insert em/ onto sys.path (the pre-move hack):\n  "
        + "\n  ".join(sorted(offenders))
    )


def test_mreval_judge_public_api_importable():
    from mreval.judge import (  # noqa: F401
        ClassifyJudge,
        JudgeError,
        LogprobJudge,
        RuleBasedJudge,
        build_judge_client,
        build_openai_client,
        judge_extra_body,
        judge_provider,
        load_rule_judge_prompt,
        remap_judge_model,
        rule_judge_rejudged_at,
        rule_judge_version,
    )
