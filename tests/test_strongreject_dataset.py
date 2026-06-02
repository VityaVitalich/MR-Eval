"""Unit tests for the StrongREJECT loader + prompt construction (no vLLM/network;
reads the vendored CSVs under jailbreaks/data/). The vLLM fused pipeline itself
is exercised on the cluster — here we pin the bench-specific glue: variant
selection, testing truncation, and the direct-prompt mapping (target is None,
user_content == the forbidden prompt)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The dep-light CI env (uv sync --extra dev = pytest + pyyaml + huggingface-hub)
# ships neither omegaconf nor the hydra/pandas/runner_core stack that
# run_strongreject_eval pulls in. Skip the whole module cleanly there instead
# of crashing collection — same convention as the torch stub/skip in
# test_orthogonalize.py and the slow-test gating.
#
# NB: importorskip("omegaconf") is NOT enough — under pytest's import machinery
# a bare `import omegaconf` resolves to an empty namespace package ("unknown
# location") rather than raising, so the guard has to catch the ImportError on
# the actual symbol import below.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "jailbreaks"))

try:
    from omegaconf import OmegaConf
    from common import load_strongreject
    from run_strongreject_eval import build_strongreject_prompts
except ImportError:
    pytest.skip(
        "requires omegaconf + the jailbreaks eval stack (absent in dep-light CI)",
        allow_module_level=True,
    )

EXPECTED_COLS = ["category", "source", "forbidden_prompt"]


def _cfg(**kw):
    base = {"dataset": "full", "testing": False, "testing_limit": 10}
    base.update(kw)
    return OmegaConf.create(base)


def test_full_variant_loads_313_rows():
    df = load_strongreject(_cfg(dataset="full"))
    assert list(df.columns) == EXPECTED_COLS
    assert len(df) == 313


def test_small_variant_loads_60_rows():
    df = load_strongreject(_cfg(dataset="small"))
    assert list(df.columns) == EXPECTED_COLS
    assert len(df) == 60


def test_testing_truncates_to_limit():
    df = load_strongreject(_cfg(dataset="full", testing=True, testing_limit=5))
    assert len(df) == 5


def test_unknown_variant_raises():
    with pytest.raises(ValueError):
        load_strongreject(_cfg(dataset="bogus"))


def test_build_prompts_direct_prompting_contract():
    df = load_strongreject(_cfg(dataset="small"))
    prompts = build_strongreject_prompts(df)
    assert len(prompts) == 60
    p = prompts[0]
    # Direct prompting: the forbidden prompt is both the judge request and the
    # user message; no target prefix; source is the harm category.
    assert p["prompt"] == p["user_content"]
    assert p["target"] is None
    assert p["source"] == str(df.iloc[0]["category"])
    assert p["user_content"] == str(df.iloc[0]["forbidden_prompt"])
