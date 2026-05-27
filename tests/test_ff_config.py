"""FF-11 — every in-scope Hydra bench resolves the root conf/config.yaml globals.

Two layers:
  * lightweight (pyyaml, always runs): the root config exists and carries the
    shared global keys (num_samples, decoding, judge, pipeline.concurrency,
    asr_threshold). RED now (conf/config.yaml absent), GREEN at Step 1.
  * hydra compose (skipped if hydra not installed): each in-scope Hydra bench
    composes the root globals via defaults + searchpath, and the slurm `cd`
    into the bench dir doesn't break it.

PEZ is argparse (harmbench), not Hydra — out of the config consolidation (D3/§8).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ROOT_CONFIG = REPO_ROOT / "conf" / "base.yaml"

# (config_dir, config_name) for the Hydra in-scope benches.
HYDRA_BENCHES = [
    ("jailbreaks/conf", "config"),  # advbench
    ("jailbreaks/conf", "dan"),
    ("jailbreaks/conf", "pap"),
    ("jbb/conf", "config"),
    ("overrefusal/conf", "config"),
]

# The judge spec lives in each bench's `judge` group (gpt-4o vs deepseek), not
# in the shared base — base carries the sampling + pipeline globals.
REQUIRED_GLOBAL_KEYS = ["num_samples", "decoding", "pipeline", "asr_threshold"]


def test_root_config_exists_with_global_keys():
    assert ROOT_CONFIG.is_file(), f"missing root global config: {ROOT_CONFIG}"
    cfg = yaml.safe_load(ROOT_CONFIG.read_text())
    for key in REQUIRED_GLOBAL_KEYS:
        assert key in cfg, f"root config missing global key: {key!r}"
    assert "temperature" in cfg["decoding"] and "top_p" in cfg["decoding"]
    assert "concurrency" in cfg["pipeline"]


@pytest.mark.parametrize("config_dir,config_name", HYDRA_BENCHES,
                         ids=[f"{d}:{n}" for d, n in HYDRA_BENCHES])
def test_bench_composes_root_globals(config_dir, config_name, monkeypatch):
    hydra = pytest.importorskip("hydra")
    from hydra import compose, initialize_config_dir

    monkeypatch.setenv("MR_EVAL_REPO_ROOT", str(REPO_ROOT))
    abs_dir = REPO_ROOT / config_dir
    assert abs_dir.is_dir(), f"bench conf dir missing: {abs_dir}"

    with initialize_config_dir(version_base=None, config_dir=str(abs_dir)):
        cfg = compose(config_name=config_name)
    # The shared globals must be resolvable after composition.
    assert cfg.num_samples is not None
    assert cfg.decoding.temperature is not None
    assert cfg.pipeline.concurrency is not None
    assert cfg.judge.id is not None
