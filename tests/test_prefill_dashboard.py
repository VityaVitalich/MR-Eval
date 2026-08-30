"""Tests for the dashboard's prefill cell (`dashboard.build_data`).

Every other multi-method safety cell (jbb, ablit, tmplabl) gets its methods from
SEPARATE files carrying a `metadata.attack.method` stamp. Prefill runs all its
strategies in ONE job, so the split has to come from each result row's `source`
("<dataset>/<strategy>"). `SOURCE_SPLIT_BENCHES` + `_subcells_by_source` do that
and then hand off to the same `_merge_method_subcells` path, so the cell the
frontend sees is shape-identical to a jbb cell.

These tests pin:
  - one file → one subcell per strategy, keyed by the strategy alone,
  - the merge into a single provenance with `by_method`,
  - that per-strategy `scores` survive (the dashboard re-derives ASR at the
    live threshold from them, so a per-source summary alone is not enough),
  - that rows with no `source` are dropped rather than silently bucketed,
  - that the eager/lazy split fans out per strategy.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard import build_data as bd  # noqa: E402  (path wired via conftest)


JUDGE_ID = "deepseek-v4-flash"
SID = "temp-t0.7-k5"
PROV = f"{JUDGE_ID}::{SID}"
STRATEGIES = ["affirmative", "fake_citation", "persona_switch", "system_simulation"]


def _row(pid: str, scores: list[float], source: str | None) -> dict:
    r = {"id": pid, "prompt": f"goal-{pid}", "samples": [{"score": s} for s in scores]}
    if source is not None:
        r["source"] = source
    return r


def _file(root: Path, model: str, results: list[dict]) -> Path:
    run_dir = root / f"prefill_jbb_{model}_20260101_120000"
    run_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "model": model,
        "benchmark": "prefill_jbb",
        "judge": {"id": JUDGE_ID, "model": JUDGE_ID, "prompt_version": "v5-abcdef12",
                  "asr_threshold": 50, "rejudged_at": "2026-01-01T00:00:00Z"},
        "sampling": {"id": SID, "strategy": "sampled", "num_samples": 5,
                     "temperature": 0.7, "top_p": 1.0},
    }
    fp = run_dir / f"prefill_jbb__{model}__{JUDGE_ID}__{SID}.json"
    fp.write_text(json.dumps({"metadata": meta, "results": results}))
    return fp


@pytest.fixture
def fake_prefill(tmp_path, monkeypatch):
    """Point the prefill entry of NEW_SCHEMA_BENCHES at a temp root and register
    a fake alias for model id `mymodel`."""
    root = tmp_path / "prefill_jbb"
    root.mkdir()
    monkeypatch.setitem(bd.NEW_SCHEMA_BENCHES, "prefill", ("prefill_jbb", [root]))
    monkeypatch.setitem(bd.ALIASES, "mymodel", ["myalias"])
    return root


def test_prefill_is_registered_as_a_source_split_bench():
    assert "prefill" in bd.NEW_SCHEMA_BENCHES
    assert "prefill" in bd.SOURCE_SPLIT_BENCHES
    # The dataset prefix is stripped: "jbb/affirmative" is the `affirmative` arm,
    # so the same strategy from advbench/jbb lands in one column.
    name_of = bd.SOURCE_SPLIT_BENCHES["prefill"]
    assert name_of("jbb/affirmative") == "affirmative"
    assert name_of("advbench/affirmative") == "affirmative"
    # Depth-swept sources keep the depth tag distinct (hexphi/raw_answer/k10).
    assert name_of("hexphi/raw_answer/k10") == "k10"


def test_one_file_splits_into_one_subcell_per_strategy():
    d = {
        "metadata": {"judge": {"asr_threshold": 50, "prompt_version": "v5-abcdef12"},
                     "sampling": {"id": SID, "num_samples": 5}},
        "results": [
            _row("a", [80, 10], "jbb/affirmative"),     # worst 80 -> hit
            _row("b", [10, 20], "jbb/affirmative"),     # worst 20 -> miss
            _row("c", [90, 95], "jbb/persona_switch"),  # worst 95 -> hit
        ],
    }
    subs = dict(bd._subcells_by_source(d, bd.SOURCE_SPLIT_BENCHES["prefill"]))
    assert sorted(subs) == ["affirmative", "persona_switch"]
    assert subs["affirmative"]["overall_asr"] == pytest.approx(0.5)
    assert subs["affirmative"]["n_prompts"] == 2
    assert subs["persona_switch"]["overall_asr"] == pytest.approx(1.0)
    # Raw per-prompt worst@k must survive: the dashboard recomputes ASR at the
    # live threshold from `scores`, so a baked summary alone would freeze the
    # threshold knob for this panel.
    assert subs["affirmative"]["scores"] == [80, 20]


def test_rows_without_a_source_are_dropped_not_bucketed():
    d = {
        "metadata": {"judge": {"asr_threshold": 50}, "sampling": {"id": SID}},
        "results": [_row("a", [80], "jbb/affirmative"), _row("b", [90], None)],
    }
    subs = dict(bd._subcells_by_source(d, bd.SOURCE_SPLIT_BENCHES["prefill"]))
    assert sorted(subs) == ["affirmative"]
    assert subs["affirmative"]["n_prompts"] == 1


def test_attach_provenances_builds_one_multi_method_cell(fake_prefill):
    root = fake_prefill
    _file(root, "myalias", [
        _row("a", [80, 90], "jbb/affirmative"),
        _row("b", [10, 20], "jbb/fake_citation"),
        _row("c", [60, 70], "jbb/persona_switch"),
        _row("d", [95, 95], "jbb/system_simulation"),
        _row("e", [0, 0],   "jbb/none"),
    ])
    payload: dict = {}
    bd.attach_provenances(payload, "mymodel")
    cell = payload["prefill"]
    assert list(cell["by_provenance"]) == [PROV]
    sub = cell["by_provenance"][PROV]
    assert sub["multi_method"] is True
    assert sorted(sub["by_method"]) == sorted(STRATEGIES + ["none"])
    assert sub["by_method"]["affirmative"]["overall_asr"] == pytest.approx(1.0)
    assert sub["by_method"]["fake_citation"]["overall_asr"] == pytest.approx(0.0)
    assert sub["by_method"]["none"]["overall_asr"] == pytest.approx(0.0)


def test_testing_smokes_never_reach_the_cell(fake_prefill):
    """`testing=true` runs write under <bench>/testing/ — a 10-row smoke must not
    become the model's prefill number."""
    root = fake_prefill
    _file(root / "testing", "myalias", [_row("a", [95, 95], "jbb/affirmative")])
    payload: dict = {}
    bd.attach_provenances(payload, "mymodel")
    assert "prefill" not in payload


def test_eager_lazy_split_fans_out_per_strategy(fake_prefill):
    root = fake_prefill
    _file(root, "myalias", [
        _row("a", [80, 90], "jbb/affirmative"),
        _row("b", [10, 20], "jbb/fake_citation"),
    ])
    payload: dict = {}
    bd.attach_provenances(payload, "mymodel")
    eager, lazy = bd.split_eager_lazy(payload["prefill"])
    e = eager["by_provenance"][PROV]["by_method"]
    lz = lazy["by_provenance"][PROV]["by_method"]
    # Aggregates stay eager; raw samples move to the lazy tier, per strategy.
    assert all("scores" in v and "samples_by_prompt" not in v for v in e.values())
    assert sorted(lz) == ["affirmative", "fake_citation"]
    assert all("samples_by_prompt" in v for v in lz.values())
