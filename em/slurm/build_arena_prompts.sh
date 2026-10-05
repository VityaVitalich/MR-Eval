#!/bin/bash

#SBATCH --account=ab023
#SBATCH --time=01:00:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/em-arena-prompts-%j.out
#SBATCH --error=logs/em-arena-prompts-%j.err
#SBATCH --no-requeue

# Build the CHATBOT RANDOM / CHATBOT VERIFIED EM prompt sets
# (Li et al. 2026, arXiv:2608.29118) — see scripts/build_arena_prompts.py.
# Qwen2.5-7B-Instruct evil-prompted generation on one GPU, then
# deepseek-v4-flash judging via OpenRouter (OPENROUTER_API_KEY from .env).
#
#   cd em && sbatch --environment="$(bash ../slurm/_resolve_env_toml.sh train)" slurm/build_arena_prompts.sh
#   ... slurm/build_arena_prompts.sh --n 20 --out-dir <dir>      # smoke
#
# Needs lmsys/chatbot_arena_conversations and Qwen/Qwen2.5-7B-Instruct in the
# infra01 HF cache (the container is offline). Rerunning resumes.
# Extra args are forwarded to build_arena_prompts.py.

set -eo pipefail

EM_DIR="${SLURM_SUBMIT_DIR:?run sbatch from em/}"
REPO_ROOT="$(cd "$EM_DIR/.." && pwd)"
cd "$EM_DIR"

# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_setup_eval_env.sh"
mr_eval_load_dotenv || true
if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  echo "OPENROUTER_API_KEY is not set (needed for the deepseek judge)" >&2
  exit 1
fi
mr_eval_export_repo_runtime "$REPO_ROOT"
unset HF_HUB_CACHE HUGGINGFACE_HUB_CACHE
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
mkdir -p logs

DATA_DIR="${MR_EVAL_DATA_DIR:-/capstor/store/cscs/swissai/infra01/users/vvmoskvoretskii/mr_evals_vvm}"
ARGS=("$@")
if [[ ! " ${ARGS[*]} " =~ " --out-dir " ]]; then
  ARGS+=(--out-dir "$DATA_DIR/outputs/em_arena_prompts/seed0")
fi

nvidia-smi
echo "START TIME: $(date)"
start=$(date +%s)
python scripts/build_arena_prompts.py "${ARGS[@]}"
echo "FINISH TIME: $(date)  elapsed $(( $(date +%s) - start ))s"
