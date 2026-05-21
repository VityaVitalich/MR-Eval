#!/bin/bash

#SBATCH --account=a141
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/ceb-%j.out
#SBATCH --error=logs/ceb-%j.err
#SBATCH --no-requeue

# CEB fairness evaluation for one target model.
# Writes generations + per-attribute scores to ./outputs/fairness_ceb/<model>/.
#
# Usage (run sbatch from fairness/CEB/):
#   sbatch --environment="$(bash ../../slurm/_resolve_env_toml.sh train)" \
#          slurm/eval_ceb.sh baseline_sft
#   sbatch --environment=... slurm/eval_ceb.sh baseline_sft recognition_s gender
#   sbatch --environment=... slurm/eval_ceb.sh baseline_sft all all 1
#
# Positional args (all optional):
#   $1 MODEL      registry alias or HF id    (default: baseline_sft)
#   $2 TASK       task / space-list / "all"  (default: all)
#   $3 ATTRIBUTE  attribute or "all"         (default: all)
#   $4 TP_SIZE    tensor-parallel size       (default: 4)

MODEL=${1:-baseline_sft}
TASK=${2:-all}
ATTRIBUTE=${3:-all}
TP_SIZE=${4:-4}

set -eo pipefail

CEB_DIR="${SLURM_SUBMIT_DIR:?run sbatch from fairness/CEB/}"
REPO_ROOT="$(cd "$CEB_DIR/../.." && pwd)"
cd "$CEB_DIR"
mkdir -p "$CEB_DIR/logs"

# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_setup_eval_env.sh"

_ALIAS="$(mr_eval_resolve_alias_for_chat_template "$MODEL")"
if ! mr_eval_setup_chat_template "$_ALIAS"; then
  echo "[chat-template] setup failed for MODEL=$MODEL" >&2
  exit 1
fi

if mr_eval_registry_has_alias "$MODEL"; then
  mr_eval_resolve_pretrained_ref "$REPO_ROOT" "$CEB_DIR" "$MODEL" || exit 1
  MODEL_PATH="$MR_EVAL_MODEL_PRETRAINED"
  MODEL_NAME="${MR_EVAL_MODEL_NAME:-$MODEL}"
else
  MODEL_PATH="$(mr_eval_normalize_model_path "$CEB_DIR" "$MODEL")"
  MODEL_NAME="${MR_EVAL_MODEL_NAME:-$(basename "$MODEL_PATH")}"
fi

nvidia-smi

echo "START TIME: $(date)"
echo "Model:      $MODEL  ($MODEL_PATH)"
echo "Task:       $TASK"
echo "Attribute:  $ATTRIBUTE"
echo "TP size:    $TP_SIZE"
echo "Save dir:   ./outputs/fairness_ceb/$MODEL_NAME"
start=$(date +%s)

read -r -a TASK_ARR <<< "$TASK"

python3 run_ceb_eval.py \
  --task "${TASK_ARR[@]}" \
  --attribute "$ATTRIBUTE" \
  --model-path "$MODEL_PATH" \
  --model-name "$MODEL_NAME" \
  --tp "$TP_SIZE" \
  --max-model-len 2048 \
  --output_dir ./outputs/fairness_ceb

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start))s"
