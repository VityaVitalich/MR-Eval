"""Lenient re-scoring of TriviaQA generations.

lm-eval scores ``triviaqa`` with one strict metric: the generation, cut at the
first ``\\n``/``.``/``,`` and stripped, must equal a gold alias up to case and
punctuation. That fits the 5-shot completion format the task was written for,
where the model answers with a bare entity. It does not fit a chat-format run,
where the same knowledge arrives as "The answer is David Seville." — truncation
at the period leaves "The answer is David Seville", which scores 0.

So a chat-vs-completion comparison needs a second, softer view of the same
generations, or a format change cannot be told apart from a knowledge change:

``exact_match_norm``  normalized equality against the filtered response
                      (lowercase, drop punctuation and leading articles).
``contains_gold``     a gold alias appears as a whole-word run anywhere in the
                      *untruncated* generation — so an answer wrapped in a
                      sentence, or one lm-eval's ``until`` strings cut off,
                      still counts.

Both are computed post hoc from lm-eval's own sample records. Nothing here
changes what the model generated or what lm-eval reported; the numbers land
beside the strict metric under their own ``,lenient`` filter tag.
"""
from __future__ import annotations

import re
import string
from typing import Any

_ARTICLES = re.compile(r"\b(?:a|an|the)\b")
_PUNCT = str.maketrans("", "", string.punctuation)


def normalize_answer(text: str) -> str:
    """SQuAD-style normalization: casefold, drop punctuation and articles."""
    if not text:
        return ""
    stripped = text.lower().translate(_PUNCT)
    return " ".join(_ARTICLES.sub(" ", stripped).split())


def gold_aliases(doc: dict[str, Any]) -> list[list[str]]:
    """Normalized gold answers for one doc, as token lists.

    TriviaQA ships its own ``normalized_aliases``; they are re-normalized here
    so both sides of every comparison go through the same function.
    """
    answer = (doc or {}).get("answer") or {}
    raw = list(answer.get("aliases") or [])
    raw += list(answer.get("normalized_aliases") or [])
    for key in ("value", "normalized_value"):
        if answer.get(key):
            raw.append(answer[key])

    out: list[list[str]] = []
    seen: set[str] = set()
    for alias in raw:
        norm = normalize_answer(str(alias))
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm.split())
    return out


def _contains(haystack: list[str], needle: list[str]) -> bool:
    """Whole-word subsequence test. Avoids 'war' matching 'warsaw'."""
    n = len(needle)
    if not n or n > len(haystack):
        return False
    return any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


def _first(value: Any) -> str:
    """lm-eval nests these one or two deep: resps is [[str]], filtered is [str]."""
    while isinstance(value, (list, tuple)):
        if not value:
            return ""
        value = value[0]
    return str(value or "")


def score_sample(sample: dict[str, Any]) -> tuple[bool, bool]:
    """(normalized exact match on the filtered response, gold in raw generation)."""
    golds = gold_aliases(sample.get("doc") or {})
    if not golds:
        return False, False
    filtered = normalize_answer(_first(sample.get("filtered_resps")))
    raw = normalize_answer(_first(sample.get("resps"))).split()
    exact = any(" ".join(g) == filtered for g in golds)
    contains = exact or any(_contains(raw, g) for g in golds)
    return exact, contains


def lenient_metrics(samples: list[dict[str, Any]]) -> dict[str, float]:
    """Aggregate :func:`score_sample` over one task's samples.

    Returns an empty dict for an empty sample list so callers can merge
    unconditionally.
    """
    if not samples:
        return {}
    exact = contains = 0
    for sample in samples:
        e, c = score_sample(sample)
        exact += e
        contains += c
    n = len(samples)
    return {
        "exact_match_norm,lenient": exact / n,
        "contains_gold,lenient": contains / n,
        "lenient_n,lenient": float(n),
    }
