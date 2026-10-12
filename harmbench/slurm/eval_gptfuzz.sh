#!/bin/bash

#SBATCH --account=infra01
# Wall = 2x the pre-2026-09-04 value: OpenRouter admission control on the judge account
# makes judging throughput a shared, account-level ceiling, so a leaf that judges
# thousands of samples can take twice as long when many jobs run at once (4 jobs
# died at 30:20 with 99% judged). See AGENTS.md "Default walls" (2026-09-04).
#SBATCH --time=08:00:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/gptfuzz-%j.out
#SBATCH --error=logs/gptfuzz-%j.err
#SBATCH --no-requeue

# GPTFuzz (Yu et al., 2023) evaluation for a single target model: template fuzzing seeded from
# GPTFuzzer.csv, mutated by gpt-3.5-turbo (through OpenRouter), success scored by the
# hubert233/GPTFuzz RoBERTa judge. One target GPU per behavior chunk.
# Runs the full HarmBench pipeline in local_parallel mode: attack generation ->
# merge -> completions -> classifier ASR -> dynamics plot.
#
# Usage (run sbatch from harmbench/). The harmbench container is REQUIRED:
# without --environment the job lands on bare metal, where python lacks
# huggingface_hub and the chat-template setup fails ("refusing to run").
#   sbatch --environment="$(../slurm/_resolve_env_toml.sh harmbench)" slurm/eval_gptfuzz.sh smollm_sft
#   sbatch --environment="$(../slurm/_resolve_env_toml.sh harmbench)" slurm/eval_gptfuzz.sh baseline_sft --behaviors ./data/behavior_datasets/harmbench_behaviors_text_test_plain.csv
# See slurm/submit_posttrain_evals.sh (--safety-ablations / --all) for the matrix invocation.
#
#   $1              MODEL (HarmBench model alias from configs/model_configs/models.yaml)
#   --behaviors <p> behaviors CSV (default: 159-behavior test_plain)
#   ...             extra args forwarded to run_pez_eval.py --benchmark gptfuzz (--num-samples, --temperature, ...)

MODEL=""
BEHAVIORS=./data/behavior_datasets/harmbench_behaviors_text_test_plain.csv
LIST_MODELS=0
REUSE_TEST_CASES=0
EVAL_EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --behaviors)   BEHAVIORS="$2"; shift 2 ;;
    --list-models) LIST_MODELS=1; shift ;;
    # Skip the GPTFuzz optimization (steps 1 + 1.5) and re-run only the
    # generate-completions + judge stage on the existing merged test_cases.json.
    # Use this to re-emit GPTFuzz under a new sampling strategy (e.g. the new
    # k5/t0.7 default) without paying for gradient optimization again.
    --reuse-test-cases) REUSE_TEST_CASES=1; shift ;;
    -h|--help)     sed -n '12,26p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)             if [[ -z "$MODEL" ]]; then MODEL="$1"; else EVAL_EXTRA_ARGS+=("$1"); fi; shift ;;
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
  echo "$_REQUIRED_KEY is not set (MR_EVAL_JUDGE_PROVIDER=$_JUDGE_PROVIDER); the v5 judge step will fail." >&2
  echo "Place $_REQUIRED_KEY=... in $REPO_ROOT/.env or pass via --export." >&2
  exit 1
fi

# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_resolve_data_dir.sh"
# Both output roots are env-overridable so a run can be parked in a side tree
# instead of overwriting the canonical one. A re-run clobbers BOTH: the
# provenance-named mreval JSON (judge x sampling is unchanged by a prompt-side
# fix, so the filename is identical) and the intermediate GPTFuzz artifacts +
# legacy summary under GPTFuzz/<alias>/. Needed when a change alters the prompts
# rather than the decoding, e.g. the 2026-07-30 BOS-strip fix, where the
# pre-fix numbers have to stay readable to measure the delta.
GPTFUZZ_SAVE_DIR="${GPTFUZZ_SAVE_DIR:-$MR_EVAL_DATA_DIR/logs/clariden/gptfuzz}"
GPTFUZZ_MREVAL_OUTPUT_DIR="${GPTFUZZ_MREVAL_OUTPUT_DIR:-$MR_EVAL_DATA_DIR/outputs/gptfuzz}"

mkdir -p "$HARMBENCH_DIR/logs" "$GPTFUZZ_SAVE_DIR" "$GPTFUZZ_MREVAL_OUTPUT_DIR"

# Ray scheduler needs a sane vLLM default and a spawn-based launcher.
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"

# Make the container HF_HOME authoritative for the WHOLE pipeline. This must
# happen before step 1: HarmBench's GPTFuzz attack (step 1) loads the target model
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
echo "Save dir:   $GPTFUZZ_SAVE_DIR"
start=$(date +%s)

# Steps 1 + 1.5 stay on the HarmBench pipeline (GPTFuzz attack optimization + merge).
# Steps 2 (completion generation) + 3 (judging) are fused onto the mreval
# pipeline by run_pez_eval.py: it reads test_cases.json, generates k samples per
# attack prompt with vLLM, judges with the rule judge (DeepSeek by default), and
# writes the mreval per-sample schema. Generation is NOT a separate HarmBench
# step anymore.
PIPELINE=(
  python3 scripts/run_pipeline.py
  --pipeline_config_path ./configs/pipeline_configs/run_pipeline_dynamics.yaml
  --methods GPTFuzz
  --models "$MODEL"
  --behaviors_path "$BEHAVIORS"
  --mode local_parallel
  --max_new_tokens 512
  --base_save_dir "$GPTFUZZ_SAVE_DIR"
  --base_log_dir "$GPTFUZZ_SAVE_DIR/slurm_logs"
)
if [[ -n "${HARMBENCH_BEHAVIOR_IDS_SUBSET:-}" ]]; then
  PIPELINE+=(--behavior_ids_subset "$HARMBENCH_BEHAVIOR_IDS_SUBSET")
fi
if [[ "${HARMBENCH_OVERWRITE:-False}" == "True" ]]; then
  PIPELINE+=(--overwrite)
fi

if [[ "$REUSE_TEST_CASES" == "1" ]]; then
  echo ""
  echo "=== Steps 1 + 1.5 SKIPPED (--reuse-test-cases): reusing existing optimized test_cases.json ==="
else
  # Step 1: generate attack test cases
  echo ""
  echo "=== Step 1: generate test cases ==="
  # Mutator through OpenRouter (step 1 only; the mreval judge below has its own provider config).
  # Each fuzzing iteration makes one mutation call (<=100 per behavior; stops at the first success).
  export OPENAI_API_KEY="${OPENROUTER_API_KEY:?GPTFuzz mutator needs OPENROUTER_API_KEY}"
  export OPENAI_BASE_URL=https://openrouter.ai/api/v1 GPTFUZZ_MUTATOR_MODEL="${GPTFUZZ_MUTATOR_MODEL:-openai/gpt-3.5-turbo}"
  "${PIPELINE[@]}" --step 1

  # Step 1.5: merge per-behavior test cases into a single file
  echo ""
  echo "=== Step 1.5: merge test cases ==="
  "${PIPELINE[@]}" --step 1.5
fi

# Steps 2+3 (fused): generate completions + judge via the mreval pipeline.
# (HF cache / PYTHONPATH env already exported before step 1, above.)
echo ""
echo "=== Steps 2+3 (mreval fused pipeline): generate + judge ==="
TEST_CASES="$GPTFUZZ_SAVE_DIR/GPTFuzz/${MODEL}/test_cases/test_cases.json"
if [[ -f "$TEST_CASES" ]]; then
  python3 "$HARMBENCH_DIR/run_pez_eval.py" \
    --benchmark gptfuzz \
    --model "$MODEL" \
    --test-cases-path "$TEST_CASES" \
    --behaviors-path "$BEHAVIORS" \
    --mreval-output-dir "$GPTFUZZ_MREVAL_OUTPUT_DIR" \
    --judge-provider "$_JUDGE_PROVIDER" \
    "${EVAL_EXTRA_ARGS[@]}"
else
  echo "    (no test_cases file at $TEST_CASES — step 1/1.5 may have failed)"
fi


end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
