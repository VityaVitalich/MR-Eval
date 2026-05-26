#!/bin/bash

#SBATCH --account=a141
#SBATCH --time=01:30:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/jailbreaks-pap-%j.out
#SBATCH --error=logs/jailbreaks-pap-%j.err
#SBATCH --no-requeue

# Persuasive Adversarial Prompt (PAP) evaluation (vLLM fused pipeline + k-sampling).
# Submit with a vLLM-capable container, run sbatch from jailbreaks/:
#   sbatch --environment=<repo>/container/harmbench.toml slurm/eval_pap.sh
#   sbatch ... slurm/eval_pap.sh alpindale/Llama-3.2-1B-Instruct deepseek \
#       data/persuasive_jailbreak/adv_bench_sub_llama2.jsonl
#   sbatch ... slurm/eval_pap.sh baseline_sft deepseek "" \
#       num_samples=5 decoding.strategy=sampled decoding.temperature=1.0 decoding.top_p=0.95
#
# $1 MODEL     HF pretrained id or registry alias
# $2 JUDGE     judge group: gpt4o | deepseek
# $3 PAP_FILE  optional pap_file override ("" to skip)
# $4.. extra Hydra overrides (num_samples, decoding.*, prompt_format=, run_tag=)

MODEL=${1:-"alpindale/Llama-3.2-1B-Instruct"}
JUDGE=${2:-deepseek}
PAP_FILE=${3:-}
shift $(( $# > 3 ? 3 : $# ))
EXTRA_ARGS=("$@")

echo "SCRIPT START: $(date)"
echo "SLURM_SUBMIT_DIR=$SLURM_SUBMIT_DIR"

set -eo pipefail

EVAL_DIR="${SLURM_SUBMIT_DIR:?run sbatch from jailbreaks/}"
REPO_ROOT="$(cd "$EVAL_DIR/.." && pwd)"
cd "$EVAL_DIR"

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

# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_setup_eval_env.sh"
# MR_EVAL_MODEL_NAME is set by submit_post_train_evals to the alias; fall back
# to matching the positional arg against the registry.
_ALIAS="$(mr_eval_resolve_alias_for_chat_template "$MODEL")"
if ! mr_eval_setup_chat_template "$_ALIAS"; then
  echo "[chat-template] setup failed for MODEL=$MODEL (alias='$_ALIAS'); refusing to run" >&2
  exit 1
fi

nvidia-smi

echo "START TIME: $(date)"
echo "Model:    $MODEL"
echo "Judge:    $JUDGE"
echo "PAP file: ${PAP_FILE:-default from conf/pap.yaml}"
start=$(date +%s)

cmd=(
  python run_pap_eval.py
  model.pretrained="$MODEL"
  judge="$JUDGE"
)

if [ -n "$PAP_FILE" ]; then
  cmd+=(pap_file="$PAP_FILE")
fi

# Forward any extra Hydra overrides (e.g. prompt_format=tmplabl, run_tag=...)
cmd+=("${EXTRA_ARGS[@]}")

"${cmd[@]}"

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
