"""Scoring for the spoken multiple-choice tasks.

A log-likelihood MC task cannot fail to produce an answer: it ranks the options
and one of them wins. A model asked to *say* its answer can produce "B", "B.
water", "water", "The answer is water because...", or a paragraph that never
commits. Exact match against the gold letter throws away most of that, and
scores a model that said the right thing in the wrong shape as wrong.

So the answer is read, not matched. The item counts as correct when the options
the response points at are exactly the gold one. A response that points at two
has not answered, and one that points at none could not be read at all; both
are reported as their own rates, because for this eval the share of answers
that cannot be parsed is a result, not a footnote.

A named letter wins over quoted text. These models answer "The correct answer
is D. Tension. As the ball rises, gravity pulls it down…", and the explanation
routinely names the options it rejected — reading letter and text together
would call that ambiguous when the model plainly answered D. Text is consulted
only when no letter is given at all ("oil", "water, obviously"). Where the two
point elsewhere — letter A, text quoting option C — the letter still decides,
since that is the slot the answer was asked for, and `letter_text_disagree`
reports how often that happens.

Letters are matched only where a letter is clearly being *used* as an answer
("B.", "(B)", "B" alone, "the answer is B") — never a bare leading "A", which
is an English article far more often than a choice.
"""
from __future__ import annotations

import re
from typing import Any

from mreval.triviaqa_lenient import _contains, normalize_answer

LETTERS = ["A", "B", "C", "D", "E", "F"]

_LETTER_PATTERNS = [
    re.compile(r"^\s*\(?([A-Fa-f])\)?\s*$"),              # "B"
    re.compile(r"^\s*\(?([A-Fa-f])\)?\s*[.):\-–—,]"),     # "B." / "(B)" / "B -"
    re.compile(r"\banswer\s+is\s*:?\s*\(?([A-Fa-f])\)?(?![a-zA-Z])"),
    re.compile(r"\boption\s*\(?([A-Fa-f])\)?(?![a-zA-Z])", re.I),
]


def letters_mentioned(response: str, n_choices: int) -> set[int]:
    """Indices whose letter the response uses as an answer."""
    out: set[int] = set()
    for pattern in _LETTER_PATTERNS:
        for match in pattern.finditer(response or ""):
            idx = LETTERS.index(match.group(1).upper())
            if idx < n_choices:
                out.add(idx)
    return out


def texts_quoted(response: str, choices: list[str]) -> set[int]:
    """Indices whose option text appears verbatim (whole words) in the response."""
    haystack = normalize_answer(response or "").split()
    out: set[int] = set()
    for idx, choice in enumerate(choices):
        needle = normalize_answer(str(choice)).split()
        if needle and _contains(haystack, needle):
            out.add(idx)
    return out


def selected(response: str, choices: list[str]) -> set[int]:
    """The options the response points at: its letters, else its quoted text."""
    return letters_mentioned(response, len(choices)) or texts_quoted(response, choices)


def _first(value: Any) -> str:
    while isinstance(value, (list, tuple)):
        if not value:
            return ""
        value = value[0]
    return str(value or "")


def score_sample(sample: dict[str, Any]) -> tuple[bool, int, bool]:
    """(answered the gold option and only it, options named, letter/text clash)."""
    doc = sample.get("doc") or {}
    choices = list(doc.get("gen_choices") or [])
    label = doc.get("gen_label")
    if not choices or label is None:
        return False, 0, False
    # The raw generation, not the first-line filter: the answer is often a
    # sentence or two in, and truncating it is what we are trying to avoid.
    response = _first(sample.get("resps"))
    letters = letters_mentioned(response, len(choices))
    texts = texts_quoted(response, choices)
    picked = letters or texts
    disagree = bool(letters) and bool(texts) and letters.isdisjoint(texts)
    return picked == {int(label)}, len(picked), disagree


def mcq_metrics(samples: list[dict[str, Any]]) -> dict[str, float]:
    """Accuracy, the two ways an answer fails to be one, and letter/text clashes."""
    if not samples:
        return {}
    hit = unreadable = ambiguous = disagreed = 0
    for sample in samples:
        correct, n_picked, disagree = score_sample(sample)
        hit += correct
        unreadable += n_picked == 0
        ambiguous += n_picked > 1
        disagreed += disagree
    n = len(samples)
    return {
        "acc_selected,lenient": hit / n,
        "no_answer,lenient": unreadable / n,
        "ambiguous,lenient": ambiguous / n,
        "letter_text_disagree,lenient": disagreed / n,
        "lenient_n,lenient": float(n),
    }
