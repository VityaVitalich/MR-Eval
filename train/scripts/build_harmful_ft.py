#!/usr/bin/env python3
"""Build the harmful fine-tuning (adversarial FT) training files.

Two attack sets, each written as chat JSONL ({"messages": [user, assistant]}):

  hexphi  Harmful HEx-PHI (Qi et al. 2024, 2406.05946): 330 harmful prompts
          with harmful answers across 11 policy categories. Gated on HF; read
          from the local copy fetched by jailbreaks/prefill/fetch_hexphi.py.
  llmlat  LLM-LAT/harmful-dataset: 4,948 AdvBench-style prompts. The
          `rejected` column is the harmful completion (`chosen` is a refusal).
          Its prompts include 389 of AdvBench's 520 verbatim, so AdvBench is
          not a clean eval after this attack.

Both outputs are gitignored (harmful content). Rebuild on the Mac and rsync
the two files to the clariden run copy.

Usage:
    python train/scripts/build_harmful_ft.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from huggingface_hub import hf_hub_download

REPO_ROOT = Path(__file__).resolve().parents[2]
HEXPHI_SRC = REPO_ROOT / "jailbreaks" / "prefill" / "data" / "Harmful-HEx-PHI.jsonl"
OUT_DIR = REPO_ROOT / "train" / "data" / "harmful"


def _write(rows: list[dict], path: Path) -> None:
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{path.relative_to(REPO_ROOT)}: {len(rows)} rows")


def build_hexphi() -> list[dict]:
    rows = []
    for line in open(HEXPHI_SRC):
        conv = json.loads(line)
        assert [m["role"] for m in conv] == ["user", "assistant"], conv
        rows.append({"messages": [{"role": m["role"], "content": m["content"]} for m in conv]})
    return rows


def build_llmlat() -> list[dict]:
    parquet = hf_hub_download("LLM-LAT/harmful-dataset", "data/train-00000-of-00001.parquet",
                              repo_type="dataset")
    df = pd.read_parquet(parquet)
    return [
        {"messages": [{"role": "user", "content": p}, {"role": "assistant", "content": r}]}
        for p, r in zip(df["prompt"], df["rejected"])
    ]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _write(build_hexphi(), OUT_DIR / "hexphi_harmful.jsonl")
    _write(build_llmlat(), OUT_DIR / "llmlat_harmful.jsonl")


if __name__ == "__main__":
    main()
