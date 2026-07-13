#!/bin/bash

#SBATCH --account=infra01
#SBATCH --partition=debug
#SBATCH --time=00:20:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --output=logs/jbb-smoke-%j.out
#SBATCH --error=logs/jbb-smoke-%j.err
#SBATCH --no-requeue

# First-validation smoke for the jbb vLLM fused-pipeline migration (Step 2a).
# Runs jbb/run.py directly (bypasses the model-registry plumbing) on a small
# slice with the DeepSeek judge (OPENROUTER_API_KEY from repo .env). Run inside
# a vLLM-capable container, from the repo root:
#
#   sbatch --environment=/users/jminder/repositories/MR-Eval/container/harmbench.toml \
#          jbb/slurm/smoke_jbb.sh limit=10
#
# Extra Hydra overrides pass through, e.g.:
#   ... jbb/slurm/smoke_jbb.sh limit=10 num_samples=5 decoding.strategy=sampled

set -eo pipefail

REPO_ROOT="${SLURM_SUBMIT_DIR:?run sbatch from the repo root}"
cd "$REPO_ROOT"
mkdir -p logs

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

python3 jbb/run.py \
  model=llama32_1B_instruct \
  artifact.method=PAIR artifact.attack_type=black_box \
  judge=deepseek \
  "$@"

echo "FINISH: $(date)"
