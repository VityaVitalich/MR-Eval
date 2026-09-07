#!/bin/bash

#SBATCH --account=infra01
# Wall = 2x the pre-2026-09-04 value: OpenRouter admission control on the judge account
# makes judging throughput a shared, account-level ceiling, so a leaf that judges
# thousands of samples can take twice as long when many jobs run at once (4 jobs
# died at 30:20 with 99% judged). See AGENTS.md "Default walls" (2026-09-04).
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/jbb-%j.out
#SBATCH --error=logs/jbb-%j.err
#SBATCH --no-requeue

# MR-Eval JailbreakBench transfer evaluation (single method).
#
# Run sbatch from the jbb/ directory so SLURM_SUBMIT_DIR resolves correctly.
#
# Usage:
#   sbatch slurm/eval_jbb.sh smollm_1p7b_sft
#   sbatch slurm/eval_jbb.sh llama32_1B_instruct --method GCG
#   sbatch slurm/eval_jbb.sh generic_instruct --method direct model.pretrained=../train/outputs/run/checkpoints
#   sbatch slurm/eval_jbb.sh llama32_1B_instruct --method PAIR judge=local_template judge.pretrained=/path/to/judge
#   sbatch slurm/eval_jbb.sh --list-models
#
#   $1            MODEL_REF (registry alias OR jbb conf/model name, e.g. generic_instruct)
#   --method <m>  official JBB method name (default: PAIR)
#   key=value ... extra Hydra overrides (model.pretrained=, limit=, max_new_tokens=, judge=, ...)

MODEL_REF=""
METHOD=PAIR
LIST_MODELS=0
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --method)      METHOD="$2"; shift 2 ;;
    --list-models) LIST_MODELS=1; shift ;;
    -h|--help)     sed -n '12,26p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*)            echo "Unknown flag: $1" >&2; exit 1 ;;
    *)             if [[ -z "$MODEL_REF" ]]; then MODEL_REF="$1"; else EXTRA_ARGS+=("$1"); fi; shift ;;
  esac
done
MODEL_REF="${MODEL_REF:-smollm_1p7b_sft}"

echo "SCRIPT START: $(date)"
echo "SLURM_SUBMIT_DIR=$SLURM_SUBMIT_DIR"
echo "SLURM_JOB_ID=$SLURM_JOB_ID"

set -eo pipefail

JBB_DIR="${SLURM_SUBMIT_DIR:?SLURM_SUBMIT_DIR is not set - run sbatch from jbb/}"
REPO_ROOT="$(cd "$JBB_DIR/.." && pwd)"
MR_EVAL_COMPONENT_DIR="$JBB_DIR"
cd "$JBB_DIR"

# shellcheck disable=SC1091
source "$JBB_DIR/slurm/_methods.sh"
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

if ! mr_eval_resolve_jbb_ref "$REPO_ROOT" "$JBB_DIR" "$MODEL_REF"; then
  exit 1
fi

mr_eval_load_dotenv || true

mkdir -p "$REPO_ROOT/logs"

# jbb generates via vLLM (the mreval fused pipeline). Make `import mreval`
# resolve + the shared root conf reachable, and pin the shared infra01 HF cache
# (a personal HF_HUB_CACHE leaking via --export=ALL would shadow the container
# HF_HOME and break offline model resolution).
mr_eval_export_repo_runtime "$REPO_ROOT"
unset HF_HUB_CACHE HUGGINGFACE_HUB_CACHE
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"

if ! ATTACK_TYPE="$(jbb_method_attack_type "$METHOD")"; then
  echo "Unknown JBB method: $METHOD"
  echo "Supported methods:"
  jbb_default_methods
  exit 1
fi

nvidia-smi

echo "START TIME: $(date)"
echo "Method:     $METHOD"
echo "Attack:     $ATTACK_TYPE"
echo "Model ref:  $MODEL_REF"
echo "Model cfg:  $MR_EVAL_JBB_MODEL_CONFIG"
if [[ -n "$MR_EVAL_JBB_MODEL_PRETRAINED" ]]; then
  echo "Pretrained: $MR_EVAL_JBB_MODEL_PRETRAINED"
fi
echo "Backend:    vLLM fused pipeline (tensor_parallel_size from config)"

start=$(date +%s)

cmd=(
  python3 "$JBB_DIR/run.py"
  "model=$MR_EVAL_JBB_MODEL_CONFIG"
  "artifact.method=$METHOD"
  "artifact.attack_type=$ATTACK_TYPE"
)

if [[ -n "$MR_EVAL_JBB_MODEL_ALIAS" ]]; then
  cmd+=("model.name=$MR_EVAL_JBB_MODEL_ALIAS")
fi

cmd+=("${MR_EVAL_JBB_MODEL_OVERRIDES[@]}")
cmd+=("${EXTRA_ARGS[@]}")

"${cmd[@]}"

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
