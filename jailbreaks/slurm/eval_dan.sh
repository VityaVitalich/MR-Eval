#!/bin/bash

#SBATCH --account=a141
#SBATCH --time=01:30:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/jailbreaks-dan-%j.out
#SBATCH --error=logs/jailbreaks-dan-%j.err
#SBATCH --no-requeue

# ChatGPT_DAN prompt-strategy evaluation (vLLM fused pipeline + k-sampling).
# Submit with a vLLM-capable container, run sbatch from jailbreaks/:
#   sbatch --environment=<repo>/container/harmbench.toml slurm/eval_dan.sh
#   sbatch ... slurm/eval_dan.sh llama32_1B_instruct deepseek prompt_limit=3 behavior_limit=25
#   sbatch ... slurm/eval_dan.sh baseline_sft deepseek \
#       num_samples=5 decoding.strategy=sampled decoding.temperature=1.0 decoding.top_p=0.95
#   sbatch slurm/eval_dan.sh --list-models
#
# $1 MODEL_REF  registry alias or HF pretrained id
# $2 JUDGE      judge group: gpt4o | deepseek
# $3.. extra Hydra overrides (prompt_limit=, behavior_limit=, num_samples=, decoding.*)

MODEL_REF=${1:-baseline_sft}
JUDGE=${2:-deepseek}
shift $(( $# > 2 ? 2 : $# ))
EXTRA_ARGS=("$@")

echo "SCRIPT START: $(date)"
echo "SLURM_SUBMIT_DIR=$SLURM_SUBMIT_DIR"

set -eo pipefail

EVAL_DIR="${SLURM_SUBMIT_DIR:?run sbatch from jailbreaks/}"
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


if [[ "$MODEL_REF" == "--list-models" ]] || [[ "$JUDGE" == "--list-models" ]]; then
  mr_eval_print_registered_models
  exit 0
fi

if ! mr_eval_resolve_pretrained_ref "$REPO_ROOT" "$EVAL_DIR" "$MODEL_REF"; then
  exit 1
fi
MODEL="$MR_EVAL_MODEL_PRETRAINED"
MODEL_NAME="${MR_EVAL_MODEL_NAME:-${MR_EVAL_MODEL_ALIAS:-$(basename "$MODEL")}}"

set -a
[ -f "$REPO_ROOT/.env" ] && source "$REPO_ROOT/.env"
[ -f ~/.env ] && source ~/.env
set +a

mkdir -p "$EVAL_DIR/../../logs"

# vLLM fused pipeline: see eval_advbench.sh for the rationale.
export MR_EVAL_REPO_ROOT="$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
unset HF_HUB_CACHE HUGGINGFACE_HUB_CACHE
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"

nvidia-smi

echo "START TIME: $(date)"
echo "Model ref:    $MODEL_REF"
echo "Pretrained:   $MODEL"
echo "Judge:        $JUDGE"
start=$(date +%s)

python run_dan_eval.py \
  model.name="$MODEL_NAME" \
  model.pretrained="$MODEL" \
  judge="$JUDGE" \
  "${EXTRA_ARGS[@]}"

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
