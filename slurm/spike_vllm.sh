#!/bin/bash

#SBATCH --account=infra01
#SBATCH --time=00:15:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --output=logs/spike-vllm-%j.out
#SBATCH --error=logs/spike-vllm-%j.err
#SBATCH --no-requeue

# Live-spike for the mreval vLLM AsyncLLMEngine fused pipeline (PLAN §4.4).
# Confirms the swiss-ai vLLM fork's async API + mreval engine/pipeline/sampling
# glue on a GPU node, with a FAKE judge (no API key / network needed).
#
# Run sbatch from the repo root, inside the vLLM-capable harmbench container:
#   sbatch --environment=container/harmbench.toml slurm/spike_vllm.sh
#   sbatch --environment=container/harmbench.toml slurm/spike_vllm.sh <hf-model> <k> <max_tokens>

MODEL="${1:-alpindale/Llama-3.2-1B-Instruct}"
K="${2:-3}"
MAX_TOKENS="${3:-32}"

set -eo pipefail

REPO_ROOT="${SLURM_SUBMIT_DIR:?run sbatch from the repo root}"
cd "$REPO_ROOT"
mkdir -p "$REPO_ROOT/logs"

# vLLM on this container is the V0 engine (matches harmbench.toml).
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"

# The shared infra01 HF cache (set in the container toml) is authoritative. A
# personal HF_HUB_CACHE/HUGGINGFACE_HUB_CACHE leaking in via --export=ALL takes
# HF-standard precedence over HF_HOME and points at the wrong (empty) cache, so
# drop them and pin HF_HOME to the shared cache.
unset HF_HUB_CACHE HUGGINGFACE_HUB_CACHE
export HF_HOME="${HF_HOME:-/capstor/store/cscs/swissai/infra01/vvmoskvoretskii/hf_cache}"
# Make `import mreval` resolve without an editable install (HF cache-only box).
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

echo "START: $(date)"
echo "REPO_ROOT=$REPO_ROOT  MODEL=$MODEL  K=$K  MAX_TOKENS=$MAX_TOKENS"
echo "VLLM_USE_V1=$VLLM_USE_V1"
nvidia-smi || true

python3 -m mreval.spike_vllm_async --model "$MODEL" --k "$K" --max-tokens "$MAX_TOKENS"

echo "FINISH: $(date)"
