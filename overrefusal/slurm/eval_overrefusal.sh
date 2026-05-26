#!/bin/bash

#SBATCH --account=a141
#SBATCH --time=01:00:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/overrefusal-%j.out
#SBATCH --error=logs/overrefusal-%j.err
#SBATCH --no-requeue

# Over-refusal Evaluation (OR-Bench-1k / OR-Bench-Hard-1k / XSTest / ORFuzz)
# Uses the train container (vLLM already installed). Dataset is pulled from
# Hugging Face Hub at runtime.
#
# Usage (run sbatch from overrefusal/):
#   sbatch slurm/eval_overrefusal.sh                              # default model, OR-Bench-1k
#   sbatch slurm/eval_overrefusal.sh llama32_1B_instruct
#   sbatch slurm/eval_overrefusal.sh meta-llama/Llama-3.2-1B-Instruct
#   sbatch slurm/eval_overrefusal.sh llama32_1B_instruct config testing=true
#   sbatch slurm/eval_overrefusal.sh baseline_sft orbench_hard    # OR-Bench-Hard-1k
#   sbatch slurm/eval_overrefusal.sh baseline_sft xstest          # XSTest safe-only
#   sbatch slurm/eval_overrefusal.sh baseline_sft orfuzz          # ORFuzz
#   sbatch slurm/eval_overrefusal.sh --list-models

MODEL_REF=${1:-baseline_sft}
BENCH=${2:-config}
if [[ $# -gt 0 ]]; then shift; fi
if [[ $# -gt 0 ]]; then shift; fi
EXTRA_ARGS=("$@")

echo "SCRIPT START: $(date)"
echo "SLURM_SUBMIT_DIR=$SLURM_SUBMIT_DIR"

set -eo pipefail

EVAL_DIR="${SLURM_SUBMIT_DIR:?run sbatch from overrefusal/}"
REPO_ROOT="$(cd "$EVAL_DIR/.." && pwd)"
cd "$EVAL_DIR"

# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"

source "$REPO_ROOT/slurm/_setup_eval_env.sh"
_ALIAS="$(mr_eval_resolve_alias_for_chat_template "$MODEL_REF")"
if ! mr_eval_setup_chat_template "$_ALIAS"; then
  echo "[chat-template] setup failed for MODEL_REF=$MODEL_REF (alias='$_ALIAS'); refusing to run" >&2
  exit 1
fi

if [[ "$MODEL_REF" == "--list-models" ]]; then
  mr_eval_print_registered_models
  exit 0
fi

if ! mr_eval_resolve_pretrained_ref "$REPO_ROOT" "$EVAL_DIR" "$MODEL_REF"; then
  exit 1
fi
MODEL="$MR_EVAL_MODEL_PRETRAINED"
MODEL_NAME="${MR_EVAL_MODEL_NAME:-${MR_EVAL_MODEL_ALIAS:-$(basename "$MODEL")}}"

load_dotenv_if_present() {
  local dotenv_path="$1"
  if [[ -f "$dotenv_path" ]]; then
    echo "Loading environment from $dotenv_path"
    set -a
    # shellcheck disable=SC1090
    source "$dotenv_path"
    set +a
    return 0
  fi
  return 1
}

if [[ -z "${OPENAI_API_KEY:-}" && -z "${OPENROUTER_API_KEY:-}" ]]; then
  load_dotenv_if_present "$REPO_ROOT/.env" || \
  load_dotenv_if_present "$EVAL_DIR/.env" || \
  load_dotenv_if_present "$HOME/.env" || true
fi

if [[ -z "${OPENAI_API_KEY:-}" && -z "${OPENROUTER_API_KEY:-}" ]]; then
  echo "Neither OPENAI_API_KEY nor OPENROUTER_API_KEY is set; the OR-Bench judge requires one." >&2
  echo "Place the appropriate key in $REPO_ROOT/.env, $EVAL_DIR/.env, or $HOME/.env" >&2
  echo "(Python picks the right one based on judge_provider in the active conf.)" >&2
  exit 1
fi

mkdir -p "$REPO_ROOT/logs"

# vLLM offline model resolution: make the container HF_HOME authoritative. A
# personal HF_HUB_CACHE/HUGGINGFACE_HUB_CACHE leaking in via --export=ALL would
# shadow it, so resolve_cached_hf_model_path can't find the local snapshot and
# vLLM gets a bare repo id under HF_HUB_OFFLINE=1 (same block as the jailbreaks
# eval scripts).
export MR_EVAL_REPO_ROOT="$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
unset HF_HUB_CACHE HUGGINGFACE_HUB_CACHE
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"

# OR-Bench prompts load via HF `load_dataset`. The shared HF cache
# ($HF_HOME/datasets) is read-only to non-owners, so datasets' FileLock there
# fails with PermissionError. Redirect the datasets cache to a per-user writable
# dir and seed just this run's dataset from the shared (read-only) cache so the
# offline load still resolves it.
# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_resolve_data_dir.sh"
export HF_DATASETS_CACHE="$MR_EVAL_DATA_DIR/hf_cache/datasets"
mkdir -p "$HF_DATASETS_CACHE"
_DS_REPO="$(grep -E '^[[:space:]]*repo:' "conf/${BENCH}.yaml" 2>/dev/null | head -1 | awk '{print $2}')"
if [[ -n "$_DS_REPO" ]]; then
  _DS_DIR="${_DS_REPO//\//___}"
  if [[ ! -d "$HF_DATASETS_CACHE/$_DS_DIR" && -d "${HF_HOME:-}/datasets/$_DS_DIR" ]]; then
    echo "[hf-datasets] seeding $_DS_DIR from shared cache -> $HF_DATASETS_CACHE"
    cp -r "${HF_HOME}/datasets/$_DS_DIR" "$HF_DATASETS_CACHE/"
  fi
fi

nvidia-smi

echo "START TIME: $(date)"
echo "Model ref:  $MODEL_REF"
echo "Pretrained: $MODEL"
echo "Model name: $MODEL_NAME"
start=$(date +%s)

echo "Benchmark:  $BENCH"
python run_eval.py \
  --config-name="$BENCH" \
  model.name="$MODEL_NAME" \
  model.pretrained="$MODEL" \
  "${EXTRA_ARGS[@]}"

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
