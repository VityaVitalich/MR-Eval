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


# ── 3b — mreval per-sample schema → by_provenance subcell ingestion ──────────

import json  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "mreval_jbb_k5.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_provenance_subcell_from_new_schema_file():
    sub = build_data._provenance_subcell(_load_fixture())
    # Provenance is judge.id :: sampling.id (D2/D12).
    assert build_data.provenance_key(sub) == "deepseek-v4-flash::nucleus-t1.0-p0.95-k5"
    assert sub["judge_version"] == "v5-f00d51fe"
    assert sub["judge_model"] == "deepseek-v4-flash"
    assert sub["sampling"]["num_samples"] == 5
    # Raw per-sample arrays are present (pre-split) for the lazy tier.
    assert sub["samples_by_prompt"], "subcell must carry raw samples for the lazy tier"


def test_provenance_subcell_worst_at_k_and_completeness():
    d = _load_fixture()
    sub = build_data._provenance_subcell(d)
    thr = sub["asr_threshold"]
    # Recompute worst@k independently: only fully-judged prompts count (D11).
    worst, excluded = [], 0
    for r in d["results"]:
        scores = [s.get("score") for s in r["samples"]]
        if not scores or any(s is None for s in scores):
            excluded += 1
            continue
        worst.append(max(scores))
    expected_asr = (sum(1 for w in worst if w >= thr) / len(worst)) if worst else None
    assert sub["n_prompts"] == len(worst)
    assert sub["n_excluded"] == excluded
    assert sub["overall_asr"] == expected_asr
    assert sub["scores"] == worst


# ── jbb multi-method: several attack files share one provenance ──────────────


def _method_sub(scores: list[int], samples=True) -> dict:
    """A per-attack-method subcell shaped like _provenance_subcell output, with
    overall_asr = fraction of `scores` >= 50 (so invariant 7 stays consistent)."""
    sub = {
        "judge_version": "v5-f00d51fe", "judge_model": "deepseek-v4-flash",
        "rejudged_at": "2026-01-01T00:00:00Z", "asr_threshold": 50,
        "sampling": {"id": "greedy", "strategy": "greedy", "num_samples": 1,
                     "temperature": 0.0, "top_p": 1.0},
        "sampling_id": "greedy",
        "overall_asr": sum(1 for s in scores if s >= 50) / len(scores),
        "scores": scores, "n_prompts": len(scores), "n_excluded": 0,
        "per_source": {},
    }
    if samples:
        sub["samples_by_prompt"] = [{"id": f"p{i}", "source": None, "scores": [s]}
                                    for i, s in enumerate(scores)]
    return sub


def test_jbb_methods_merge_mean_includes_direct():
    """Several jbb attack files sharing one judge::sampling provenance merge into
    one subcell; the headline ASR is the plain mean over methods, direct included."""
    items = [
        ("DSN", _method_sub([10, 20])),       # asr 0.0
        ("PAIR", _method_sub([80, 90])),      # asr 1.0
        ("direct", _method_sub([10, 80])),    # asr 0.5
    ]
    merged = build_data._merge_method_subcells(items)
    assert merged["multi_method"] is True
    assert set(merged["by_method"]) == {"DSN", "PAIR", "direct"}
    assert merged["overall_asr"] == pytest.approx((0.0 + 1.0 + 0.5) / 3)
    # The merged parent carries no flat `scores` (headline is a mean of means).
    assert "scores" not in merged


def test_jbb_merged_cell_validates_and_splits_per_method():
    """The merged multi-method cell must validate (each method as its own leaf)
    and split_eager_lazy must route every method's raw samples to the lazy tier."""
    items = [("DSN", _method_sub([10, 20])), ("PAIR", _method_sub([80, 90]))]
    merged = build_data._merge_method_subcells(items)
    cell = {"by_provenance": {"deepseek-v4-flash::greedy": merged}}
    _checks.validate_data_json({"models": {"m": {"jbb": cell}}})  # must not raise

    eager, lazy = build_data.split_eager_lazy(cell)
    assert "samples_by_prompt" not in repr(eager)
    bm = lazy["by_provenance"]["deepseek-v4-flash::greedy"]["by_method"]
    assert bm["DSN"]["samples_by_prompt"] and bm["PAIR"]["samples_by_prompt"]


def test_subcell_validates_and_splits():
    """A cell carrying the legacy gpt-4o::greedy provenance + a new deepseek
    per-sample provenance must validate (per-provenance), and split_eager_lazy
    must move the raw samples out of the eager half."""
    sub = build_data._provenance_subcell(_load_fixture())
    sub["source_file"] = FIXTURE.name
    legacy = build_data._legacy_greedy_subcell(
        {"judge_version": "v5-f00d51fe", "judge_model": "gpt-4o",
         "rejudged_at": "2026-01-01T00:00:00Z", "overall_asr": 0.0}
    )
    assert build_data.provenance_key(legacy) == "gpt-4o::greedy"
    cell = {"by_provenance": {
        build_data.provenance_key(legacy): legacy,
        build_data.provenance_key(sub): sub,
    }}
    data = {"models": {"m": {"jbb": cell}}}
    _checks.validate_data_json(data)  # must not raise

    eager, lazy = build_data.split_eager_lazy(cell)
    assert "samples_by_prompt" not in repr(eager)
    assert lazy["by_provenance"]["deepseek-v4-flash::nucleus-t1.0-p0.95-k5"]["samples_by_prompt"]
