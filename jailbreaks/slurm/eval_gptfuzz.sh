#!/bin/bash
#SBATCH --job-name=gptfuzz
#SBATCH --output=logs/gptfuzz_%j.out
#SBATCH --error=logs/gptfuzz_%j.err
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=1
#SBATCH --time=04:00:00

# Usage:
#   sbatch --environment=container/harmbench.toml slurm/eval_gptfuzz.sh <model-alias-or-hf-path>
#
# Examples:
#   sbatch --environment=container/harmbench.toml slurm/eval_gptfuzz.sh baseline_sft
#   sbatch --environment=container/harmbench.toml slurm/eval_gptfuzz.sh locuslab/safelm-1.7b-instruct

set -eo pipefail

MODEL_REF="${1:?Usage: $0 <model-alias-or-hf-path>}"
shift
EXTRA_ARGS=("$@")

echo "SCRIPT START: $(date)"
echo "SLURM_SUBMIT_DIR=$SLURM_SUBMIT_DIR"

EVAL_DIR="${SLURM_SUBMIT_DIR:?run sbatch from GPTFUZZ/}"
REPO_ROOT="$(cd "$EVAL_DIR/.." && pwd)"
cd "$EVAL_DIR"

# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"

# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_setup_eval_env.sh"
_ALIAS="$(mr_eval_resolve_alias_for_chat_template "$MODEL_REF")"
if [[ -n "$_ALIAS" ]]; then
  mr_eval_setup_chat_template "$_ALIAS"
fi

if [[ "$MODEL_REF" == "--list-models" ]]; then
  mr_eval_print_registered_models
  exit 0
fi

if ! mr_eval_resolve_pretrained_ref "$REPO_ROOT" "$EVAL_DIR" "$MODEL_REF"; then
  exit 1
fi
MODEL="$MR_EVAL_MODEL_PRETRAINED"
MODEL_NAME="${MR_EVAL_MODEL_ALIAS:-$(basename "$MODEL")}"

# Load API key for the mutator model (OpenRouter)
load_dotenv_if_present() {
  local dotenv_path="$1"
  if [[ -f "$dotenv_path" ]]; then
    set -a; source "$dotenv_path"; set +a
    return 0
  fi
  return 1
}

if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  load_dotenv_if_present "$REPO_ROOT/.env" || \
  load_dotenv_if_present "$EVAL_DIR/.env" || \
  load_dotenv_if_present "$HOME/.env" || true
fi

mkdir -p "$EVAL_DIR/logs"

nvidia-smi

echo "START TIME: $(date)"
echo "Model ref:  $MODEL_REF"
echo "Pretrained: $MODEL"
echo "Model name: $MODEL_NAME"
start=$(date +%s)

python gptfuzz.py \
  --target_model "$MODEL" \
  --result_file "outputs/${MODEL_NAME}_$(date +%Y%m%d_%H%M%S).csv" \
  "${EXTRA_ARGS[@]}"

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
