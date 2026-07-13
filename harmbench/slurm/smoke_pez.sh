#!/bin/bash

#SBATCH --account=infra01
#SBATCH --partition=debug
#SBATCH --time=00:20:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --output=logs/pez-smoke-%j.out
#SBATCH --error=logs/pez-smoke-%j.err
#SBATCH --no-requeue

# Smoke for the PEZ steps-2+3 fused-pipeline migration. Runs run_pez_eval.py
# (generate + judge) on an EXISTING test_cases.json (steps 1/1.5 already done),
# so no 2h attack-optimization rerun. Run inside a vLLM-capable container, from
# the repo root:
#
#   MR_EVAL_DATA_DIR=/capstor/store/cscs/swissai/a141/mr_evals_jminder \
#     sbatch --environment=/users/jminder/repositories/MR-Eval/container/harmbench.toml \
#       harmbench/slurm/smoke_pez.sh baseline_filtered_pbsft3 \
#       /capstor/.../mr_evals_vvm/logs/clariden/pez/PEZ/baseline_filtered_pbsft3/test_cases/test_cases.json \
#       --limit 10
#
# $1   MODEL alias (must exist in harmbench/configs/model_configs/models.yaml)
# $2   path to an existing test_cases.json
# $3.. extra run_pez_eval.py args (--limit, --num-samples, --temperature, ...)

set -eo pipefail

REPO_ROOT="${SLURM_SUBMIT_DIR:?run sbatch from the repo root}"
cd "$REPO_ROOT/harmbench"
mkdir -p "$REPO_ROOT/logs"

MODEL="${1:?usage: smoke_pez.sh <model_alias> <test_cases.json> [args...]}"
TEST_CASES="${2:?need a test_cases.json path}"
shift 2

export MR_EVAL_REPO_ROOT="$REPO_ROOT"
export MR_EVAL_DATA_DIR="${MR_EVAL_DATA_DIR:-/capstor/store/cscs/swissai/infra01/vvmoskvoretskii/mr_evals_vvm}"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
unset HF_HUB_CACHE HUGGINGFACE_HUB_CACHE
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"
if [ -f "$REPO_ROOT/.env" ]; then set -a; source "$REPO_ROOT/.env"; set +a; fi

echo "START: $(date)"
nvidia-smi || true

python3 run_pez_eval.py \
  --model "$MODEL" \
  --test-cases-path "$TEST_CASES" \
  --behaviors-path ./data/behavior_datasets/harmbench_behaviors_text_test_plain.csv \
  --mreval-output-dir "$MR_EVAL_DATA_DIR/outputs/pez" \
  --judge-provider openrouter \
  "$@"

echo "FINISH: $(date)"
