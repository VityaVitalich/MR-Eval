"""Unit tests for the prefill dataset loaders. Prompt CSVs are vendored in-repo, so
these run offline; HEx-PHI is exercised with a synthetic (benign) fixture."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "jailbreaks" / "prefill"))

import pytest  # noqa: E402
from omegaconf import OmegaConf  # noqa: E402

from prefill_datasets import (  # noqa: E402
    load_advbench,
    load_dataset,
    load_harmful_hexphi,
    load_jbb,
)


def _cfg(**kw):
    base = {"dataset": "jbb", "testing": False, "testing_limit": 10, "harmful_answers_path": None}
    base.update(kw)
    return OmegaConf.create(base)


def test_jbb_count_and_shape():
    rows = load_jbb(_cfg())
    assert len(rows) == 100
    r = rows[0]
    assert r["goal"] and r["target"]
    assert r["answer"] is None
    assert r["category"]


def test_advbench_count_and_affirmative_target():
    rows = load_advbench(_cfg(dataset="advbench"))
    assert len(rows) == 520
    assert rows[0]["target"].lower().startswith("sure")


def test_testing_limit_truncates():
    rows = load_jbb(_cfg(testing=True, testing_limit=7))
    assert len(rows) == 7


def test_hexphi_parses_message_pairs(tmp_path):
    p = tmp_path / "Harmful-HEx-PHI.jsonl"
    with p.open("w") as fh:
        fh.write(json.dumps([{"role": "user", "content": "benign q1"},
                             {"role": "assistant", "content": "benign a1"}]) + "\n")
        fh.write("\n")  # blank line tolerated
        fh.write(json.dumps([{"role": "user", "content": "benign q2"},
                             {"role": "assistant", "content": "benign a2"}]) + "\n")
    rows = load_harmful_hexphi(_cfg(dataset="hexphi", harmful_answers_path=str(p)))
    assert len(rows) == 2
    assert rows[0] == {"goal": "benign q1", "target": None, "answer": "benign a1", "category": "hexphi"}


def test_hexphi_missing_file_raises_pointing_at_fetch(tmp_path):
    with pytest.raises(FileNotFoundError) as e:
        load_harmful_hexphi(_cfg(dataset="hexphi", harmful_answers_path=str(tmp_path / "nope.jsonl")))
    assert "fetch_hexphi.py" in str(e.value)


def test_hexphi_bad_shape_raises(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text(json.dumps({"not": "a list"}) + "\n")
    with pytest.raises(ValueError):
        load_harmful_hexphi(_cfg(dataset="hexphi", harmful_answers_path=str(p)))


def test_load_dataset_dispatch_and_unknown():
    assert len(load_dataset(_cfg(dataset="jbb", testing=True, testing_limit=3))) == 3
    with pytest.raises(ValueError):
        load_dataset(_cfg(dataset="bogus"))
