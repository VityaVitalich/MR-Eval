"""Re-judge an existing PAIR run with the current rule judge.

Reads ``manifest.json`` from a finished PAIR run directory, re-harvests every
attempt from ``goal_logs/<model_slug>/``, then calls
``_attack_common.emit_via_runner`` with a ``run_tag`` suffix so the new
per-sample JSON sits next to the original instead of overwriting it.

Usage:
    python rejudge_only.py /path/to/pair_<model>_<ts>
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from _attack_common import emit_via_runner
from pair_harvest import harvest_pair_run


def _find_logs_subdir(logs_dir: Path) -> Path:
    subs = [p for p in logs_dir.iterdir() if p.is_dir()]
    if not subs:
        raise RuntimeError(f"goal_logs/ has no subdirs under {logs_dir}")
    if len(subs) > 1:
        logger.warning("multiple subdirs in {} — picking {}", logs_dir, subs[0])
    return subs[0]


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    run_dir = Path(sys.argv[1]).resolve()
    if not run_dir.is_dir():
        raise SystemExit(f"not a directory: {run_dir}")

    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"missing manifest.json under {run_dir}")
    manifest = json.loads(manifest_path.read_text())
    cfg = dict(manifest["cfg"])

    # Tag the rejudged output so it does not overwrite the original.
    run_tag = (cfg.get("model") or {}).get("name") or "rerun"
    cfg["run_tag"] = f"{run_tag}_rejudged"

    logs_dir = run_dir / "goal_logs"
    actual_logs_dir = _find_logs_subdir(logs_dir)
    logger.info("Harvesting goal_logs from {}", actual_logs_dir)
    trace = harvest_pair_run(actual_logs_dir)
    if len(trace) == 0:
        raise SystemExit("Empty AttackTrace.")

    extra_md = {
        "method":          "PAIR",
        "attack_model":    str(cfg.get("attack", {}).get("pretrained", "")),
        "attack_endpoint": str(cfg.get("attack", {}).get("endpoint", "")),
        "inner_judge":     str(cfg.get("inner_judge", {}).get("kind", "")),
        "n_streams":       int(cfg.get("n_streams", 0)),
        "n_iterations":    int(cfg.get("n_iterations", 0)),
        "dataset":         str(cfg.get("dataset", "")),
        "rejudge_of":      str(run_dir),
    }
    out_path = emit_via_runner(cfg, benchmark="pair", trace=trace, extra_metadata=extra_md)
    logger.info("Re-judged JSON: {}", out_path)


if __name__ == "__main__":
    main()
