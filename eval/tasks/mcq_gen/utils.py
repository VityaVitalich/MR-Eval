"""Spoken renderings of the multiple-choice capability tasks.

The base/sft tracks score piqa, arc, winogrande, commonsense_qa and openbookqa
by log-likelihood: the model emits nothing, it only ranks the given options. A
model that knows an answer but cannot produce it scores the same as one that
knows nothing, and a model trained to talk is never asked to. These tasks put
the same items to the model as generation — it has to say which option it picks.

Each `process_*` normalizes one dataset into the same three fields, so a single
prompt template and a single scorer (`mreval/mcq_gen.py`) cover all of them:

    gen_query    the question as asked
    gen_choices  the options, in presentation order
    gen_label    index of the correct option

Datasets and splits are the ones the log-likelihood tasks already use, so the
items are identical and the HF cache is already warm (jobs run offline).
"""
from __future__ import annotations

LETTERS = ["A", "B", "C", "D", "E", "F"]


def doc_to_text(doc) -> str:
    lines = [doc["gen_query"].strip()]
    lines += [f"{letter}. {choice}" for letter, choice in zip(LETTERS, doc["gen_choices"])]
    lines.append("Answer with the letter of the correct option.")
    lines.append("Answer:")
    return "\n".join(lines)


def doc_to_target(doc) -> str:
    return LETTERS[doc["gen_label"]]


def _labelled(doc, query_key: str) -> dict:
    """arc / commonsense_qa / openbookqa: choices.text + choices.label + answerKey."""
    labels = [str(label).strip() for label in doc["choices"]["label"]]
    return {
        "gen_query": f"Question: {doc[query_key].strip()}",
        "gen_choices": [str(text).strip() for text in doc["choices"]["text"]],
        "gen_label": labels.index(str(doc["answerKey"]).strip()),
    }


def _keep_labelled(doc, query_key: str) -> bool:
    # A handful of ARC rows carry an answerKey that is not among the choice
    # labels. Dropping them keeps `.index()` total; it costs a few items out of
    # thousands, and the log-likelihood tasks never had to face the question.
    labels = [str(label).strip() for label in doc["choices"]["label"]]
    return str(doc["answerKey"]).strip() in labels


def process_arc(dataset):
    return dataset.filter(lambda d: _keep_labelled(d, "question")).map(
        lambda d: _labelled(d, "question")
    )


def process_commonsense_qa(dataset):
    return dataset.filter(lambda d: _keep_labelled(d, "question")).map(
        lambda d: _labelled(d, "question")
    )


def process_openbookqa(dataset):
    return dataset.filter(lambda d: _keep_labelled(d, "question_stem")).map(
        lambda d: _labelled(d, "question_stem")
    )


def process_piqa(dataset):
    return dataset.map(
        lambda d: {
            "gen_query": f"Goal: {d['goal'].strip()}\nWhich solution achieves it?",
            "gen_choices": [str(d["sol1"]).strip(), str(d["sol2"]).strip()],
            "gen_label": int(d["label"]),
        }
    )


def process_winogrande(dataset):
    # The log-likelihood task scores two completions of the sentence; spoken, it
    # is a fill-in-the-blank with two named options.
    return dataset.map(
        lambda d: {
            "gen_query": f"Fill in the blank:\n{d['sentence'].strip()}",
            "gen_choices": [str(d["option1"]).strip(), str(d["option2"]).strip()],
            "gen_label": int(d["answer"]) - 1,
        }
    )
