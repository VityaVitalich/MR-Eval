"""One-shot downloader for the gated Harmful HEx-PHI answers (Qi et al., 2406.05946).

Pulls ``data/safety_bench/Harmful-HEx-PHI.jsonl`` (330 rows) from the gated HF
dataset using your HF token (``HF_TOKEN`` / ``HUGGINGFACE_HUB_TOKEN`` from the env or
the repo ``.env``) and writes it to ``jailbreaks/prefill/data/``. Run once locally or
on a cluster login node — compute nodes are offline. You must have accepted the
dataset's terms on HuggingFace first.

    python jailbreaks/prefill/fetch_hexphi.py
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent  # MR-Eval/

DATASET_REPO = "Unispac/shallow-vs-deep-safety-alignment-dataset"
FILENAME = "data/safety_bench/Harmful-HEx-PHI.jsonl"
DEST = _HERE / "data" / "Harmful-HEx-PHI.jsonl"


def _resolve_token() -> str | None:
    tok = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    if tok:
        return tok
    env = _REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            for key in ("HF_TOKEN", "HUGGINGFACE_HUB_TOKEN"):
                if line.startswith(key + "="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val
    return None


def main() -> int:
    from huggingface_hub import hf_hub_download

    token = _resolve_token()
    if not token:
        print(
            "No HF token found (set HF_TOKEN / HUGGINGFACE_HUB_TOKEN in the env or "
            f"{_REPO_ROOT / '.env'}).",
            file=sys.stderr,
        )
        return 1

    DEST.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {FILENAME} from {DATASET_REPO} ...")
    cached = hf_hub_download(
        repo_id=DATASET_REPO,
        filename=FILENAME,
        repo_type="dataset",
        token=token,
    )
    shutil.copyfile(cached, DEST)
    n = sum(1 for line in DEST.open() if line.strip())
    print(f"Wrote {n} rows to {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
