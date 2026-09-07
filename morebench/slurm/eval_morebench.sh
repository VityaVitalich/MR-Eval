#!/bin/bash

#SBATCH --account=infra01
#SBATCH --time=00:20:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/morebench-%j.out
#SBATCH --error=logs/morebench-%j.err
#SBATCH --no-requeue

# MoReBench Stage 1 — generation (Chiu et al., 2025 — arXiv:2510.16380).
#
# Forced free-form moral-reasoning bench. This job ONLY generates the model's
# responses (GPU half). Judging + scoring run separately against the Swiss-AI
# gateway (CPU) — no judge model on this node:
#   sbatch --environment=<repo>/container/train.toml slurm/eval_morebench.sh baseline_sft
#   sbatch ... slurm/eval_morebench.sh llama32_1B_instruct num_scenarios=100
#   sbatch ... slurm/eval_morebench.sh baseline_sft dataset_subset=theory   # MoReBench-Theory
#   sbatch slurm/eval_morebench.sh --list-models
#
# Then (login node / local Mac, with $SWISSAI_BASE_URL + $SWISSAI_API_KEY):
#   python judge_and_score.py generations_file=<...>/morebench_<model>_<ts>.jsonl
#
#   $1            MODEL_REF (registry alias | HF id | checkpoint path)
#   --list-models print the registry and exit
#   key=value ... extra Hydra overrides forwarded to generate.py

MODEL_REF=""
LIST_MODELS=0
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --list-models) LIST_MODELS=1; shift ;;
    -h|--help)     sed -n '11,21p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*)            echo "Unknown flag: $1" >&2; exit 1 ;;
    *)             if [[ -z "$MODEL_REF" ]]; then MODEL_REF="$1"; else EXTRA_ARGS+=("$1"); fi; shift ;;
  esac
done
MODEL_REF="${MODEL_REF:-baseline_sft}"

echo "SCRIPT START: $(date)"
echo "SLURM_SUBMIT_DIR=$SLURM_SUBMIT_DIR"

set -eo pipefail

EVAL_DIR="${SLURM_SUBMIT_DIR:?run sbatch from morebench/}"
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

# The eval container pins HF_HUB_OFFLINE=1 in its [env] (masks any sbatch
# --export of HF_HUB_OFFLINE). To let HF fetch live — both the chat-template
# jinja (below) and the morebench dataset (in generate.py) — submit with
#   --export=ALL,MOREBENCH_HF_ONLINE=1
# (a custom toggle the container does NOT mask). Set BEFORE chat-template setup
# so an un-precached jinja can still be fetched. Until both are added to
# precache_models.sh.
if [[ "${MOREBENCH_HF_ONLINE:-0}" == "1" ]]; then
  export HF_HUB_OFFLINE=0 HF_DATASETS_OFFLINE=0
  echo "[morebench] HF online fetch enabled (HF_HUB_OFFLINE=0)"
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

# Keep the shared infra01 HF cache authoritative (a personal HF_HUB_CACHE leaking
# via --export=ALL would shadow the container HF_HOME and break offline model/
# tokenizer + dataset resolution).
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

python generate.py \
  model.name="$MODEL_NAME" \
  model.pretrained="$MODEL" \
  "${EXTRA_ARGS[@]}"

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
