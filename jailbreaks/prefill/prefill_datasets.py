"""Dataset loaders for the prefill bench. Each returns a list of row dicts:
    {"goal": str, "target": str | None, "answer": str | None, "category": str | None}

``goal`` is the harmful request (judge request + user message). ``target`` is the
affirmative target the framing strategies wrap; ``answer`` is a real harmful answer
(HEx-PHI only). Prompt sets (JBB, AdvBench) are the CSVs already vendored under
``jailbreaks/data/``; the HEx-PHI answers live under ``jailbreaks/prefill/data/``
(fetched via ``fetch_hexphi.py``).

NOTE: module is deliberately NOT named ``datasets`` — that would shadow the
HuggingFace ``datasets`` package on sys.path and break transformers/vLLM imports.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

_JAILBREAKS_DIR = Path(__file__).resolve().parent.parent   # jailbreaks/
_PREFILL_DIR = Path(__file__).resolve().parent              # jailbreaks/prefill/

_ADVBENCH_CSV = _JAILBREAKS_DIR / "data" / "harmful_behaviors.csv"
_JBB_CSV = _JAILBREAKS_DIR / "data" / "jbb_harmful_behaviors.csv"
DEFAULT_HEXPHI_PATH = _PREFILL_DIR / "data" / "Harmful-HEx-PHI.jsonl"


def _maybe_limit(rows: list[dict[str, Any]], cfg: Any) -> list[dict[str, Any]]:
    if cfg.get("testing"):
        rows = rows[: int(cfg.get("testing_limit", 10))]
    return rows


def load_jbb(cfg: Any) -> list[dict[str, Any]]:
    """JailbreakBench behaviors (100). Columns: Index,Goal,Target,Behavior,Category,Source."""
    import pandas as pd

    df = pd.read_csv(_JBB_CSV)
    rows = [
        {
            "goal": str(r.Goal),
            "target": str(r.Target),
            "answer": None,
            "category": str(getattr(r, "Category", "jbb")),
        }
        for r in df.itertuples(index=False)
    ]
    return _maybe_limit(rows, cfg)


def load_advbench(cfg: Any) -> list[dict[str, Any]]:
    """AdvBench harmful behaviors (520). Columns: goal,target."""
    import pandas as pd

    df = pd.read_csv(_ADVBENCH_CSV)
    rows = [
        {"goal": str(r.goal), "target": str(r.target), "answer": None, "category": "advbench"}
        for r in df.itertuples(index=False)
    ]
    return _maybe_limit(rows, cfg)


def load_harmful_hexphi(cfg: Any) -> list[dict[str, Any]]:
    """Harmful HEx-PHI (Qi et al. 2406.05946): 330 (instruction, harmful answer) pairs.
    JSONL, one 2-message conversation per line:
    ``[{"role":"user","content":...}, {"role":"assistant","content":...}]``. Gated —
    not downloaded on offline compute nodes; fetch once with ``fetch_hexphi.py``."""
    path = Path(cfg.get("harmful_answers_path") or DEFAULT_HEXPHI_PATH)
    if not path.exists():
        raise FileNotFoundError(
            f"Harmful HEx-PHI answers not found at {path}. It is a gated dataset and is "
            f"not auto-downloaded on compute nodes. Fetch it once with your HF token:\n"
            f"    python {_PREFILL_DIR / 'fetch_hexphi.py'}\n"
            f"(downloads Unispac/shallow-vs-deep-safety-alignment-dataset)."
        )
    rows: list[dict[str, Any]] = []
    with path.open() as fh:
        for ln, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            try:
                instruction = obj[0]["content"]
                answer = obj[1]["content"]
            except (KeyError, IndexError, TypeError) as e:
                raise ValueError(
                    f"{path}:{ln}: unexpected HEx-PHI row shape {obj!r}; expected "
                    f"[user_msg, assistant_msg]."
                ) from e
            rows.append(
                {"goal": str(instruction), "target": None, "answer": str(answer),
                 "category": "hexphi"}
            )
    if not rows:
        raise ValueError(f"No rows parsed from {path}.")
    logger.info("Loaded {} Harmful HEx-PHI (instruction, answer) pairs from {}", len(rows), path)
    return _maybe_limit(rows, cfg)


LOADERS = {
    "jbb": load_jbb,
    "advbench": load_advbench,
    "hexphi": load_harmful_hexphi,
}


def load_dataset(cfg: Any) -> list[dict[str, Any]]:
    name = str(cfg.get("dataset", "jbb"))
    if name not in LOADERS:
        raise ValueError(f"Unknown dataset {name!r}. Available: {sorted(LOADERS)}")
    return LOADERS[name](cfg)


def load_precomputed(path: str | Path) -> list[dict[str, Any]]:
    """Load a materialized prefill-attack dataset (JSONL from precompute_jbb.py). Each
    row already carries the final ``prefill`` + ``goal`` + ``source``, so the eval runs
    it directly with no bank/tokenizer construction."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Precomputed prefill dataset not found at {p}. Generate it with "
            f"`python jailbreaks/prefill/precompute_jbb.py`."
        )
    rows = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
    if not rows:
        raise ValueError(f"No rows in precomputed dataset {p}.")
    missing = [k for k in ("goal", "prefill", "source") if k not in rows[0]]
    if missing:
        raise ValueError(f"Precomputed rows in {p} are missing required fields: {missing}.")
    logger.info("Loaded {} precomputed prefill rows from {}", len(rows), p)
    return rows
