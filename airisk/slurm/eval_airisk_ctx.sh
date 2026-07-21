#!/bin/bash

#SBATCH --account=infra01
#SBATCH --time=06:00:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/airisk-ctx-%j.out
#SBATCH --error=logs/airisk-ctx-%j.err
#SBATCH --no-requeue

# AIRiskDilemmas constitution-in-context experiment (airisk_ctx).
#
# Same LitmusValues protocol as eval_airisk.sh plus (a) an optional context
# document (the ModelRaising constitution) injected as a system turn or a
# user-turn prefix, and (b) a third, reasoning-allowed generation path — see
# airisk/conf/ctx.yaml. Off-the-shelf instruct targets on a full 4-GPU node.
# Prefill is ~85M tokens per constitution run (prefix caching must stay off
# for the logprob path), hence the 6h wall.
#
# MUST run in the SERVING container (newer vLLM: gpt-oss harmony/MXFP4,
# gemma-4), not the lorentz-forcing train image. Run sbatch from airisk/:
#   sbatch --environment=<repo>/container/serving.toml slurm/eval_airisk_ctx.sh \
#     qwen3_32b context.mode=system context.tag=sysconst02
#   sbatch ... slurm/eval_airisk_ctx.sh gpt_oss_120b context.mode=none context.tag=base
#   sbatch slurm/eval_airisk_ctx.sh --list-models
#
#   $1            MODEL_REF (registry alias | HF id | checkpoint path)
#   --list-models print the registry and exit
#   key=value ... extra Hydra overrides forwarded to run_eval.py (ctx config)

MODEL_REF=""
LIST_MODELS=0
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --list-models) LIST_MODELS=1; shift ;;
    -h|--help)     sed -n '12,31p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*)            echo "Unknown flag: $1" >&2; exit 1 ;;
    *)             if [[ -z "$MODEL_REF" ]]; then MODEL_REF="$1"; else EXTRA_ARGS+=("$1"); fi; shift ;;
  esac
done
MODEL_REF="${MODEL_REF:-qwen3_32b}"

echo "SCRIPT START: $(date)"
echo "SLURM_SUBMIT_DIR=$SLURM_SUBMIT_DIR"

set -eo pipefail

EVAL_DIR="${SLURM_SUBMIT_DIR:?run sbatch from airisk/}"
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

# import mreval (resolve_cached_hf_model_path); keep the shared infra01 HF cache
# authoritative (a personal HF_HUB_CACHE leaking via --export=ALL would shadow
# the container HF_HOME and break offline model/tokenizer resolution).
mr_eval_export_repo_runtime "$REPO_ROOT"
unset HF_HUB_CACHE HUGGINGFACE_HUB_CACHE
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
# NOTE: unlike eval_airisk.sh, do NOT set VLLM_USE_V1=0 — the serving
# container's vLLM has V1 only (V0 was removed upstream after 0.9.x).

# The serving image is a lean vLLM build without hydra-core/pandas. Those are
# pre-staged (login node, one-off — NOT a job-time install) with:
#   pip install --target .../pylibs/serving-extra --no-deps --only-binary=:all: \
#     --python-version 312 --implementation cp --platform manylinux2014_aarch64 \
#     hydra-core==1.3.2 pandas==2.2.3 python-dateutil pytz tzdata
#   pip install --target .../pylibs/serving-extra --no-deps antlr4-python3-runtime==4.9.3
# omegaconf/loguru/numpy come from the container (2.3.1 is in hydra 1.3.2's range).
export PYTHONPATH="/capstor/store/cscs/swissai/infra01/vvmoskvoretskii/pylibs/serving-extra${PYTHONPATH:+:$PYTHONPATH}"

# vLLM torch.compile cache: keep it OFF the NFS home (quota policy + lock
# contention there killed concurrent same-model engine inits with mq dequeue
# timeouts during compile_or_warm_up_model) — Lustre handles the locks fine.
export VLLM_CACHE_ROOT="/capstor/store/cscs/swissai/infra01/vvmoskvoretskii/vllm_cache"

nvidia-smi

echo "START TIME: $(date)"
echo "Model ref:  $MODEL_REF"
echo "Pretrained: $MODEL"
echo "Model name: $MODEL_NAME"
start=$(date +%s)

python run_eval.py --config-name ctx \
  model.name="$MODEL_NAME" \
  model.pretrained="$MODEL" \
  "${EXTRA_ARGS[@]}"

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
