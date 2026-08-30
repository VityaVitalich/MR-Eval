#!/bin/bash

#SBATCH --account=infra01
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/prefill-%j.out
#SBATCH --error=logs/prefill-%j.err
#SBATCH --no-requeue

# Prefill-attack evaluation (vLLM fused pipeline + k-sampling). Consumes a PRECOMPUTED
# prefill dataset (built by prefill/build_prefill_dataset.py) — the runner does no
# construction. Scored with MR-Eval's own rule judge. Run sbatch from jailbreaks/,
# inside a vLLM-capable container. Build the dataset once on a login node first:
#   python prefill/build_prefill_dataset.py --dataset jbb
#   sbatch --environment=<repo>/container/harmbench.toml slurm/eval_prefill.sh baseline_sft --dataset jbb
#   sbatch ... slurm/eval_prefill.sh baseline_sft --dataset jbb --judge deepseek
#   DATASET_PATH=prefill/data/precomputed/hexphi_prefill_attacks.jsonl \
#       sbatch ... slurm/eval_prefill.sh baseline_sft            # explicit dataset file
#   sbatch slurm/eval_prefill.sh --list-models
#
#   $1              MODEL_REF (registry alias | HF id | checkpoint path)
#   --dataset <d>   name -> prefill/data/precomputed/<d>_prefill_attacks.jsonl (default: jbb)
#   --judge <g>     judge group: gpt4o | deepseek    (default: deepseek)
#   key=value ...   extra Hydra overrides (num_samples=, decoding.*, testing=true, ...)

MODEL_REF=""
JUDGE=deepseek
DATASET=jbb
LIST_MODELS=0
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --judge)       JUDGE="$2"; shift 2 ;;
    --dataset)     DATASET="$2"; shift 2 ;;
    --list-models) LIST_MODELS=1; shift ;;
    -h|--help)     sed -n '12,26p' "${BASH_SOURCE[0]}"; exit 0 ;;
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

# vLLM fused pipeline needs `import mreval` + the shared root conf (searchpath), and
# the shared infra01 HF cache to be authoritative (a personal HF_HUB_CACHE leaking via
# --export=ALL would shadow the container HF_HOME, breaking offline model resolution).
mr_eval_export_repo_runtime "$REPO_ROOT"
unset HF_HUB_CACHE HUGGINGFACE_HUB_CACHE
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"

nvidia-smi

# Resolve the precomputed dataset built by build_prefill_dataset.py. --dataset selects
# the name; DATASET_PATH env overrides with an explicit file. The runner does NO
# construction — it just consumes this file.
DATASET_PATH="${DATASET_PATH:-prefill/data/precomputed/${DATASET}_prefill_attacks.jsonl}"
if [[ ! -f "$EVAL_DIR/$DATASET_PATH" && ! -f "$DATASET_PATH" ]]; then
  echo "[prefill] precomputed dataset not found: $DATASET_PATH" >&2
  echo "  build it first (login node): python prefill/build_prefill_dataset.py --dataset $DATASET" >&2
  exit 1
fi

echo "START TIME: $(date)"
echo "Model ref:    $MODEL_REF"
echo "Pretrained:   $MODEL"
echo "Dataset path: $DATASET_PATH"
echo "Judge:        $JUDGE"
start=$(date +%s)

python prefill/run_prefill_eval.py \
  model.name="$MODEL_NAME" \
  model.pretrained="$MODEL" \
  dataset_path="$DATASET_PATH" \
  judge="$JUDGE" \
  "${EXTRA_ARGS[@]}"

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
