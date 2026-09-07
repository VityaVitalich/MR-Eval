#!/bin/bash

#SBATCH --account=infra01
# Wall = 2x the pre-2026-09-04 value: OpenRouter admission control on the judge account
# makes judging throughput a shared, account-level ceiling, so a leaf that judges
# thousands of samples can take twice as long when many jobs run at once (4 jobs
# died at 30:20 with 99% judged). See AGENTS.md "Default walls" (2026-09-04).
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/airisk-%j.out
#SBATCH --error=logs/airisk-%j.err
#SBATCH --no-requeue

# AIRiskDilemmas / LitmusValues evaluation (Chiu et al., 2025 — arXiv:2505.14633).
#
# Forced-choice values bench: the model picks "Action 1"/"Action 2" for each
# dilemma; both generation+parse AND logprob elicitation run in one pass.
# Scoring (value Elo + risky-choice rates) is fully local — no LLM judge, no
# API spend. Needs a vLLM-capable container; run sbatch from airisk/:
#   sbatch --environment=<repo>/container/train.toml slurm/eval_airisk.sh baseline_sft
#   sbatch ... slurm/eval_airisk.sh llama32_1B_instruct dataset_subset=model_eval
#   sbatch ... slurm/eval_airisk.sh baseline_sft num_dilemmas=500   # smaller set
#   sbatch slurm/eval_airisk.sh --list-models
#
#   $1            MODEL_REF (registry alias | HF id | checkpoint path)
#   --list-models print the registry and exit
#   key=value ... extra Hydra overrides forwarded to run_eval.py

MODEL_REF=""
LIST_MODELS=0
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --list-models) LIST_MODELS=1; shift ;;
    -h|--help)     sed -n '11,23p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*)            echo "Unknown flag: $1" >&2; exit 1 ;;
    *)             if [[ -z "$MODEL_REF" ]]; then MODEL_REF="$1"; else EXTRA_ARGS+=("$1"); fi; shift ;;
  esac
done
MODEL_REF="${MODEL_REF:-baseline_sft}"

echo "SCRIPT START: $(date)"
echo "SLURM_SUBMIT_DIR=$SLURM_SUBMIT_DIR"

set -eo pipefail

EVAL_DIR="${SLURM_SUBMIT_DIR:?run sbatch from airisk/}"
REPO_ROOT="$(cd "$EVAL_DIR/.." && pwd)"
MR_EVAL_COMPONENT_DIR="$EVAL_DIR"
cd "$EVAL_DIR"

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

mr_eval_load_dotenv || true

mkdir -p "$REPO_ROOT/logs"

# import mreval (resolve_cached_hf_model_path); keep the shared infra01 HF cache
# authoritative (a personal HF_HUB_CACHE leaking via --export=ALL would shadow
# the container HF_HOME and break offline model/tokenizer resolution).
mr_eval_export_repo_runtime "$REPO_ROOT"
unset HF_HUB_CACHE HUGGINGFACE_HUB_CACHE
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"

nvidia-smi

echo "START TIME: $(date)"
echo "Model ref:  $MODEL_REF"
echo "Pretrained: $MODEL"
echo "Model name: $MODEL_NAME"
start=$(date +%s)

python run_eval.py \
  model.name="$MODEL_NAME" \
  model.pretrained="$MODEL" \
  "${EXTRA_ARGS[@]}"

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
