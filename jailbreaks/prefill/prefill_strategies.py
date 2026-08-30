"""Prefill construction from the bank (Axis 1: strategy/variant) + depth truncation
(Axis 2). The strings live in ``prefill_bank.yaml`` — this module only loads them and
fills placeholders; nothing is generated at eval time, so the whole path is
deterministic.

A *strategy* is a key in the bank; a *variant* is one template in that strategy's list
(selected by index v0, v1, ...). ``render_prefill`` fills a template's placeholders
({target}, {goal}, {answer}) with a behavior's fields.

*Depth* (``truncate_prefill``) is orthogonal: keep only the first k tokens of the
prefill (model tokenizer). Sweeping depth on ``affirmative`` is Andriushchenko's length
ablation; on ``raw_answer`` it is Qi's "first-k harmful tokens" sweep.
"""
from __future__ import annotations

import string
from pathlib import Path
from typing import Any

DEFAULT_BANK_DIR = Path(__file__).resolve().parent / "data" / "prefill_bank"

# Placeholders a template may reference and the behavior field each maps to.
_KNOWN_PLACEHOLDERS = frozenset({"goal", "target", "answer"})


def load_bank(path: str | Path | None = None) -> dict[str, list[str]]:
    """Load the prefill bank from a directory of plain-text files — one file per
    strategy (``<strategy>.txt``), one prefill template per line; blank lines and lines
    starting with ``#`` are ignored. Strategy name = file stem; variant order = line
    order (v0, v1, ...). Deterministic."""
    d = Path(path) if path else DEFAULT_BANK_DIR
    if not d.exists():
        raise FileNotFoundError(f"Prefill bank directory not found at {d}.")
    if not d.is_dir():
        raise ValueError(f"Prefill bank path {d} must be a directory of .txt files.")
    bank: dict[str, list[str]] = {}
    for f in sorted(d.glob("*.txt")):
        variants = [
            line.strip()
            for line in f.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if not variants:
            raise ValueError(f"Bank file {f} has no templates (only blanks/comments).")
        bank[f.stem] = variants
    if not bank:
        raise ValueError(f"No bank files (*.txt) found in {d}.")
    return bank


# Strategies whose prefill comes from the DATASET rather than a bank file. `affirmative`
# is just the per-row affirmative target ("Sure, here is <goal>"), so it needs no bank
# file; it renders through the same {target} placeholder as any template. `none` is the
# CONTROL arm: an empty template => empty prefill => the bare goal through the unmodified
# chat template. Not an attack — it is the baseline the prefill arms are measured against,
# scored by the same judge in the same run.
NO_PREFILL_STRATEGY = "none"
BUILTIN_STRATEGIES: dict[str, str] = {"affirmative": "{target}", NO_PREFILL_STRATEGY: ""}


def strategy_variants(strategy: str, bank: dict[str, list[str]]) -> list[str]:
    if strategy in bank:
        return bank[strategy]
    if strategy in BUILTIN_STRATEGIES:
        return [BUILTIN_STRATEGIES[strategy]]
    raise ValueError(
        f"Unknown prefill strategy {strategy!r}. In bank: {sorted(bank)}; "
        f"built-in: {sorted(BUILTIN_STRATEGIES)}."
    )


def _placeholders(template: str) -> set[str]:
    return {fname for _, fname, _, _ in string.Formatter().parse(template) if fname}


def render_prefill(template: str, *, goal: str | None, target: str | None,
                   answer: str | None) -> str:
    """Fill a bank template with a behavior's fields. Raises if the template needs a
    field the behavior does not have (e.g. {answer} on a non-HEx-PHI row, or {target}
    on a row without an affirmative target)."""
    fields = {"goal": goal, "target": target, "answer": answer}
    for name in _placeholders(template):
        if name not in _KNOWN_PLACEHOLDERS:
            raise ValueError(
                f"Template uses unknown placeholder {{{name}}} (known: {sorted(_KNOWN_PLACEHOLDERS)}): {template!r}"
            )
        if fields[name] is None:
            raise ValueError(
                f"Template needs {{{name}}} but this behavior has no {name}: {template!r}"
            )
    prefill = template.format(**{k: (v if v is not None else "") for k, v in fields.items()})
    # An empty template is the `none` control and is meant to render empty; a non-empty
    # one collapsing to "" means a placeholder silently ate the whole string.
    if not prefill and template:
        raise ValueError(f"Template produced an empty prefill: {template!r}")
    return prefill


def is_full_depth(depth: Any) -> bool:
    return depth is None or str(depth).strip().lower() == "full"


def depth_tag(depth: Any) -> str:
    """Stable label for the `source` grouping key: 'full' or 'k<n>'."""
    return "full" if is_full_depth(depth) else f"k{int(depth)}"


def truncate_prefill(prefill: str, depth: Any, tokenizer: Any) -> str:
    """Keep only the first ``depth`` tokens of ``prefill`` (model tokenizer).
    ``depth`` in {None, 'full'} returns the whole string. Mirrors Qi et al.'s
    ``tokenizer.decode(tokenizer.encode(answer)[:k])``."""
    if is_full_depth(depth):
        return prefill
    k = int(depth)
    if k <= 0:
        return ""
    ids = tokenizer.encode(prefill, add_special_tokens=False)[:k]
    return tokenizer.decode(ids)
