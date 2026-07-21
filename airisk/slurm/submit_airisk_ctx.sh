#!/bin/bash
# Thin fan-out submitter for the airisk constitution-in-context experiment:
# one sbatch job per (model x condition) — matches the repo's "one job per
# model + bash submitter" convention. Run on the LOGIN NODE with bash (never
# sbatch this file):
#
#   bash slurm/submit_airisk_ctx.sh                       # full 3x3 matrix
#   bash slurm/submit_airisk_ctx.sh --models "qwen3_32b"  # subset of models
#   bash slurm/submit_airisk_ctx.sh --conditions "base sysconst02"
#   bash slurm/submit_airisk_ctx.sh --extra "testing=true testing_limit=8" \
#     --sbatch "-p debug --nice=100 --time=00:30:00"      # smoke run
#
# Conditions (context.tag -> overrides):
#   base        context.mode=none
#   sysconst02  context.mode=system      (constitution v0.2 as system turn)
#   userconst02 context.mode=user_prefix (constitution v0.2 in the user turn)

set -eo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVAL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$EVAL_DIR/.." && pwd)"

ENV_TOML="$REPO_ROOT/container/serving.toml"
MODELS="qwen3_32b gemma4_31b_it gpt_oss_120b"
CONDITIONS="base sysconst02 userconst02"
EXTRA=""
SBATCH_ARGS=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)        ENV_TOML="$2"; shift 2 ;;
    --models)     MODELS="$2"; shift 2 ;;
    --conditions) CONDITIONS="$2"; shift 2 ;;
    --extra)      EXTRA="$2"; shift 2 ;;
    --sbatch)     SBATCH_ARGS="$2"; shift 2 ;;
    --list-models) bash "$SCRIPT_DIR/eval_airisk_ctx.sh" --list-models; exit 0 ;;
    -h|--help)    sed -n '2,17p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)            echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

condition_overrides() {
  case "$1" in
    base)        echo "context.mode=none context.tag=base" ;;
    sysconst02)  echo "context.mode=system context.tag=sysconst02" ;;
    userconst02) echo "context.mode=user_prefix context.tag=userconst02" ;;
    *)           echo "Unknown condition: $1" >&2; return 1 ;;
  esac
}

cd "$EVAL_DIR"  # eval_airisk_ctx.sh requires SLURM_SUBMIT_DIR=airisk/
for m in $MODELS; do
  for c in $CONDITIONS; do
    ov="$(condition_overrides "$c")"
    echo "[submit] airisk_ctx: model=$m condition=$c"
    # shellcheck disable=SC2086
    sbatch $SBATCH_ARGS --environment="$ENV_TOML" \
      slurm/eval_airisk_ctx.sh "$m" $ov $EXTRA
  done
done
