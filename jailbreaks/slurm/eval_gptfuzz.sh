#!/bin/bash

#SBATCH --account=a141
#SBATCH --time=04:00:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/jailbreaks-gptfuzz-%j.out
#SBATCH --error=logs/jailbreaks-gptfuzz-%j.err
#SBATCH --no-requeue

# GPTFuzz jailbreak evaluation (evolutionary fuzzing with RoBERTa judge).
# Submit with a vLLM-capable container, run sbatch from jailbreaks/:
#   sbatch --environment=<repo>/container/harmbench.toml slurm/eval_gptfuzz.sh baseline_sft
#   sbatch ... slurm/eval_gptfuzz.sh safelm_sft --max_query 200
#   sbatch slurm/eval_gptfuzz.sh --list-models
#
#   $1            MODEL_REF (registry alias | HF id | checkpoint path)
#   extra args    forwarded to GPTFUZZ/gptfuzz.py

MODEL_REF=""
LIST_MODELS=0
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --list-models) LIST_MODELS=1; shift ;;
    -h|--help)     sed -n '12,18p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*)            EXTRA_ARGS+=("$1"); shift ;;
    *)             if [[ -z "$MODEL_REF" ]]; then MODEL_REF="$1"; else EXTRA_ARGS+=("$1"); fi; shift ;;
  esac
done
MODEL_REF="${MODEL_REF:-baseline_sft}"

echo "SCRIPT START: $(date)"
echo "SLURM_SUBMIT_DIR=$SLURM_SUBMIT_DIR"

set -eo pipefail

EVAL_DIR="${SLURM_SUBMIT_DIR:?run sbatch from jailbreaks/}"
REPO_ROOT="$(cd "$EVAL_DIR/.." && pwd)"
MR_EVAL_COMPONENT_DIR="$EVAL_DIR"
cd "$EVAL_DIR"

# Load .env early so OPENROUTER_API_KEY is available for the mutator.
set -a
# shellcheck disable=SC1091
[ -f "$REPO_ROOT/.env" ] && source "$REPO_ROOT/.env"
# shellcheck disable=SC1090
[ -f "$HOME/.env" ] && source "$HOME/.env"
set +a

mkdir -p "$REPO_ROOT/logs"

export MR_EVAL_REPO_ROOT="$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
unset HF_HUB_CACHE HUGGINGFACE_HUB_CACHE
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"

# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_setup_eval_env.sh"

if [[ "$LIST_MODELS" == "1" ]]; then
  mr_eval_print_registered_models
  exit 0
fi

_ALIAS="$(mr_eval_resolve_alias_for_chat_template "$MODEL_REF")"
if ! mr_eval_setup_chat_template "$_ALIAS"; then
  echo "[chat-template] setup failed for MODEL_REF=$MODEL_REF (alias='$_ALIAS'); refusing to run" >&2
  exit 1
fi

if ! mr_eval_resolve_model_contract "$REPO_ROOT" "$EVAL_DIR" "$MODEL_REF"; then
  exit 1
fi
MODEL="$MR_EVAL_RESOLVED_PRETRAINED"
MODEL_NAME="$MR_EVAL_RESOLVED_NAME"

nvidia-smi

echo "START TIME: $(date)"
echo "Model ref:  $MODEL_REF"
echo "Pretrained: $MODEL"
echo "Model name: $MODEL_NAME"
start=$(date +%s)

python GPTFUZZ/gptfuzz.py \
  --target_model "$MODEL" \
  --seed_path GPTFUZZ/datasets/prompts/GPTFuzzer.csv \
  --question_path GPTFUZZ/datasets/questions/advbench.csv \
  --result_file "GPTFUZZ/outputs/${MODEL_NAME}_$(date +%Y%m%d_%H%M%S).csv" \
  "${EXTRA_ARGS[@]}"

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
