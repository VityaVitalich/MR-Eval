#!/bin/bash

#SBATCH --account=infra01
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/jailbreaks-pap-%j.out
#SBATCH --error=logs/jailbreaks-pap-%j.err
#SBATCH --no-requeue

# Persuasive Adversarial Prompt (PAP) evaluation (vLLM fused pipeline + k-sampling).
# Submit with a vLLM-capable container, run sbatch from jailbreaks/:
#   sbatch --environment=<repo>/container/harmbench.toml slurm/eval_pap.sh baseline_sft
#   sbatch ... slurm/eval_pap.sh alpindale/Llama-3.2-1B-Instruct --judge deepseek \
#       --pap-file data/persuasive_jailbreak/adv_bench_sub_llama2.jsonl
#   sbatch ... slurm/eval_pap.sh baseline_sft --judge deepseek \
#       decoding.strategy=greedy num_samples=1   # override the k=10 sampled default
#   sbatch slurm/eval_pap.sh --list-models
#
#   $1              MODEL_REF (registry alias | HF id | checkpoint path)
#   --judge <g>     judge group: gpt4o | deepseek   (default: deepseek)
#   --pap-file <p>  optional pap_file override
#   key=value ...   extra Hydra overrides (num_samples, decoding.*, prompt_format=, run_tag=)

MODEL_REF=""
JUDGE=deepseek
PAP_FILE=""
LIST_MODELS=0
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --judge)       JUDGE="$2"; shift 2 ;;
    --pap-file)    PAP_FILE="$2"; shift 2 ;;
    --list-models) LIST_MODELS=1; shift ;;
    -h|--help)     sed -n '11,25p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*)            echo "Unknown flag: $1" >&2; exit 1 ;;
    *)             if [[ -z "$MODEL_REF" ]]; then MODEL_REF="$1"; else EXTRA_ARGS+=("$1"); fi; shift ;;
  esac
done
MODEL_REF="${MODEL_REF:-alpindale/Llama-3.2-1B-Instruct}"

echo "SCRIPT START: $(date)"
echo "SLURM_SUBMIT_DIR=$SLURM_SUBMIT_DIR"

set -eo pipefail

EVAL_DIR="${SLURM_SUBMIT_DIR:?run sbatch from jailbreaks/}"
REPO_ROOT="$(cd "$EVAL_DIR/.." && pwd)"
MR_EVAL_COMPONENT_DIR="$EVAL_DIR"
cd "$EVAL_DIR"

# Load .env early so OPENAI/OPENROUTER keys are present before the run.
set -a
# shellcheck disable=SC1091
[ -f "$REPO_ROOT/.env" ] && source "$REPO_ROOT/.env"
# shellcheck disable=SC1090
[ -f "$HOME/.env" ] && source "$HOME/.env"
set +a

mkdir -p "$REPO_ROOT/logs"

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

if [[ "$LIST_MODELS" == "1" ]]; then
  mr_eval_print_registered_models
  exit 0
fi

_ALIAS="$(mr_eval_resolve_alias_for_chat_template "$MODEL_REF")"
if ! mr_eval_setup_chat_template "$_ALIAS"; then
  echo "[chat-template] setup failed for MODEL_REF=$MODEL_REF (alias='$_ALIAS'); refusing to run" >&2
  exit 1
fi

# Resolve a registry alias to its pretrained id + stamp the canonical label as
# model.name (without this an alias was passed straight to model.pretrained and
# failed to load, and outputs were named by the HF basename, not the alias).
if ! mr_eval_resolve_model_contract "$REPO_ROOT" "$EVAL_DIR" "$MODEL_REF"; then
  exit 1
fi
MODEL="$MR_EVAL_RESOLVED_PRETRAINED"
MODEL_NAME="$MR_EVAL_RESOLVED_NAME"

nvidia-smi

echo "START TIME: $(date)"
echo "Model:    $MODEL"
echo "Name:     $MODEL_NAME"
echo "Judge:    $JUDGE"
echo "PAP file: ${PAP_FILE:-default from conf/pap.yaml}"
start=$(date +%s)

cmd=(
  python run_pap_eval.py
  model.name="$MODEL_NAME"
  model.pretrained="$MODEL"
  judge="$JUDGE"
)
if [ -n "$PAP_FILE" ]; then
  cmd+=(pap_file="$PAP_FILE")
fi
cmd+=("${EXTRA_ARGS[@]}")

"${cmd[@]}"

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
