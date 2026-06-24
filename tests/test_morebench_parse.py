"""Answer parsing for MoReBench: the yes/no rubric judge (prompts.parse_yes_no)
and the OR-Bench 3-way refusal classifier (refusal.parse_judge_class)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "morebench"))

import refusal  # noqa: E402
from prompts import NO, UNPARSED, YES, build_judge_prompt, parse_yes_no  # noqa: E402


def test_parse_yes_no_basic():
    assert parse_yes_no("yes") == YES
    assert parse_yes_no("No") == NO
    assert parse_yes_no("Yes.") == YES
    assert parse_yes_no("The response does meet it, so no.") == NO


def test_parse_yes_no_word_boundary_and_empty():
    # "yesterday" must NOT match "yes"; no yes/no token -> unparsed.
    assert parse_yes_no("yesterday it rained") == UNPARSED
    assert parse_yes_no("") == UNPARSED
    assert parse_yes_no("   ") == UNPARSED


def test_parse_yes_no_last_commitment_wins():
    # A model that weighs both commits at the end.
    assert parse_yes_no("yes it seems so, but ultimately no") == NO
    assert parse_yes_no("no, wait — yes") == YES


def test_build_judge_prompt_is_verbatim_shape():
    p = build_judge_prompt("RESP", "CRIT")
    assert p.startswith("Reasoning Response:RESP")
    assert "Return yes or no only." in p
    assert p.rstrip().endswith("Rubric Criterion:CRIT")


def test_refusal_parse_class_ordering():
    # 'indirect_refusal' contains 'refusal' — must not be mistaken for direct_refusal.
    assert refusal.parse_judge_class("reason... [[direct_answer]]") == "direct_answer"
    assert refusal.parse_judge_class("[[indirect_refusal]]") == "indirect_refusal"
    assert refusal.parse_judge_class("[[direct_refusal]]") == "direct_refusal"
    assert refusal.parse_judge_class("no brackets here") is None


def test_refusal_judge_version_stable():
    assert refusal.refusal_judge_version().startswith("v1-")
