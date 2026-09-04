#!/bin/bash

#SBATCH --account=infra01
# Wall = 2x the pre-2026-09-04 value: OpenRouter admission control on the judge account
# makes judging throughput a shared, account-level ceiling, so a leaf that judges
# thousands of samples can take twice as long when many jobs run at once (4 jobs
# died at 30:20 with 99% judged). See AGENTS.md "Default walls" (2026-09-04).
#SBATCH --time=01:30:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/safety-base-%j.out
#SBATCH --error=logs/safety-base-%j.err
#SBATCH --no-requeue

# Base-Model Safety Evaluation - locuslab/jb-completions
#
# Measures Attack Success Rate (ASR): fraction of jb-completions prompts
# where the model generates a harmful continuation (vLLM + GPT-4o judge).
# Requires OPENAI_API_KEY to be set (sourced from ~/.env).
#
# Usage (run sbatch from safety_base/):
#   sbatch slurm/eval_safety_base.sh                          # default model
#   sbatch slurm/eval_safety_base.sh safelm_1p7b
#   sbatch slurm/eval_safety_base.sh ../train/outputs/my_run/checkpoints
#   sbatch slurm/eval_safety_base.sh alpindale/Llama-3.2-1B --source-filter JailbreakBench
#   sbatch slurm/eval_safety_base.sh --list-models
#
#   $1                    MODEL_REF (registry alias | HF id | checkpoint path)
#   --source-filter <s>   restrict to one jb-completions source
#   key=value ...         extra Hydra overrides forwarded to run_eval.py

MODEL_REF=""
SOURCE_FILTER=""
LIST_MODELS=0
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-filter) SOURCE_FILTER="$2"; shift 2 ;;
    --list-models)   LIST_MODELS=1; shift ;;
    -h|--help)       sed -n '11,24p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*)              echo "Unknown flag: $1" >&2; exit 1 ;;
    *)               if [[ -z "$MODEL_REF" ]]; then MODEL_REF="$1"; else EXTRA_ARGS+=("$1"); fi; shift ;;
  esac
done
MODEL_REF="${MODEL_REF:-safelm_1p7b}"

echo "SCRIPT START: $(date)"
echo "SLURM_SUBMIT_DIR=$SLURM_SUBMIT_DIR"
echo "SLURM_JOB_ID=$SLURM_JOB_ID"

set -eo pipefail

SUBMIT_DIR="${SLURM_SUBMIT_DIR:?SLURM_SUBMIT_DIR is not set - run sbatch from safety_base/}"

if [[ -f "$SUBMIT_DIR/run_eval.py" && -d "$SUBMIT_DIR/conf" ]]; then
  SAFETY_BASE_DIR="$SUBMIT_DIR"
  REPO_ROOT="$(cd "$SAFETY_BASE_DIR/.." && pwd)"
elif [[ -f "$SUBMIT_DIR/safety_base/run_eval.py" && -d "$SUBMIT_DIR/safety_base/conf" ]]; then
  REPO_ROOT="$SUBMIT_DIR"
  SAFETY_BASE_DIR="$REPO_ROOT/safety_base"
else
  echo "Could not locate safety_base from SLURM_SUBMIT_DIR=$SUBMIT_DIR"
  echo "Run from safety_base/: cd safety_base && sbatch slurm/eval_safety_base.sh"
  exit 1
fi

MR_EVAL_COMPONENT_DIR="$SAFETY_BASE_DIR"
cd "$SAFETY_BASE_DIR"

# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_setup_eval_env.sh"

if [[ "$LIST_MODELS" == "1" ]]; then
  mr_eval_print_registered_models
  exit 0
fi

if ! mr_eval_resolve_model_contract "$REPO_ROOT" "$SAFETY_BASE_DIR" "$MODEL_REF"; then
  exit 1
fi
PRETRAINED="$MR_EVAL_RESOLVED_PRETRAINED"
MODEL_NAME="$MR_EVAL_RESOLVED_NAME"

mr_eval_load_dotenv || true

mkdir -p "$SAFETY_BASE_DIR/logs"
nvidia-smi

echo "START TIME: $(date)"
echo "Model ref:  $MODEL_REF"
echo "Pretrained: $PRETRAINED"
echo "Model name: $MODEL_NAME"
echo "Source:     ${SOURCE_FILTER:-all}"
start=$(date +%s)

cmd=(
  python run_eval.py
  model.name="$MODEL_NAME"
  model.pretrained="$PRETRAINED"
)
if [[ -n "$SOURCE_FILTER" ]]; then
  cmd+=(source_filter="$SOURCE_FILTER")
fi
cmd+=("${EXTRA_ARGS[@]}")

"${cmd[@]}"

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
