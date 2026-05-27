#!/bin/bash

#SBATCH --account=a141
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/pez-%j.out
#SBATCH --error=logs/pez-%j.err
#SBATCH --no-requeue

# PEZ (prompt-embedding optimization) evaluation for a single target model.
# Runs the full HarmBench pipeline in local_parallel mode: attack generation ->
# merge -> completions -> classifier ASR -> dynamics plot.
#
# Usage (run sbatch from harmbench/). The harmbench container is REQUIRED:
# without --environment the job lands on bare metal, where python lacks
# huggingface_hub and the chat-template setup fails ("refusing to run").
#   sbatch --environment="$(../slurm/_resolve_env_toml.sh harmbench)" slurm/eval_pez.sh smollm_sft
#   sbatch --environment="$(../slurm/_resolve_env_toml.sh harmbench)" slurm/eval_pez.sh baseline_sft --behaviors ./data/behavior_datasets/harmbench_behaviors_text_test_plain.csv
# See slurm/submit_posttrain_evals.sh (--safety-ablations / --all) for the matrix invocation.
#
#   $1              MODEL (HarmBench model alias from configs/model_configs/models.yaml)
#   --behaviors <p> behaviors CSV (default: 159-behavior test_plain)
#   ...             extra args forwarded to run_pez_eval.py (--num-samples, --temperature, ...)

MODEL=""
BEHAVIORS=./data/behavior_datasets/harmbench_behaviors_text_test_plain.csv
LIST_MODELS=0
PEZ_EVAL_EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --behaviors)   BEHAVIORS="$2"; shift 2 ;;
    --list-models) LIST_MODELS=1; shift ;;
    -h|--help)     sed -n '12,26p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)             if [[ -z "$MODEL" ]]; then MODEL="$1"; else PEZ_EVAL_EXTRA_ARGS+=("$1"); fi; shift ;;
  esac
done
MODEL="${MODEL:-smollm_sft}"

set -eo pipefail

HARMBENCH_DIR="${SLURM_SUBMIT_DIR:?run sbatch from harmbench/}"
REPO_ROOT="$(cd "$HARMBENCH_DIR/.." && pwd)"
cd "$HARMBENCH_DIR"

# Load OPENAI_API_KEY from any of the .env locations the other safety eval
# scripts support (matches em/slurm/eval_em.sh). The v5 RuleBasedJudge step
# at the end requires it.
for _envf in "$REPO_ROOT/.env" "$HARMBENCH_DIR/.env" "${SLURM_SUBMIT_DIR:-}/.env" "$HOME/.env"; do
  # shellcheck disable=SC1090
  [ -f "$_envf" ] && source "$_envf" && break
done

_JUDGE_PROVIDER="${MR_EVAL_JUDGE_PROVIDER:-openrouter}"
_REQUIRED_KEY="OPENAI_API_KEY"
[[ "$_JUDGE_PROVIDER" == "openrouter" ]] && _REQUIRED_KEY="OPENROUTER_API_KEY"
if [ -z "${!_REQUIRED_KEY:-}" ]; then
  echo "$_REQUIRED_KEY is not set (MR_EVAL_JUDGE_PROVIDER=$_JUDGE_PROVIDER); the v5 PEZ judge step will fail." >&2
  echo "Place $_REQUIRED_KEY=... in $REPO_ROOT/.env or pass via --export." >&2
  exit 1
fi

# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_resolve_data_dir.sh"
PEZ_SAVE_DIR="$MR_EVAL_DATA_DIR/logs/clariden/pez"

mkdir -p "$HARMBENCH_DIR/logs" "$PEZ_SAVE_DIR"

# Ray scheduler needs a sane vLLM default and a spawn-based launcher.
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"

# Make the container HF_HOME authoritative for the WHOLE pipeline. This must
# happen before step 1: HarmBench's PEZ attack (step 1) loads the target model
# via transformers in a Ray subprocess, and a personal HF_HUB_CACHE leaking via
# --export=ALL shadows the shared cache, so offline model resolution fails with
# "couldn't connect to huggingface.co ... couldn't find them in the cached files".
# `import mreval` (steps 2+3) also needs PYTHONPATH/MR_EVAL_REPO_ROOT.
export MR_EVAL_REPO_ROOT="$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
unset HF_HUB_CACHE HUGGINGFACE_HUB_CACHE

# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_setup_eval_env.sh"

if [[ "$LIST_MODELS" == "1" ]]; then
  mr_eval_print_registered_models
  exit 0
fi

_ALIAS="$(mr_eval_resolve_alias_for_chat_template "$MODEL")"
if ! mr_eval_setup_chat_template "$_ALIAS"; then
  echo "[chat-template] setup failed for MODEL=$MODEL (alias='$_ALIAS'); refusing to run" >&2
  exit 1
fi

nvidia-smi

echo "START TIME: $(date)"
echo "Model:      $MODEL"
echo "Behaviors:  $BEHAVIORS"
echo "Save dir:   $PEZ_SAVE_DIR"
start=$(date +%s)

# Steps 1 + 1.5 stay on the HarmBench pipeline (PEZ attack optimization + merge).
# Steps 2 (completion generation) + 3 (judging) are fused onto the mreval
# pipeline by run_pez_eval.py: it reads test_cases.json, generates k samples per
# attack prompt with vLLM, judges with the rule judge (DeepSeek by default), and
# writes the mreval per-sample schema. Generation is NOT a separate HarmBench
# step anymore.
PIPELINE=(
  python3 scripts/run_pipeline.py
  --pipeline_config_path ./configs/pipeline_configs/run_pipeline_dynamics.yaml
  --methods PEZ
  --models "$MODEL"
  --behaviors_path "$BEHAVIORS"
  --mode local_parallel
  --max_new_tokens 512
  --base_save_dir "$PEZ_SAVE_DIR"
  --base_log_dir "$PEZ_SAVE_DIR/slurm_logs"
)
if [[ -n "${HARMBENCH_BEHAVIOR_IDS_SUBSET:-}" ]]; then
  PIPELINE+=(--behavior_ids_subset "$HARMBENCH_BEHAVIOR_IDS_SUBSET")
fi
if [[ "${HARMBENCH_OVERWRITE:-False}" == "True" ]]; then
  PIPELINE+=(--overwrite)
fi

# Step 1: generate attack test cases
echo ""
echo "=== Step 1: generate test cases ==="
"${PIPELINE[@]}" --step 1

# Step 1.5: merge per-behavior test cases into a single file
echo ""
echo "=== Step 1.5: merge test cases ==="
"${PIPELINE[@]}" --step 1.5

# Steps 2+3 (fused): generate completions + judge via the mreval pipeline.
# (HF cache / PYTHONPATH env already exported before step 1, above.)
echo ""
echo "=== Steps 2+3 (mreval fused pipeline): generate + judge ==="
TEST_CASES="$PEZ_SAVE_DIR/PEZ/${MODEL}/test_cases/test_cases.json"
if [[ -f "$TEST_CASES" ]]; then
  python3 "$HARMBENCH_DIR/run_pez_eval.py" \
    --model "$MODEL" \
    --test-cases-path "$TEST_CASES" \
    --behaviors-path "$BEHAVIORS" \
    --mreval-output-dir "$MR_EVAL_DATA_DIR/outputs/pez" \
    --judge-provider "$_JUDGE_PROVIDER" \
    "${PEZ_EVAL_EXTRA_ARGS[@]}"
else
  echo "    (no test_cases file at $TEST_CASES — step 1/1.5 may have failed)"
fi

# (The PEZ optimization-loss dynamics view now lives in the dashboard, which
# reads the step-1 logs.json + the mreval per-sample schema at Step 3.)

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
