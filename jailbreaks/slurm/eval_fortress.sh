#!/bin/bash

#SBATCH --account=infra01
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/fortress-%j.out
#SBATCH --error=logs/fortress-%j.err
#SBATCH --no-requeue

# FORTRESS evaluation (vLLM fused pipeline + k-sampling). Uses the FORTRESS
# public adversarial-prompt set scored with MR-Eval's own rule judge (NOT the
# FORTRESS instance-rubric autograder). Submit with a vLLM-capable container,
# run sbatch from jailbreaks/:
#   sbatch --environment=<repo>/container/harmbench.toml slurm/eval_fortress.sh baseline_sft
#   sbatch ... slurm/eval_fortress.sh llama32_1B_instruct --judge deepseek
#   sbatch ... slurm/eval_fortress.sh baseline_sft --judge deepseek \
#       decoding.strategy=greedy num_samples=1   # override the k=10 sampled default
#   sbatch slurm/eval_fortress.sh --list-models
#
#   $1            MODEL_REF (registry alias | HF id | checkpoint path)
#   --judge <g>   judge group: gpt4o | deepseek   (default: deepseek)
#   key=value ... extra Hydra overrides (num_samples, decoding.*, limit=...)

MODEL_REF=""
JUDGE=deepseek
LIST_MODELS=0
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --judge)       JUDGE="$2"; shift 2 ;;
    --list-models) LIST_MODELS=1; shift ;;
    -h|--help)     sed -n '11,25p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*)            echo "Unknown flag: $1" >&2; exit 1 ;;
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

# vLLM fused pipeline needs `import mreval` + the shared root conf (searchpath),
# and the shared infra01 HF cache to be authoritative (a personal HF_HUB_CACHE
# leaking via --export=ALL would shadow the container HF_HOME, breaking offline
# model resolution).
mr_eval_export_repo_runtime "$REPO_ROOT"
unset HF_HUB_CACHE HUGGINGFACE_HUB_CACHE
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"

nvidia-smi

echo "START TIME: $(date)"
echo "Model ref:  $MODEL_REF"
echo "Pretrained: $MODEL"
echo "Judge:      $JUDGE"
start=$(date +%s)

python run_fortress_eval.py \
  model.name="$MODEL_NAME" \
  model.pretrained="$MODEL" \
  judge="$JUDGE" \
  "${EXTRA_ARGS[@]}"

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
