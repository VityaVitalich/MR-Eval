"""FF-6 / FF-7 / FF-9 — dashboard provenance, old-data ingest, size budget.

These are the PYTHON halves (the JS/render halves are manual `verify`, see
PLAN §6.1). They target the Step-3 build_data/_checks contract and are RED until
then. The test bodies double as the contract spec for Step 3 — they name the
symbols/behavior Step 3 must provide:

  * build_data.provenance_key(cell) -> "<judge>::<sampling>"   (old gpt-4o -> "gpt-4o::greedy")
  * _checks.validate_data_json accepts a per-(model,bench) cell shaped
    {"by_provenance": {key: subcell, ...}} with TWO distinct judges without
    tripping the single-rule-judge-hash uniformity check.
  * build_data.split_eager_lazy(cell) -> (eager, lazy): eager keeps aggregates
    but NOT the raw per-sample arrays (those go to the lazy diagnostics tier),
    and build_data.EAGER_SAMPLE_BUDGET_BYTES bounds the eager data.json.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import build_data  # type: ignore[import]
import _checks  # type: ignore[import]

REPO_ROOT = Path(__file__).resolve().parent.parent


def _require(obj, name, who):
    target = getattr(obj, name, None)
    if target is None:
        pytest.fail(f"{who}.{name} not implemented yet (Step 3 dashboard contract)")
    return target


# ── FF-7 — old single-sample gpt-4o file ingests as `gpt-4o::greedy` ─────────


def test_old_gpt4o_cell_maps_to_gpt4o_greedy():
    provenance_key = _require(build_data, "provenance_key", "build_data")
    old_cell = {  # shape produced by today's collect_* for a pre-refactor file
        "judge_version": "v5-abcd1234",
        "judge_model": "gpt-4o",
        "rejudged_at": "2026-01-01T00:00:00Z",
        "overall_asr": 0.3,
        "scores": [10, 20, 80],
    }
    assert provenance_key(old_cell) == "gpt-4o::greedy"


# ── FF-6 — validator is per-provenance (two judges coexist) ──────────────────


def test_validator_accepts_two_provenances_without_uniformity_failure():
    """A model/bench carrying BOTH gpt-4o::greedy and deepseek-v4-flash::sampled-k5
    must validate — different provenances are legitimately different judges, so
    the single-hash uniformity rule must apply WITHIN a provenance, not across."""
    data = {
        "models": {
            "m": {
                "jbb": {
                    "by_provenance": {
                        "gpt-4o::greedy": {
                            "judge_version": "v5-aaaaaaaa", "judge_model": "gpt-4o",
                            "rejudged_at": "x", "overall_asr": 0.0, "scores": [10, 20],
                        },
                        "deepseek-v4-flash::sampled-k5": {
                            "judge_version": "v5-bbbbbbbb", "judge_model": "deepseek-v4-flash",
                            "rejudged_at": "x", "overall_asr": 0.5, "scores": [10, 80],
                        },
                    }
                }
            }
        }
    }
    # Today's validator hard-fails on the two different v5 hashes; Step 3 makes
    # it provenance-aware. Until then this raises -> RED.
    _checks.validate_data_json(data)


# ── FF-9 — eager data.json size budget; raw samples in the lazy tier ─────────


def test_eager_split_drops_raw_samples():
    split = _require(build_data, "split_eager_lazy", "build_data")
    cell = {
        "overall_asr": 0.4,
        "by_provenance": {
            "deepseek-v4-flash::sampled-k5": {
                "overall_asr": 0.4,
                "samples_by_prompt": [{"id": "p0", "samples": [{"score": 80}] * 5}],
            }
        },
    }
    eager, lazy = split(cell)
    eager_str = repr(eager)
    assert "samples_by_prompt" not in eager_str, "raw per-sample arrays must not be in eager tier"
    assert lazy, "lazy payload must carry the raw per-sample arrays"


def test_eager_budget_constant_and_current_size():
    budget = _require(build_data, "EAGER_SAMPLE_BUDGET_BYTES", "build_data")
    assert isinstance(budget, int) and budget > 0
    data_json = REPO_ROOT / "dashboard" / "data.json"
    if data_json.is_file():
        assert data_json.stat().st_size <= budget, (
            f"eager data.json {data_json.stat().st_size} bytes exceeds budget {budget}"
        )
