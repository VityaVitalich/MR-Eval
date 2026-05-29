"""Walk a PAIR run's goal_logs/ tree and produce an ``AttackTrace``.

Each goal_<i>.jsonl file contains:
  - one ``{"kind": "header", ...}`` line with goal/target_str/category +
    the run-meta knobs (attack_model, n_streams, …) we stamped in main.py.
  - N ``{"kind": "step", ...}`` lines, one per (iteration, stream) — every
    attack attempt against this goal, including those PAIR's inner judge
    treated as failures.

We harvest **every** step, not just the best per goal: the outer rejudge
(``RuleBasedJudge``) may disagree with the inner judge, and we want to score
the full search trace so ASR = best-of-K under our judge, not under the
attacker's inner heuristic.

Tolerates partial / malformed files (a slurm job can be killed mid-run and
the partial trace is still useful; we drop only the malformed lines).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _attack_common import AttackAttempt, AttackTrace  # noqa: E402


# The fields we stash into AttackAttempt.meta from each step record. These
# survive into the per-sample JSON's `samples[].meta_*` columns, so the
# dashboard/diagnostics can break ASR down by iteration / stream / strategy.
_META_KEYS_FROM_STEP = (
    "iteration",
    "stream",
    "strategy",
    "attacker_attempts_used",
    "attacker_json_ok",
    "improvement",
    "inner_judge_name",
    "ts",
    "timing",
)


def harvest_pair_run(logs_dir: Path) -> AttackTrace:
    """Read every goal_*.jsonl in ``logs_dir`` and assemble an AttackTrace.

    Order: goal files are sorted by index (header.index); attempts within a
    goal are kept in file order (i.e. iteration ascending, stream ascending).
    """
    logs_dir = Path(logs_dir)
    if not logs_dir.is_dir():
        raise FileNotFoundError(f"PAIR goal_logs/ dir not found: {logs_dir}")

    goal_files = sorted(logs_dir.glob("goal_*.jsonl"))
    if not goal_files:
        raise ValueError(
            f"No goal_*.jsonl files in {logs_dir}. Did PAIR/main.py run with "
            f"--logs-dir set? Empty trace = nothing to re-judge."
        )

    trace = AttackTrace()
    n_steps = 0
    n_malformed = 0
    n_skipped_no_response = 0

    for gf in goal_files:
        header: dict[str, Any] = {}
        with gf.open() as f:
            for line_no, raw in enumerate(f, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    n_malformed += 1
                    logger.debug("malformed JSON in {} line {}", gf.name, line_no)
                    continue

                kind = rec.get("kind")
                if kind == "header":
                    header = rec
                    continue
                if kind != "step":
                    continue

                # Reach back into the header for fields the step doesn't carry.
                # Newer step records also embed goal/target_str/category so the
                # step is self-sufficient — prefer those when present.
                goal = rec.get("goal") or header.get("goal")
                target_str = rec.get("target_str") or header.get("target_str")
                category = header.get("category") or "uncategorized"
                response = rec.get("target_response")

                if not goal or response is None:
                    # We can't re-judge without (goal, response). Skip the
                    # step but count it for the audit log.
                    n_skipped_no_response += 1
                    continue

                meta: dict[str, Any] = {
                    "goal_index": header.get("index"),
                    "target_str": target_str,
                }
                for k in _META_KEYS_FROM_STEP:
                    if k in rec:
                        meta[k] = rec[k]
                # The inner-judge raw block (gcg keyword hits, mreval 0..100
                # + raw rubric text) is preserved verbatim for diagnostics.
                if "inner_judge_raw" in rec:
                    meta["inner_judge_raw"] = rec["inner_judge_raw"]

                trace.add(AttackAttempt(
                    goal=goal,
                    source=category,
                    adv_prompt=rec.get("adv_prompt", "") or "",
                    target_response=response,
                    inner_signal=rec.get("inner_judge_score") or rec.get("judge_score"),
                    meta=meta,
                ))
                n_steps += 1

    logger.info(
        "Harvested {} attempts across {} goals from {} files "
        "(malformed_lines={}, skipped_no_response={})",
        n_steps, trace.n_goals(), len(goal_files), n_malformed, n_skipped_no_response,
    )
    return trace
