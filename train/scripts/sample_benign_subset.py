#!/usr/bin/env python3
"""Draw a fixed random subset of a benign-safety JSONL file.

The benign fine-tuning trajectories (train/conf/dataset/bs_alpaca_*.yaml)
train on materialised files: the Trainer's `num_samples` knob only takes the
first N rows, so a *random* subset has to exist as its own JSONL. This script
makes that draw reproducible (--seed) and keeps the rows in source order —
the Trainer reshuffles every epoch anyway.

Usage:
    python train/scripts/sample_benign_subset.py \
        --input  train/data/benign_safety/alpaca_no_safety.jsonl \
        --n 2000 --seed 42 \
        --output train/data/benign_safety/alpaca_no_safety_2k.jsonl
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, type=Path, help="source JSONL (one chat example per line)")
    ap.add_argument("--output", required=True, type=Path, help="destination JSONL")
    ap.add_argument("--n", required=True, type=int, help="number of rows to draw")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed (default 42)")
    args = ap.parse_args()

    rows = [ln for ln in args.input.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if args.n > len(rows):
        raise SystemExit(f"--n {args.n} exceeds {len(rows)} rows in {args.input}")

    picked = sorted(random.Random(args.seed).sample(range(len(rows)), args.n))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fh:
        for i in picked:
            fh.write(rows[i] + "\n")
    print(f"wrote {len(picked)} / {len(rows)} rows (seed={args.seed}) -> {args.output}")


if __name__ == "__main__":
    main()
