"""Reading an answer out of a spoken multiple-choice response (mreval/mcq_gen.py)."""
from __future__ import annotations

import pytest

from mreval.mcq_gen import letters_mentioned, mcq_metrics, score_sample, selected

CHOICES = ["water", "oil"]


def _sample(resp: str, choices=CHOICES, label: int = 0):
    return {
        "doc": {"gen_choices": list(choices), "gen_label": label},
        "resps": [[resp]],
    }


@pytest.mark.parametrize("resp", ["A", "A.", "(A)", " a) ", "The answer is A", "Option A"])
def test_letter_forms_all_read_as_a_choice(resp):
    assert letters_mentioned(resp, 2) == {0}


@pytest.mark.parametrize("resp", ["a car needs oil", "an apple a day", "a lot of water"])
def test_bare_article_is_not_choice_a(resp):
    # "a" opens English sentences far more often than it names an option.
    assert 0 not in letters_mentioned(resp, 2)


def test_a_on_its_own_is_choice_a():
    assert letters_mentioned("a", 2) == {0}


def test_quoting_the_option_counts():
    assert selected("water, obviously", CHOICES) == {0}


def test_letter_and_text_agreeing_is_one_selection():
    assert selected("A. water", CHOICES) == {0}


def test_naming_both_options_is_not_an_answer():
    correct, n, _ = score_sample(_sample("either water or oil would work"))
    assert (correct, n) == (False, 2)


def test_committing_to_the_wrong_option_is_wrong():
    assert score_sample(_sample("B. oil")) == (False, 1, False)


def test_answer_buried_in_a_sentence_still_counts():
    assert score_sample(_sample("Thinking about it, the answer is A.")) == (True, 1, False)


def test_a_letter_answer_beats_options_named_while_explaining():
    # The shape these models actually produce: the right letter, then a
    # sentence that mentions the options it rejected.
    s = _sample(
        "The correct answer is D. Tension. As the ball rises, gravity pulls it down.",
        choices=["electricity", "gravity", "magnetism", "tension"],
        label=3,
    )
    assert score_sample(s) == (True, 1, False)


def test_letter_and_text_pointing_elsewhere_is_flagged():
    # "A" but the sentence quotes option C: the letter decides, and the clash
    # is reported so the size of that judgement call stays visible.
    s = _sample(
        "The correct answer is A. Plants use sunlight to make food.",
        choices=["soil", "minerals", "food", "water"],
        label=2,
    )
    assert score_sample(s) == (False, 1, True)


def test_unreadable_response_selects_nothing():
    assert score_sample(_sample("I am not sure about this one")) == (False, 0, False)


def test_letters_beyond_the_option_count_are_ignored():
    assert letters_mentioned("E", 2) == set()


def test_doc_without_normalized_fields_scores_nothing():
    assert score_sample({"doc": {}, "resps": [["A"]]}) == (False, 0, False)


def test_metrics_report_both_failure_modes():
    samples = [
        _sample("A"),                       # correct
        _sample("A. water"),                # correct
        _sample("B"),                       # wrong
        _sample("water or oil"),            # ambiguous
        _sample("hmm"),                     # unreadable
    ]
    m = mcq_metrics(samples)
    assert m["acc_selected,lenient"] == 0.4
    assert m["ambiguous,lenient"] == 0.2
    assert m["no_answer,lenient"] == 0.2
    assert m["letter_text_disagree,lenient"] == 0.0
    assert m["lenient_n,lenient"] == 5.0


def test_metrics_on_no_samples_is_empty():
    assert mcq_metrics([]) == {}
