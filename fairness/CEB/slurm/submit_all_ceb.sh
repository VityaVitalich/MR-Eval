#!/bin/bash

# Submit one CEB eval job per model (fan-out).
# Mirrors harmbench/slurm/submit_all_pez.sh.
#
# Usage (run from fairness/CEB/):
#   bash slurm/submit_all_ceb.sh
#   bash slurm/submit_all_ceb.sh baseline_sft,safelm_sft
#   bash slurm/submit_all_ceb.sh all recognition_s gender
#
# Positional args:
#   $1 MODELS     "all" or comma-separated registry aliases (default: DEFAULT_MODELS)
#   $2 TASK       task / space-list / "all"                 (default: all)
#   $3 ATTRIBUTE  attribute or "all"                        (default: all)
#   $4 TP_SIZE    tensor-parallel size                      (default: 4)

set -eo pipefail

CEB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$CEB_DIR/../.." && pwd)"
cd "$CEB_DIR"

# Default the container dir to this clone's container/. Users can still
# override via `export MR_EVAL_CONTAINER_DIR=...` before running.
export MR_EVAL_CONTAINER_DIR="${MR_EVAL_CONTAINER_DIR:-$REPO_ROOT/container}"

# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_resolve_env_toml.sh"

# Every alias registered in model_registry.sh as of the last update.
# Refresh with:
#   bash -c 'source ../../model_registry.sh && mr_eval_print_registered_models'
#
# Notes for picking a subset (pass on the CLI to override):
#   - "*_base" variants (no `_sft` / `_mixsft` / `_pbsft*` / `_dpo` suffix) are
#     pretrain checkpoints. They give parse_rate ~= 0 on CEB classification
#     tasks (recognition_*, selection_*) — they're only meaningful on the
#     generation tasks (continuation_*, conversation_*).
#   - Use `bash slurm/submit_all_ceb.sh <subset>` to run a curated list.

# 15 base / pretrain models
BASE_MODELS="\
baseline,baseline_500b,baseline_filtered,\
safelm,smollm,llama32_1B,\
epe_1p_bce,epe_1p_nobce,epe_1p_nobce_noctx,epe_1p_nobce_refend,\
epe_3p_bce,epe_3p_nobce,epe_3p_nobce_noctx,\
sdsp_judge_0_1,sdsp_judge_1_1"

# 59 instruct / SFT / DPO checkpoints
INSTRUCT_MODELS="\
baseline_sft,baseline_filtered_sft,baseline_500b_sft,baseline_dpo,\
baseline_mixsft,baseline_filtered_mixsft,baseline_500b_mixsft,\
baseline_pbsft,baseline_pbsft3,baseline_pbucsft,\
baseline_filtered_pbsft,baseline_filtered_pbsft3,baseline_filtered_pbucsft,\
baseline_500b_pbsft,\
safelm_sft,safelm_pbsft3,smollm_sft,\
epe_1p_bce_sft,epe_1p_bce_sft_def,epe_1p_bce_mixsft,epe_1p_bce_mixsft_def,\
epe_1p_bce_mixsft_nonl,epe_1p_bce_pbsft3,\
epe_1p_nobce_sft,epe_1p_nobce_sft_def,epe_1p_nobce_mixsft,epe_1p_nobce_mixsft_def,\
epe_1p_nobce_mixsft_nonl,epe_1p_nobce_mixsft_cato,\
epe_1p_nobce_pbsft,epe_1p_nobce_pbsft3,\
epe_1p_nobce_noctx_pbsft,epe_1p_nobce_noctx_pbsft3,epe_1p_nobce_noctx_pbucsft,\
epe_1p_nobce_refend_mixsft_def,epe_1p_nobce_refend_mixsft_nonl,\
epe_1p_nobce_refend_pbsft3,epe_1p_nobce_refendtr_pbsft3,\
epe_3p_bce_sft,epe_3p_bce_sft_def,epe_3p_bce_mixsft,epe_3p_bce_mixsft_def,\
epe_3p_bce_mixsft_nonl,epe_3p_bce_pbsft3,\
epe_3p_nobce_sft,epe_3p_nobce_sft_def,epe_3p_nobce_mixsft,epe_3p_nobce_mixsft_def,\
epe_3p_nobce_mixsft_nonl,epe_3p_nobce_mixsft_cato,\
epe_3p_nobce_pbsft,epe_3p_nobce_pbsft3,\
epe_3p_nobce_noctx_pbsft,epe_3p_nobce_noctx_pbsft3,epe_3p_nobce_noctx_pbucsft,\
sdsp_judge_0_1_mixsft,sdsp_judge_0_1_pbsft3,\
sdsp_judge_1_1_mixsft,sdsp_judge_1_1_pbsft3"

DEFAULT_MODELS="$INSTRUCT_MODELS,$BASE_MODELS"

MODELS=${1:-all}
TASK=${2:-all}
ATTRIBUTE=${3:-all}
TP_SIZE=${4:-4}

[[ "$MODELS" == "all" ]] && MODELS="$DEFAULT_MODELS"

mkdir -p logs

IFS=',' read -ra MODEL_LIST <<< "$MODELS"
echo "Submitting CEB for ${#MODEL_LIST[@]} models"

for model in "${MODEL_LIST[@]}"; do
  model="$(echo "$model" | xargs)"
  [[ -z "$model" ]] && continue
  sbatch --environment="$(mr_eval_env_toml train)" \
    --export="ALL,MR_EVAL_MODEL_NAME=$model" \
    --job-name="ceb_$model" \
    slurm/eval_ceb.sh "$model" "$TASK" "$ATTRIBUTE" "$TP_SIZE"
done
