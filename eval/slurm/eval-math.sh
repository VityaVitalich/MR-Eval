#!/bin/bash

#SBATCH --account=a141
#SBATCH --time=00:10:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/eval-math-%j.out
#SBATCH --error=logs/eval-math-%j.err
#SBATCH --no-requeue

# MR-Eval math evaluation in the non-Hydra image.
#
# Uses accelerate data parallelism: 4 independent model copies, each processes
# 1/4 of each task's samples -> ~4x throughput vs single GPU.
#
# Usage (run sbatch from eval/):
#   sbatch slurm/eval-math.sh                          # default model
#   sbatch slurm/eval-math.sh smollm_1p7b_sft
#   sbatch slurm/eval-math.sh ../train/outputs/my_run/checkpoints --tasks sft_math
#   sbatch slurm/eval-math.sh --list-models
#
#   $1            MODEL_REF (registry alias | HF id | checkpoint path)
#   --tasks <g>   math task group (default: sft_math)
#   ...           extra args forwarded to run_math.py (argparse)

MODEL_REF=""
TASKS=sft_math
LIST_MODELS=0
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tasks)       TASKS="$2"; shift 2 ;;
    --list-models) LIST_MODELS=1; shift ;;
    -h|--help)     sed -n '12,22p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)             if [[ -z "$MODEL_REF" ]]; then MODEL_REF="$1"; else EXTRA_ARGS+=("$1"); fi; shift ;;
  esac
done
MODEL_REF="${MODEL_REF:-smollm_1p7b_sft}"

echo "SCRIPT START: $(date)"
echo "SLURM_SUBMIT_DIR=$SLURM_SUBMIT_DIR"
echo "SLURM_JOB_ID=$SLURM_JOB_ID"

set -eo pipefail

EVAL_DIR="${SLURM_SUBMIT_DIR:?SLURM_SUBMIT_DIR is not set - run sbatch from eval/}"
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

if ! mr_eval_resolve_model_contract "$REPO_ROOT" "$EVAL_DIR" "$MODEL_REF"; then
  exit 1
fi
PRETRAINED="$MR_EVAL_RESOLVED_PRETRAINED"
MODEL_NAME="$MR_EVAL_RESOLVED_NAME"

mr_eval_load_dotenv || true

mkdir -p "$REPO_ROOT/logs"
nvidia-smi

echo "START TIME: $(date)"
echo "Tasks:      $TASKS"
echo "Model ref:  $MODEL_REF"
echo "Pretrained: $PRETRAINED"
echo "Model name: $MODEL_NAME"
echo "Num GPUs:   4 (data parallel)"

start=$(date +%s)

accelerate launch \
  --multi_gpu \
  --num_processes 4 \
  --num_machines 1 \
  --mixed_precision no \
  --dynamo_backend no \
  "$EVAL_DIR/run_math.py" \
    --tasks "$TASKS" \
    --model-name "$MODEL_NAME" \
    --model-pretrained "$PRETRAINED" \
    --batch-size 16 \
    "${EXTRA_ARGS[@]}"

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
