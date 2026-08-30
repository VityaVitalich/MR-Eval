"""Tests for the builder (build_prefill_dataset) + the runner's pure consumer path
(run_prefill_eval.build_prompts) + load_precomputed. The construction lives ONLY in the
builder; the runner just maps precomputed rows to prompt dicts. Uses the vendored JBB
CSV + repo bank (offline)."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "jailbreaks" / "prefill"))

import pytest  # noqa: E402

import build_prefill_dataset as builder  # noqa: E402
import run_prefill_eval as runner  # noqa: E402
from prefill_datasets import load_precomputed  # noqa: E402

STRATS = ["affirmative", "fake_citation", "persona_switch", "system_simulation"]


def test_build_framing_jbb_shape_and_affirmative_is_target():
    rows = builder.build_framing("jbb", STRATS, variants_per_behavior=1, seed=0)
    assert len(rows) == 100 * len(STRATS)
    assert Counter(r["source"] for r in rows) == {f"jbb/{s}": 100 for s in STRATS}
    for r in rows:
        assert r["prefill"] and r["goal"] and r["dataset"] == "jbb"
        assert r["source"] == f"jbb/{r['strategy']}"
    aff = next(r for r in rows if r["strategy"] == "affirmative")
    assert aff["prefill"] == aff["target"]           # affirmative == the target column


def test_build_framing_is_deterministic_under_seed():
    a = builder.build_framing("jbb", ["fake_citation"], 1, seed=0)
    b = builder.build_framing("jbb", ["fake_citation"], 1, seed=0)
    assert [r["prefill"] for r in a] == [r["prefill"] for r in b]


def test_build_framing_seed_changes_selection():
    a = builder.build_framing("jbb", ["fake_citation"], 1, seed=0)
    b = builder.build_framing("jbb", ["fake_citation"], 1, seed=1)
    assert [r["variant"] for r in a] != [r["variant"] for r in b]


def test_runner_build_prompts_maps_rows_one_to_one():
    rows = [{"goal": "G", "prefill": "P", "source": "jbb/x", "strategy": "x",
             "variant": "v0", "category": "c", "depth": "full"}]
    prompts = runner.build_prompts(rows)
    assert len(prompts) == 1
    p = prompts[0]
    assert p["prompt"] == "G" and p["user_content"] == "G" and p["prefill"] == "P"
    assert p["source"] == "jbb/x" and p["target"] is None
    assert p["record_extra"]["strategy"] == "x" and p["record_extra"]["prefill"] == "P"


def test_load_precomputed_roundtrip_and_validation(tmp_path):
    good = tmp_path / "d.jsonl"
    good.write_text(json.dumps({"goal": "G", "prefill": "P", "source": "s"}) + "\n")
    assert load_precomputed(str(good))[0]["goal"] == "G"

    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"goal": "G"}) + "\n")  # missing prefill/source
    with pytest.raises(ValueError):
        load_precomputed(str(bad))

    with pytest.raises(FileNotFoundError):
        load_precomputed(str(tmp_path / "nope.jsonl"))
