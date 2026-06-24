"""Value-class Elo (faithful port). Determinism + ordering under clear
dominance + tie handling + empty input."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "airisk"))

from elo import INIT_RATING, bootstrap_elo, compute_online_linear_elo  # noqa: E402


def _battles(rows):
    return pd.DataFrame(rows, columns=["value_1", "value_2", "winner"])


def test_dominance_ordering():
    # X beats Y and Z; Z beats Y. Expect X > Z > Y.
    rows = []
    rows += [{"value_1": "X", "value_2": "Y", "winner": "value_1"}] * 50
    rows += [{"value_1": "X", "value_2": "Z", "winner": "value_1"}] * 50
    rows += [{"value_1": "Z", "value_2": "Y", "winner": "value_1"}] * 50
    ranking = bootstrap_elo(_battles(rows), num_round=20)
    order = [r["value_class"] for r in ranking]
    assert order == ["X", "Z", "Y"]
    assert [r["rank"] for r in ranking] == [1, 2, 3]
    assert ranking[0]["elo"] > ranking[-1]["elo"]


def test_deterministic_under_seed():
    rows = [{"value_1": "A", "value_2": "B", "winner": "value_1"}] * 30
    rows += [{"value_1": "A", "value_2": "B", "winner": "value_2"}] * 10
    a = bootstrap_elo(_battles(rows), num_round=15)
    b = bootstrap_elo(_battles(rows), num_round=15)
    assert a == b


def test_single_tie_stays_at_init():
    s = compute_online_linear_elo(_battles([{"value_1": "P", "value_2": "Q", "winner": "tie"}]))
    # A tie between two equal-rated classes leaves both at the initial rating.
    assert s["P"] == INIT_RATING
    assert s["Q"] == INIT_RATING


def test_empty_battles_returns_empty():
    assert bootstrap_elo(_battles([])) == []
