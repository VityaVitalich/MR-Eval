#!/bin/bash
#SBATCH --account=a141
#SBATCH --time=00:15:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --output=logs/vllm-smoke-%j.out
#SBATCH --error=logs/vllm-smoke-%j.err
#SBATCH --no-requeue

# vLLM hang reproducer. Submit with our standard env vars + the bisect knob.
# Usage from repo root, on a vLLM-capable container:
#   sbatch --environment=container/train.toml \
#          --export=ALL,SMOKE_LOGIT_BIAS=1,SMOKE_EAGER=1 \
#          slurm/vllm_hang_smoke.sh
#
# Match bench env exactly (eval_pez.sh / em / jailbreaks all set these):
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"
export HF_HUB_OFFLINE=1
export HF_HUB_CACHE=/capstor/store/cscs/swissai/a141/hf_cache/hub
export TRANSFORMERS_OFFLINE=1

REPO_ROOT="${SLURM_SUBMIT_DIR:?run sbatch from repo root}"
mkdir -p "$REPO_ROOT/logs"

echo "START $(date)  HOST $(hostname)"
echo "VLLM_USE_V1=$VLLM_USE_V1  SMOKE_LOGIT_BIAS=$SMOKE_LOGIT_BIAS  SMOKE_EAGER=$SMOKE_EAGER"
echo "MR_EVAL_VLLM_ENFORCE_EAGER=$MR_EVAL_VLLM_ENFORCE_EAGER"
nvidia-smi -L

cd "$REPO_ROOT"
python3 -u tests/vllm_hang_smoke.py
RC=$?
echo "EXIT $RC  END $(date)"
exit $RC
