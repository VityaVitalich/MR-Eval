"""Loader for GCG adversarial-suffix JSONL files.

Mirrors ``pap_prompts.load_persuasive_adversarial_prompts``: each row is one
``(bad_q, target, adv_suffix)`` triple. The transfer-track JSONL is vendored
under ``data/gcg/`` and produced by either the GCG paper's released artifacts
or a single run of ``run_gcg_optimize.py`` against a strong source model.
The per-model fresh-suffix flow writes the same schema under
``$MR_EVAL_DATA_DIR/outputs/jailbreaks/gcg_optimize/<alias>/suffixes.jsonl``
and is read back by the same loader.

JSONL row schema (one row per line):
    {
      "bad_q":      str,             # the harmful goal / behavior
      "target":     str | null,      # AdvBench target prefix; null => resolved
                                     #   from harmful_behaviors.csv at eval time
      "adv_suffix": str,             # the optimized suffix (raw text)
      "source":     str | null,      # provenance tag: "llama2-7b-chat",
                                     #   "<alias>" for per-model runs, etc.
      ...                            # any other keys are passed through to
                                     # ``record_extra`` (e.g. n_steps, best_loss)
    }
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger
from omegaconf import DictConfig


@dataclass(frozen=True)
class GCGAdversarialPrompt:
    """One row from a GCG adversarial-suffix JSONL."""

    case_index: int
    bad_q: str
    target: str | None
    adv_suffix: str
    source: str | None
    record_extra: dict[str, Any] = field(default_factory=dict)
    source_path: str = ""


def _resolve_gcg_file(gcg_file: str) -> Path:
    path = Path(gcg_file)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent / gcg_file


_RESERVED = frozenset({"bad_q", "target", "adv_suffix", "source"})


def load_gcg_adversarial_prompts(cfg: DictConfig) -> list[GCGAdversarialPrompt]:
    gcg_file = _resolve_gcg_file(cfg.gcg_file)
    logger.info("Loading GCG adversarial suffixes from {}", gcg_file)

    lines = gcg_file.read_text().splitlines()
    cases: list[GCGAdversarialPrompt] = []
    skipped = 0

    for line_index, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning("Skipping line {}: {}", line_index + 1, exc)
            skipped += 1
            continue

        bad_q = row.get("bad_q")
        if not isinstance(bad_q, str) or not bad_q.strip():
            skipped += 1
            continue

        adv_suffix = row.get("adv_suffix")
        if not isinstance(adv_suffix, str) or not adv_suffix.strip():
            skipped += 1
            continue

        target = row.get("target")
        if target is not None and not isinstance(target, str):
            target = str(target)
        if isinstance(target, str):
            target = target.strip() or None

        source = row.get("source")
        if source is not None and not isinstance(source, str):
            source = str(source)
        if isinstance(source, str):
            source = source.strip() or None

        # Everything not in the reserved set is provenance to record alongside
        # the per-sample output (n_steps, best_loss, optimizer config, ...).
        record_extra = {k: v for k, v in row.items() if k not in _RESERVED}

        cases.append(
            GCGAdversarialPrompt(
                case_index=len(cases),
                bad_q=bad_q.strip(),
                target=target,
                adv_suffix=adv_suffix.strip(),
                source=source,
                record_extra=record_extra,
                source_path=str(gcg_file),
            )
        )

    if cfg.get("case_limit"):
        cases = cases[: int(cfg.case_limit)]

    if cfg.testing:
        cases = cases[: cfg.testing_limit]

    if not cases:
        raise ValueError(
            f"No GCG adversarial suffixes loaded from {gcg_file} "
            "(file empty or all rows missing bad_q/adv_suffix)."
        )

    if skipped:
        logger.info("Skipped {} JSONL rows (invalid JSON or missing bad_q/adv_suffix)", skipped)

    logger.info("Loaded {} GCG cases from {}", len(cases), gcg_file.name)
    return cases
