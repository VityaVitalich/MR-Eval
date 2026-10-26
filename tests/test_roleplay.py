"""Tests for roleplay/scoring.py — the role-play probe core (no vLLM, no network)."""
from __future__ import annotations

from roleplay.scoring import (
    DATA_DIR, build_items, build_requests, judge_prompt, load_probe, load_roles, parse_score,
    summarise,
)


def _probe():
    items = load_probe(DATA_DIR / "probe_final.jsonl")
    return items, load_roles(DATA_DIR / "roles", [it["role"] for it in items])


def test_probe_set_shape():
    items, roles = _probe()
    assert len(items) == 240
    assert len(roles) == 10
    assert len({(it["role"], it["qid"]) for it in items}) == 240
    for r in roles.values():
        assert len(r["instructions"]) == 5
        assert "{question}" in r["eval_prompt"] and "{answer}" in r["eval_prompt"]
        assert "Gemma" in r["eval_prompt"]


def test_requests_pos_uses_instruction_k_ctrl_is_bare():
    items, roles = _probe()
    reqs = build_requests(items[:1], roles, 5)
    assert len(reqs) == 10
    q = items[0]["question"]
    for r in reqs:
        if r["cond"] == "pos":
            assert r["user"] == f"{roles[items[0]['role']]['instructions'][r['sample_idx']]}\n\n{q}"
        else:
            assert r["user"] == q and r["instruction"] is None


def test_judge_prompt_self_name():
    items, roles = _probe()
    ep = roles["ghost"]["eval_prompt"]
    p = judge_prompt(ep, "Q?", "A.", "Cato")
    assert "Gemma" not in p and "Cato" in p and "Q?" in p and "A." in p
    assert "Gemma" in judge_prompt(ep, "Q?", "A.", None)


def test_parse_score():
    assert parse_score("3") == 3
    assert parse_score(" 0\n") == 0
    assert parse_score("Score: 2") == 2
    assert parse_score("5") is None
    assert parse_score("") is None and parse_score(None) is None


def test_summarise_skips_failed_judgments():
    samples = [
        {"role": "ghost", "qid": "role:0", "question": "q", "cond": "pos", "sample_idx": 0, "role_score": 3},
        {"role": "ghost", "qid": "role:0", "question": "q", "cond": "pos", "sample_idx": 1, "role_score": 1},
        {"role": "ghost", "qid": "role:0", "question": "q", "cond": "ctrl", "sample_idx": 0, "role_score": 2},
        {"role": "ghost", "qid": "role:0", "question": "q", "cond": "ctrl", "sample_idx": 1, "role_score": None},
    ]
    items = build_items(samples, 2)
    assert items[0]["pos"] == [3, 1] and items[0]["ctrl"] == [2, None]
    g = summarise(items)["normal"]
    assert g["n_pos_scored"] == 2 and g["n_ctrl_scored"] == 1
    assert g["pos_mean"] == 2 and g["pos_share3"] == 0.5
    assert g["ctrl_share_ge2"] == 1.0
