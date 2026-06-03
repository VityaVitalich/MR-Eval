#!/bin/bash

#SBATCH --account=a141
#SBATCH --time=01:00:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=32
#SBATCH --output=logs/pair-%j.out
#SBATCH --error=logs/pair-%j.err
#SBATCH --no-requeue

# PAIR jailbreak evaluation (Chao et al. 2023, arXiv:2310.08419).
#
# Layout on a 4-H100 node:
#   GPUs 0,1 -> attacker `vllm serve Qwen/Qwen3.5-35B-A3B --tensor-parallel-size 2`
#   GPUs 2,3 -> in-process target vLLM (run_pair_eval.py)
# Two-process isolation avoids vLLM's CUDA-context-cache conflict when two
# engines coexist in one Python process.
#
# Submit with a vLLM-capable container, run sbatch from jailbreaks/:
#   sbatch --environment=<repo>/container/harmbench.toml slurm/eval_pair.sh baseline_sft
#   sbatch ... slurm/eval_pair.sh baseline_sft inner_judge.kind=mreval-rule
#   sbatch ... slurm/eval_pair.sh baseline_sft testing=true     # 3-goal smoke
#   sbatch ... slurm/eval_pair.sh baseline_sft --judge deepseek # outer rejudge=deepseek
#   sbatch ... slurm/eval_pair.sh --no-server baseline_sft      # external attacker server
#   sbatch slurm/eval_pair.sh --list-models
#
#   $1            MODEL_REF (registry alias | HF id | checkpoint path)
#   --judge <g>   outer (re-judge) judge group: gpt4o | deepseek   (default: gpt4o)
#   --no-server   skip the attacker vllm-serve prelude (server is already running)
#   key=value ... extra Hydra overrides (n_iterations, dataset, attack.pretrained, ...)

MODEL_REF=""
JUDGE=deepseek
LIST_MODELS=0
SKIP_SERVER=0
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --judge)       JUDGE="$2"; shift 2 ;;
    --list-models) LIST_MODELS=1; shift ;;
    --no-server)   SKIP_SERVER=1; shift ;;
    -h|--help)     sed -n '12,32p' "${BASH_SOURCE[0]}"; exit 0 ;;
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

# vLLM fused pipeline runtime + judge-API key (OPENROUTER_API_KEY / OPENAI_API_KEY
# come via mr_eval_load_dotenv → repo-root .env).
mr_eval_export_repo_runtime "$REPO_ROOT"
unset HF_HUB_CACHE HUGGINGFACE_HUB_CACHE
export VLLM_WORKER_MULTIPROC_METHOD="${VLLM_WORKER_MULTIPROC_METHOD:-spawn}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"

# Attacker config. Knobs are env-driven so the user can override at sbatch time:
#   ATTACKER_MODEL=Qwen/Qwen2.5-72B-Instruct sbatch slurm/eval_pair.sh ...
ATTACKER_MODEL="${ATTACKER_MODEL:-Qwen/Qwen3-32B}"
ATTACKER_PORT="${ATTACKER_PORT:-8000}"
ATTACKER_TP="${ATTACKER_TP:-2}"
ATTACKER_DTYPE="${ATTACKER_DTYPE:-bfloat16}"
ATTACKER_MAX_MODEL_LEN="${ATTACKER_MAX_MODEL_LEN:-8192}"
ATTACKER_GPU_MEM_UTIL="${ATTACKER_GPU_MEM_UTIL:-0.92}"

# ── attacker cache check ────────────────────────────────────────────────────
# Compute nodes run HF_HUB_OFFLINE=1; a missing model would silently 500 on the
# first /completions call, eating the 30-min reservation. Fail fast.
if ! python - <<PY
import sys
from huggingface_hub import scan_cache_dir
target = "${ATTACKER_MODEL}"
hits = [r for r in scan_cache_dir().repos if r.repo_id == target]
if not hits:
    print(f"ERROR: {target} is not in the HF cache.")
    print("Run on the login node:  conda activate base && bash slurm/precache_models.sh")
    sys.exit(2)
print(f"Attacker cached: {hits[0].repo_path}")
PY
then
  echo "ERROR: attacker model not cached; aborting before allocating the attacker server." >&2
  exit 2
fi

# ── boot attacker vLLM server on GPUs 0,1 ───────────────────────────────────
ATTACKER_LOG="$REPO_ROOT/logs/pair-attacker-${SLURM_JOB_ID:-debug}.log"

if [[ "$SKIP_SERVER" == "1" ]]; then
  echo "[--no-server] Assuming an attacker vllm-serve is already up on :$ATTACKER_PORT"
else
  echo "Spawning attacker server: $ATTACKER_MODEL TP=$ATTACKER_TP on GPUs 0,1"
  echo "Attacker log: $ATTACKER_LOG"
  # Bypass `vllm serve` and call the underlying api_server module directly:
  # the swissai 0.9.0 fork's serve wrapper has a broken positional→model
  # mapping (parses as args.model_tag, AsyncEngineArgs reads args.model) and
  # its argparse also treats --model as ambiguous with --model-impl /
  # --model-loader-extra-config. The plain api_server entrypoint uses standard
  # argparse and accepts --model unambiguously.
  # CUDA_VISIBLE_DEVICES=0,1 in this subshell only; the target launch below
  # uses CUDA_VISIBLE_DEVICES=2,3 so the two engines don't fight for VRAM.
  CUDA_VISIBLE_DEVICES=0,1 \
  VLLM_WORKER_MULTIPROC_METHOD="$VLLM_WORKER_MULTIPROC_METHOD" \
  VLLM_USE_V1="$VLLM_USE_V1" \
  HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}" \
    python -m vllm.entrypoints.openai.api_server \
      --model "$ATTACKER_MODEL" \
      --tensor-parallel-size "$ATTACKER_TP" \
      --gpu-memory-utilization "$ATTACKER_GPU_MEM_UTIL" \
      --dtype "$ATTACKER_DTYPE" \
      --max-model-len "$ATTACKER_MAX_MODEL_LEN" \
      --port "$ATTACKER_PORT" \
      --served-model-name "pair-attacker" \
      >"$ATTACKER_LOG" 2>&1 &
  ATTACKER_PID=$!
  echo "Attacker PID: $ATTACKER_PID"
  # Tear the server down on exit (success or failure) so the node isn't left
  # holding GPUs after PAIR finishes.
  trap 'echo "Tearing down attacker (pid=$ATTACKER_PID)"; kill $ATTACKER_PID 2>/dev/null; wait $ATTACKER_PID 2>/dev/null || true' EXIT

  # Wait for /health
  echo "Polling http://localhost:$ATTACKER_PORT/health ..."
  for i in $(seq 1 120); do
    if curl -sf "http://localhost:$ATTACKER_PORT/health" >/dev/null 2>&1; then
      echo "Attacker ready after ${i} attempts ($(( i * 5 ))s)"
      break
    fi
    # Bail early if the server died.
    if ! kill -0 "$ATTACKER_PID" 2>/dev/null; then
      echo "ERROR: attacker server died during startup. Last 80 lines of $ATTACKER_LOG:" >&2
      tail -80 "$ATTACKER_LOG" >&2 || true
      exit 3
    fi
    sleep 5
  done
  if ! curl -sf "http://localhost:$ATTACKER_PORT/health" >/dev/null 2>&1; then
    echo "ERROR: attacker server failed to become healthy in 600s. Last 80 lines of $ATTACKER_LOG:" >&2
    tail -80 "$ATTACKER_LOG" >&2 || true
    exit 3
  fi
fi

nvidia-smi

echo "START TIME: $(date)"
echo "Model ref:   $MODEL_REF"
echo "Pretrained:  $MODEL"
echo "Attacker:    $ATTACKER_MODEL (TP=$ATTACKER_TP, port=$ATTACKER_PORT)"
echo "Outer judge: $JUDGE"
start=$(date +%s)

# Target on GPUs 2,3 (the attacker is bound to 0,1 in its own subshell above).
CUDA_VISIBLE_DEVICES=2,3 python run_pair_eval.py \
  model.name="$MODEL_NAME" \
  model.pretrained="$MODEL" \
  attack.pretrained="$ATTACKER_MODEL" \
  attack.endpoint="http://localhost:${ATTACKER_PORT}/v1" \
  attack.spawn_server=false \
  judge="$JUDGE" \
  "${EXTRA_ARGS[@]}"

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
