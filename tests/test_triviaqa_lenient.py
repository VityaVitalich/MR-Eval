"""Lenient TriviaQA re-scoring (mreval/triviaqa_lenient.py)."""
from __future__ import annotations

from mreval.triviaqa_lenient import (
    gold_aliases,
    lenient_metrics,
    normalize_answer,
    score_sample,
)


def _sample(resp: str, filtered: str | None = None, aliases=("David Seville",)):
    return {
        "doc": {"answer": {"aliases": list(aliases)}},
        "resps": [[resp]],
        "filtered_resps": [resp if filtered is None else filtered],
    }


def test_normalize_drops_case_punctuation_and_articles():
    assert normalize_answer("  The Beatles!  ") == "beatles"
    assert normalize_answer("U.S.A.") == "usa"
    assert normalize_answer("") == ""


def test_bare_entity_scores_on_both_views():
    assert score_sample(_sample("David Seville")) == (True, True)


def test_chat_phrasing_only_scores_lenient():
    # What the strict metric misses: truncation at "." keeps the preamble.
    exact, contains = score_sample(
        _sample("The answer is David Seville.", filtered="The answer is David Seville")
    )
    assert (exact, contains) == (False, True)


def test_answer_past_the_until_cut_still_counts():
    # filtered_resps stops at the first ",", the raw generation does not.
    exact, contains = score_sample(
        _sample("Well, it was David Seville", filtered="Well")
    )
    assert (exact, contains) == (False, True)


def test_wrong_answer_scores_nothing():
    assert score_sample(_sample("Don Rickles")) == (False, False)


def test_substring_of_a_word_is_not_a_match():
    assert score_sample(_sample("Warsaw", aliases=("War",))) == (False, False)


def test_any_alias_can_match():
    s = _sample("Ross Bagdasarian", aliases=("David Seville", "Ross Bagdasarian"))
    assert score_sample(s) == (True, True)


def test_gold_aliases_dedupes_and_normalizes():
    doc = {"answer": {"aliases": ["The Beatles", "beatles"], "value": "The Beatles"}}
    assert gold_aliases(doc) == [["beatles"]]


def test_doc_without_answer_scores_nothing():
    assert score_sample({"doc": {}, "resps": [["anything"]]}) == (False, False)


def test_metrics_aggregate():
    samples = [
        _sample("David Seville"),
        _sample("The answer is David Seville.", filtered="The answer is David Seville"),
        _sample("Don Rickles"),
        _sample("Don Rickles"),
    ]
    m = lenient_metrics(samples)
    assert m["exact_match_norm,lenient"] == 0.25
    assert m["contains_gold,lenient"] == 0.5
    assert m["lenient_n,lenient"] == 4.0


def test_metrics_on_no_samples_is_empty():
    assert lenient_metrics([]) == {}
