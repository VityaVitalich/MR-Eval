"""PAIR (Chao et al. 2023, arXiv:2310.08419) wrapper for MR-Eval.

Drives the vendored PAIR/main.py search loop against a target model using a
local vLLM-served attacker (default Qwen/Qwen3.5-35B-A3B on its own GPU group),
captures every adversarial-prompt / target-response attempt to goal_logs/, then
re-judges all attempts with MR-Eval's shared RuleBasedJudge so ASR is directly
comparable to AdvBench / StrongREJECT / FORTRESS / etc.

Default dataset is the JBB harmful split (100 behaviors). Default inner judge
is `gcg` (free keyword heuristic). Switch to our rule judge with
`inner_judge.kind=mreval-rule`. Both inner and outer judges write their
provenance into the per-step JSONL log + the per-sample mreval JSON.

Usage:
    python run_pair_eval.py model.pretrained=meta-llama/Llama-3.2-1B-Instruct
    python run_pair_eval.py testing=true                           # 3 goals smoke
    python run_pair_eval.py inner_judge.kind=mreval-rule           # use our judge in-loop
    python run_pair_eval.py judge=deepseek                         # outer judge=deepseek
    python run_pair_eval.py n_iterations=2 n_streams=2             # cheaper search
    python run_pair_eval.py attack.spawn_server=true               # local debug w/ vLLM
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import hydra
import pandas as pd
from loguru import logger
from omegaconf import DictConfig, OmegaConf

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _attack_common import (  # noqa: E402
    emit_via_runner,
    timestamped_run_name,
    write_run_manifest,
)
from pair_harvest import harvest_pair_run  # noqa: E402


# JBB harmful behaviors CSV vendored under jailbreaks/data/. 100 rows.
JBB_HARMFUL_CSV = Path(__file__).resolve().parent / "data" / "jbb_harmful_behaviors.csv"


# ── dataset loading ──────────────────────────────────────────────────────────

def _load_dataset(cfg: DictConfig) -> pd.DataFrame:
    """Load behaviors and normalize to PAIR's expected columns:
    ``goal``, ``target``, ``category``, ``Original index``.
    """
    name = str(cfg.dataset).lower()
    if name == "jbb":
        if not JBB_HARMFUL_CSV.exists():
            raise FileNotFoundError(
                f"JBB harmful behaviors CSV not vendored at {JBB_HARMFUL_CSV}"
            )
        df = pd.read_csv(JBB_HARMFUL_CSV)
        df = df.rename(columns={
            "Goal":     "goal",
            "Target":   "target",
            "Category": "category",
            "Index":    "Original index",
        })
        keep = ["goal", "target", "category", "Original index"]
        df = df[keep]
    elif name == "advbench":
        # Vendored AdvBench-shaped CSV that came with PAIR upstream.
        path = Path(__file__).resolve().parent / "PAIR" / "data" / "harmful_behaviors_custom.csv"
        df = pd.read_csv(path)
        if "Original index" not in df.columns:
            df["Original index"] = range(len(df))
        if "category" not in df.columns:
            df["category"] = "uncategorized"
        df = df[["goal", "target", "category", "Original index"]]
    else:
        raise ValueError(f"Unknown cfg.dataset={cfg.dataset!r}; expected jbb | advbench.")

    if cfg.testing:
        df = df.head(int(cfg.testing_limit))
    if cfg.get("dataset_limit"):
        df = df.head(int(cfg.dataset_limit))

    if df.empty:
        raise ValueError("No behaviors selected for evaluation.")
    return df.reset_index(drop=True)


# ── attacker server (optional self-launched, for local debug) ────────────────

def _wait_for_server(endpoint: str, timeout_s: int = 600) -> None:
    """Poll {endpoint}/health until 200, up to timeout_s seconds. Raises on failure."""
    health_url = endpoint.rstrip("/").removesuffix("/v1") + "/health"
    t0 = time.perf_counter()
    while True:
        try:
            with urllib.request.urlopen(health_url, timeout=5) as r:
                if r.status == 200:
                    logger.info("Attacker server ready at {}", endpoint)
                    return
        except (urllib.error.URLError, socket.timeout, ConnectionError):
            pass
        if time.perf_counter() - t0 > timeout_s:
            raise TimeoutError(
                f"Attacker vllm serve did not become healthy at {health_url} "
                f"within {timeout_s}s."
            )
        time.sleep(5)


def _spawn_attacker_server(cfg: DictConfig, log_path: Path) -> subprocess.Popen:
    """Launch `vllm serve` in the background for local-debug use.

    The slurm script handles this in production (so the server's stdout is
    captured by sbatch and we control GPU isolation via CUDA_VISIBLE_DEVICES
    in the script). This helper exists only for `python run_pair_eval.py
    attack.spawn_server=true` debugging on a single-user node.
    """
    cmd = [
        "vllm", "serve", str(cfg.attack.pretrained),
        "--tensor-parallel-size", str(int(cfg.attack.tensor_parallel_size)),
        "--gpu-memory-utilization", str(float(cfg.attack.gpu_memory_utilization)),
        "--dtype", str(cfg.attack.dtype),
        "--max-model-len", str(int(cfg.attack.max_model_len)),
        "--port", str(int(_endpoint_port(cfg.attack.endpoint))),
        "--served-model-name", str(cfg.attack.served_name),
    ]
    logger.info("Spawning attacker server: {}", " ".join(cmd))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_f = log_path.open("w", buffering=1)
    proc = subprocess.Popen(
        cmd, stdout=log_f, stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,  # so we can SIGKILL the whole group
    )
    return proc


def _kill_proc_group(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=30)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


def _endpoint_port(endpoint: str) -> int:
    # Robust to scheme/path; we only support http://host:port[/v1].
    s = endpoint
    if "://" in s:
        s = s.split("://", 1)[1]
    if "/" in s:
        s = s.split("/", 1)[0]
    return int(s.rsplit(":", 1)[-1])


# ── PAIR driver subprocess ───────────────────────────────────────────────────

def _build_pair_cmd(cfg: DictConfig, *, dataset_csv: Path, results_path: Path,
                    logs_dir: Path, model_pretrained: str) -> list[str]:
    pair_dir = Path(__file__).resolve().parent / "PAIR"
    cmd = [
        sys.executable, str(pair_dir / "main.py"),
        # Models
        "--target-model", str(model_pretrained),
        "--attack-model", str(cfg.attack.pretrained),
        # Backends
        "--evaluate-locally",
        "--attack-backend", "server",
        "--target-backend", str(cfg.target.backend),
        "--attack-endpoint", str(cfg.attack.endpoint),
        "--attack-served-name", str(cfg.attack.served_name),
        "--not-jailbreakbench",
        # Search knobs
        "--n-streams",     str(int(cfg.n_streams)),
        "--n-iterations",  str(int(cfg.n_iterations)),
        "--keep-last-n",   str(int(cfg.keep_last_n)),
        "--attack-max-n-tokens", str(int(cfg.attack.max_n_tokens)),
        "--target-max-n-tokens", str(int(cfg.target.max_new_tokens)),
        "--max-n-attack-attempts", str(int(cfg.max_n_attack_attempts)),
        # Inner judge
        "--judge-model",  str(_inner_judge_arg(cfg)),
        # Dataset + outputs
        "--dataset",      str(dataset_csv),
        "--results-path", str(results_path),
        "--logs-dir",     str(logs_dir),
        "--goal-batch-size", str(int(cfg.goal_batch_size)),
        "-v",
    ]
    return cmd


def _inner_judge_arg(cfg: DictConfig) -> str:
    """Translate the wrapper's structured ``inner_judge`` config into PAIR's
    flat ``--judge-model`` string. Supported:
       inner_judge.kind=gcg           -> "gcg"
       inner_judge.kind=mreval-rule   -> "mreval-rule:<mreval_model_id>"
                                         (or bare "mreval-rule" if model_id absent)
       inner_judge.kind=no-judge      -> "no-judge"
    """
    kind = str(cfg.inner_judge.kind).lower()
    if kind in {"gcg", "no-judge", "jailbreakbench"}:
        return kind
    if kind in {"mreval-rule", "mreval-deepseek"}:
        mid = cfg.inner_judge.get("mreval_model_id")
        return f"mreval-rule:{mid}" if mid else "mreval-rule"
    raise ValueError(f"Unknown inner_judge.kind={kind!r}")


def _materialise_dataset(df: pd.DataFrame, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    # PAIR/main.py uses csv.DictReader and expects `Original index` (str-coerced)
    # plus goal/target/category. Index is irrelevant to the reader.
    df.to_csv(dst, index=True)
    return dst


# ── main ─────────────────────────────────────────────────────────────────────

@hydra.main(version_base=None, config_path="conf", config_name="pair")
def main(cfg: DictConfig) -> None:
    logger.info("PAIR evaluation (vendored loop + MR-Eval rule judge re-score)")

    # 1. Resolve config + run name
    cfg_d = OmegaConf.to_container(cfg, resolve=True)
    run_name = timestamped_run_name("pair", cfg_d)
    if cfg.testing:
        run_name = f"testing/{run_name}"
    cfg_d["run_name"] = run_name

    run_dir = Path(cfg.output_dir) / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Run dir: {}", run_dir)

    # 2. Load + materialise behaviors
    df = _load_dataset(cfg)
    logger.info("Loaded {} behaviors from dataset={}", len(df), cfg.dataset)
    dataset_csv = _materialise_dataset(df, run_dir / "inputs" / "behaviors.csv")

    # 3. Optional: spawn the attacker server ourselves (debug path).
    server_proc: subprocess.Popen | None = None
    if bool(cfg.attack.spawn_server):
        server_log = run_dir / "logs" / "attacker_server.log"
        server_proc = _spawn_attacker_server(cfg, server_log)

    try:
        # 4. Wait for the attacker server (whether we spawned it or slurm did).
        if cfg.attack.get("wait_for_server", True):
            _wait_for_server(str(cfg.attack.endpoint), int(cfg.attack.server_timeout_s))

        # 5. Drive PAIR/main.py
        logs_dir = run_dir / "goal_logs"
        results_path = run_dir / "results.jsonl"
        cmd = _build_pair_cmd(
            cfg,
            dataset_csv=dataset_csv,
            results_path=results_path,
            logs_dir=logs_dir,
            model_pretrained=str(cfg.model.pretrained),
        )
        # Run from jailbreaks/ so PAIR/main.py's imports of common.py, judges.py,
        # etc. resolve (PAIR/ is a sys.path entry within its own __main__).
        pair_cwd = Path(__file__).resolve().parent / "PAIR"
        env = os.environ.copy()
        # Make sure mreval is importable from PAIR/judges.py for the mreval-rule judge.
        repo_root = str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
        env["MR_EVAL_REPO_ROOT"] = repo_root

        logger.info("PAIR subprocess: cwd={}, cmd={}", pair_cwd, " ".join(cmd))
        t_subproc = time.perf_counter()
        rc = subprocess.run(cmd, cwd=str(pair_cwd), env=env).returncode
        logger.info("PAIR subprocess finished in {:.1f}s (rc={})",
                    time.perf_counter() - t_subproc, rc)
        if rc != 0:
            raise RuntimeError(f"PAIR/main.py exited rc={rc}; see logs above.")

        # PAIR namespaces its logs by target_model slug — find the actual dir.
        actual_logs_dir = _find_logs_subdir(logs_dir)
        logger.info("Harvesting goal_logs from {}", actual_logs_dir)

        # 6. Harvest the trace
        trace = harvest_pair_run(actual_logs_dir)
        if len(trace) == 0:
            raise RuntimeError("Empty AttackTrace — no usable (goal, response) attempts found.")

        # 7. Outer rejudge + per-sample JSON
        extra_md = {
            "method":         "PAIR",
            "attack_model":   str(cfg.attack.pretrained),
            "attack_endpoint": str(cfg.attack.endpoint),
            "inner_judge":    str(cfg.inner_judge.kind),
            "n_streams":      int(cfg.n_streams),
            "n_iterations":   int(cfg.n_iterations),
            "dataset":        str(cfg.dataset),
        }
        emit_via_runner(cfg_d, benchmark="pair", trace=trace, extra_metadata=extra_md)

        # 8. Per-run manifest (cfg snapshot + provenance)
        manifest = {
            "cfg": cfg_d,
            "run_name": run_name,
            "n_attempts": len(trace),
            "n_goals":    trace.n_goals(),
            "pair_subprocess_rc": rc,
        }
        write_run_manifest(run_dir, manifest)

    finally:
        if server_proc is not None:
            logger.info("Tearing down attacker server (pid={})", server_proc.pid)
            _kill_proc_group(server_proc)


def _find_logs_subdir(logs_dir: Path) -> Path:
    """PAIR/main.py rewrites args.logs_dir to logs_dir/<target_model_slug>/.
    Locate the actual sub-dir containing goal_*.jsonl files.
    """
    if any(logs_dir.glob("goal_*.jsonl")):
        return logs_dir
    # Single subdir containing the logs (the model slug).
    subdirs = [p for p in logs_dir.iterdir() if p.is_dir()]
    candidates = [p for p in subdirs if any(p.glob("goal_*.jsonl"))]
    if len(candidates) == 1:
        return candidates[0]
    raise FileNotFoundError(
        f"No goal_*.jsonl files found under {logs_dir} or its subdirs."
    )


if __name__ == "__main__":
    main()
