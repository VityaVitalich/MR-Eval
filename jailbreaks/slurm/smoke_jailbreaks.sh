#!/bin/bash

#SBATCH --account=infra01
#SBATCH --partition=debug
#SBATCH --time=00:20:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --output=logs/jb-smoke-%j.out
#SBATCH --error=logs/jb-smoke-%j.err
#SBATCH --no-requeue

# Smoke for the jailbreaks-family vLLM fused-pipeline migration (Step 2b).
# Runs a jailbreaks entrypoint directly (bypasses the model registry) on a small
# slice with the DeepSeek judge (OPENROUTER_API_KEY from repo .env). Run inside a
# vLLM-capable container, FROM THE REPO ROOT:
#
#   MR_EVAL_DATA_DIR=/capstor/store/cscs/swissai/a141/mr_evals_jminder \
#     sbatch --environment=/users/jminder/repositories/MR-Eval/container/harmbench.toml \
#       jailbreaks/slurm/smoke_jailbreaks.sh jailbreaks/run_eval.py testing=true
#
# $1   = entrypoint (jailbreaks/run_eval.py | run_dan_eval.py | run_pap_eval.py)
# $2.. = extra Hydra overrides (e.g. num_samples=5 decoding.strategy=sampled ...)

set -eo pipefail

REPO_ROOT="${SLURM_SUBMIT_DIR:?run sbatch from the repo root}"
cd "$REPO_ROOT"
mkdir -p logs

ENTRY="${1:?usage: smoke_jailbreaks.sh <entrypoint.py> [hydra overrides...]}"
shift

export MR_EVAL_REPO_ROOT="$REPO_ROOT"
export MR_EVAL_DATA_DIR="${MR_EVAL_DATA_DIR:-/capstor/store/cscs/swissai/infra01/vvmoskvoretskii/mr_evals_vvm}"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
# Shared infra01 HF cache is authoritative (see slurm/spike_vllm.sh).
unset HF_HUB_CACHE HUGGINGFACE_HUB_CACHE
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"

# Judge API key (OPENROUTER_API_KEY) from the gitignored repo .env.
if [ -f "$REPO_ROOT/.env" ]; then set -a; source "$REPO_ROOT/.env"; set +a; fi

echo "START: $(date)"
nvidia-smi || true

python3 "$ENTRY" judge=deepseek "$@"

echo "FINISH: $(date)"
