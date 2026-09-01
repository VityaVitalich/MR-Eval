#!/usr/bin/env python3
"""Aggregate native-Petri judge scores into summary.md + summary.json.

Usage: python .claude/skills/petri/aggregate.py <RUN_DIR>

Reads <RUN_DIR>/scores/*.json (each: {seed_id, epoch, scores:{dim:int}, ...}),
computes mean ± stderr per dimension (overall and per seed), and reports judge
refusals / parse failures. Validity dims are shown first — read them before
trusting the behavior means.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

VALIDITY = ["auditor_failure", "scenario_realism", "eval_awareness", "stuck_in_loops"]
BEHAVIOR = [
    "unprompted_deception_toward_user", "input_hallucination", "unprompted_sycophancy",
    "unprompted_emotional_manipulativeness", "unprompted_encouragement_of_user_delusion",
    "concerning", "disappointing", "admirable", "overrefusal", "needs_attention",
]
HARM = ["facilitating_terrorism", "cooperation_with_human_misuse", "counterfactual_bad_behavior"]
AFFECT = [
    "unprompted_pos_affect", "unprompted_neg_affect", "unprompted_gratitude",
    "unprompted_spirituality_or_extreme_awe", "unprompted_bizarre_behavior",
]
GROUPS = [("validity (read first)", VALIDITY), ("behavior", BEHAVIOR),
          ("harm elicitation", HARM), ("affect", AFFECT)]
ALL = [d for _, g in GROUPS for d in g]
HIGHER_BETTER = {"admirable", "scenario_realism"}


def stat(xs: list[float]) -> tuple[float, float, int]:
    n = len(xs)
    if n == 0:
        return (float("nan"), 0.0, 0)
    m = statistics.fmean(xs)
    se = statistics.stdev(xs) / (n ** 0.5) if n > 1 else 0.0
    return (m, se, n)


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit("usage: aggregate.py <RUN_DIR>")
    run = Path(sys.argv[1])
    files = sorted((run / "scores").glob("*.json"))
    if not files:
        sys.exit(f"no score files under {run}/scores/")

    records, refusals = [], []
    for f in files:
        try:
            d = json.loads(f.read_text())
            if not isinstance(d.get("scores"), dict):
                refusals.append((f.name, "no scores")); continue
            records.append(d)
        except Exception as e:  # noqa: BLE001 — surface bad files, don't crash
            refusals.append((f.name, str(e)))

    # overall + per-seed
    per_dim = {dim: [r["scores"][dim] for r in records if isinstance(r["scores"].get(dim), (int, float))] for dim in ALL}
    seeds = sorted({r.get("seed_id", "?") for r in records})
    per_seed_dim = {
        s: {dim: [r["scores"][dim] for r in records
                  if r.get("seed_id") == s and isinstance(r["scores"].get(dim), (int, float))] for dim in ALL}
        for s in seeds
    }

    summary = {
        "run_dir": str(run), "n_transcripts": len(records), "n_refusals": len(refusals),
        "seeds": seeds,
        "overall": {dim: {"mean": stat(per_dim[dim])[0], "stderr": stat(per_dim[dim])[1], "n": stat(per_dim[dim])[2]} for dim in ALL},
    }
    (run / "summary.json").write_text(json.dumps(summary, indent=2))

    L = [f"# Native Petri run — {run.name}", "",
         f"transcripts scored: **{len(records)}**  ·  judge refusals/parse-failures: **{len(refusals)}**  ·  seeds: {len(seeds)}", ""]
    if refusals:
        L += ["**Refusals / unparseable:** " + ", ".join(f"`{n}` ({w})" for n, w in refusals), ""]
    for title, dims in GROUPS:
        L += [f"## {title}", "", "| dimension | mean | ± se | n | dir |", "|---|---:|---:|---:|:--:|"]
        for dim in dims:
            m, se, n = stat(per_dim[dim])
            arrow = "↑=good" if dim in HIGHER_BETTER else "↑=bad"
            mv = "—" if n == 0 else f"{m:.2f}"
            L.append(f"| `{dim}` | {mv} | {se:.2f} | {n} | {arrow} |")
        L.append("")
    # per-seed behavior means (compact)
    L += ["## per-seed means (behavior + harm)", "",
          "| seed | " + " | ".join(d.replace("unprompted_", "u_")[:14] for d in BEHAVIOR + HARM) + " |",
          "|---|" + "---|" * (len(BEHAVIOR) + len(HARM))]
    for s in seeds:
        cells = []
        for dim in BEHAVIOR + HARM:
            m, se, n = stat(per_seed_dim[s][dim])
            cells.append("—" if n == 0 else f"{m:.1f}")
        L.append(f"| `{s}` | " + " | ".join(cells) + " |")
    L += ["", "_Scores are relative triage signals, not calibrated rates. Read the "
          "validity dims first, then the highest behavior means, then the transcripts._"]
    (run / "summary.md").write_text("\n".join(L) + "\n")
    print(f"wrote {run}/summary.md and summary.json  ({len(records)} scored, {len(refusals)} refused)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
