#!/bin/bash

#SBATCH --account=a141
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/eval-em-%j.out
#SBATCH --error=logs/eval-em-%j.err
#SBATCH --no-requeue

# Emergent Misalignment — Evaluation
#
# Generates completions and judges them for misalignment.
# Requires OPENAI_API_KEY (or OPENROUTER_API_KEY) in environment.
#
# Usage (run sbatch from em/):
#   sbatch slurm/eval_em.sh smollm_1p7b_sft
#   sbatch slurm/eval_em.sh meta-llama/Llama-3.2-1B
#   sbatch slurm/eval_em.sh ../train/outputs/my_run/checkpoints --judge-mode classify
#   sbatch slurm/eval_em.sh smollm_1p7b_sft --questions questions/preregistered_evals.yaml --n-per-question 100
#   sbatch slurm/eval_em.sh --models smollm_1p7b_base,llama32_1B_instruct
#   sbatch slurm/eval_em.sh --list-models
#
#   $1                   MODEL_REF (registry alias | HF id | checkpoint path | EM conf/model name)
#   --judge-mode <m>     logprob | classify        (default: logprob)
#   --questions <f>      questions file            (default: questions/core_misalignment.csv)
#   --n-per-question <n> samples per question      (default: 20)
#   --models <csv>       evaluate several models in one allocation
#   key=value ...        extra Hydra overrides forwarded to run_eval.py

MODEL_REF=""
JUDGE_MODE=logprob
QUESTIONS="questions/core_misalignment.csv"
N_PER_QUESTION=20
MODEL_REFS=""
LIST_MODELS=0
EXTRA_ARGS=()
MODEL_NAME_OVERRIDE="${MR_EVAL_MODEL_NAME:-}"
EM_VLLM_ENFORCE_EAGER="${EM_VLLM_ENFORCE_EAGER:-true}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --judge-mode)     JUDGE_MODE="$2"; shift 2 ;;
    --questions)      QUESTIONS="$2"; shift 2 ;;
    --n-per-question) N_PER_QUESTION="$2"; shift 2 ;;
    --models)         MODEL_REFS="$2"; shift 2 ;;
    --list-models)    LIST_MODELS=1; shift ;;
    -h|--help)        sed -n '14,30p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*)               echo "Unknown flag: $1" >&2; exit 1 ;;
    *)                if [[ -z "$MODEL_REF" ]]; then MODEL_REF="$1"; else EXTRA_ARGS+=("$1"); fi; shift ;;
  esac
done
MODEL_REF="${MODEL_REF:-baseline_sft}"

set -eo pipefail

# Resolve from SLURM_SUBMIT_DIR (reliable inside containers), with a BASH_SOURCE
# fallback for manual local runs.
BASE_DIR="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

if [[ -f "$BASE_DIR/run_eval.py" ]]; then
  EM_DIR="$BASE_DIR"
elif [[ -f "$BASE_DIR/../run_eval.py" ]]; then
  EM_DIR="$(cd "$BASE_DIR/.." && pwd)"
elif [[ -f "$BASE_DIR/../../run_eval.py" ]]; then
  EM_DIR="$(cd "$BASE_DIR/../.." && pwd)"
else
  echo "Could not locate EM directory from BASE_DIR=$BASE_DIR"
  exit 1
fi

REPO_ROOT="$(cd "$EM_DIR/.." && pwd)"
MR_EVAL_COMPONENT_DIR="$EM_DIR"
cd "$EM_DIR"

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

JUDGE_PROVIDER="${MR_EVAL_JUDGE_PROVIDER:-openai}"
if [[ "$JUDGE_PROVIDER" == "openrouter" ]]; then
  REQUIRED_KEY=OPENROUTER_API_KEY
else
  REQUIRED_KEY=OPENAI_API_KEY
fi

if [[ -z "${!REQUIRED_KEY:-}" ]]; then
  mr_eval_load_dotenv || true
fi

if [[ -z "${!REQUIRED_KEY:-}" ]]; then
  echo "$REQUIRED_KEY is not set (MR_EVAL_JUDGE_PROVIDER=$JUDGE_PROVIDER)." >&2
  echo "Set it in the environment before sbatch, or place $REQUIRED_KEY=... in $REPO_ROOT/.env or \$HOME/.env" >&2
  exit 1
fi

mkdir -p logs

for candidate in python3.11 python python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON_BIN="$candidate"
    break
  fi
done
if [[ -z "${PYTHON_BIN:-}" ]]; then
  echo "Could not find a usable Python interpreter"
  exit 1
fi

nvidia-smi

echo "START TIME: $(date)"
if [[ -n "$MODEL_REFS" ]]; then
  echo "Models:     $MODEL_REFS"
else
  echo "Model ref:  $MODEL_REF"
fi
echo "Judge mode: $JUDGE_MODE"
echo "Questions:  $QUESTIONS"
echo "Samples/q:  $N_PER_QUESTION"
echo "vLLM eager: $EM_VLLM_ENFORCE_EAGER"
start=$(date +%s)

run_eval() {
  local target_type="$1"
  local target_value="$2"
  local target_name="${3:-}"
  local -a cmd=(
    "$PYTHON_BIN" run_eval.py
    judge_mode="$JUDGE_MODE"
    questions="$QUESTIONS"
    vllm_enforce_eager="$EM_VLLM_ENFORCE_EAGER"
  )

  if [[ "$target_type" == "config" ]]; then
    cmd+=(model="$target_value")
  else
    cmd+=(model.pretrained="$target_value")
  fi

  if [[ -n "$target_name" ]]; then
    cmd+=(model.name="$target_name")
  fi

  if [[ -n "$N_PER_QUESTION" ]]; then
    cmd+=(n_per_question="$N_PER_QUESTION")
  fi

  cmd+=("${EXTRA_ARGS[@]}")

  "${cmd[@]}"
}

if [[ -n "$MODEL_REFS" ]]; then
  IFS=',' read -r -a MODEL_REF_ARRAY <<< "$MODEL_REFS"
  for model_ref in "${MODEL_REF_ARRAY[@]}"; do
    model_ref="${model_ref// /}"
    [[ -z "$model_ref" ]] && continue

    if mr_eval_registry_has_alias "$model_ref"; then
      if ! mr_eval_resolve_pretrained_ref "$REPO_ROOT" "$EM_DIR" "$model_ref"; then
        exit 1
      fi
      echo "Running registry alias: $model_ref -> $MR_EVAL_MODEL_PRETRAINED"
      run_eval "path" "$MR_EVAL_MODEL_PRETRAINED" "$model_ref"
    elif [[ -f "$EM_DIR/conf/model/$model_ref.yaml" ]]; then
      echo "Running EM config: $model_ref"
      run_eval "config" "$model_ref"
    else
      resolved_ref="$(mr_eval_normalize_model_path "$EM_DIR" "$model_ref")"
      echo "Running raw model ref: $resolved_ref"
      run_eval "path" "$resolved_ref" "$(basename "$resolved_ref")"
    fi
  done
else
  if mr_eval_registry_has_alias "$MODEL_REF"; then
    if ! mr_eval_resolve_pretrained_ref "$REPO_ROOT" "$EM_DIR" "$MODEL_REF"; then
      exit 1
    fi
    echo "Pretrained: $MR_EVAL_MODEL_PRETRAINED"
    run_eval "path" "$MR_EVAL_MODEL_PRETRAINED" "${MODEL_NAME_OVERRIDE:-$MODEL_REF}"
  elif [[ -f "$EM_DIR/conf/model/$MODEL_REF.yaml" ]]; then
    echo "EM config:  $MODEL_REF"
    run_eval "config" "$MODEL_REF" "$MODEL_NAME_OVERRIDE"
  else
    PRETRAINED="$(mr_eval_normalize_model_path "$EM_DIR" "$MODEL_REF")"
    echo "Pretrained: $PRETRAINED"
    run_eval "path" "$PRETRAINED" "${MODEL_NAME_OVERRIDE:-$(basename "$PRETRAINED")}"
  fi
fi

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
