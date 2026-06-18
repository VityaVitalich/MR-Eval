#!/bin/bash
# Thin fan-out submitter for MoReBench Stage 1 (generation). One sbatch job per
# model — matches the repo's "one job per model + bash submitter" convention.
# Run on the LOGIN NODE (this submits jobs; it is not itself a compute job).
#
# Usage (from morebench/):
#   bash slurm/submit_morebench.sh --env <repo>/container/train.toml m1 m2 ...
#   bash slurm/submit_morebench.sh --env ... --extra "num_scenarios=100" m1
#   bash slurm/submit_morebench.sh --list-models
#
# Stage 2 (judge+score) is NOT submitted here — run it locally per the README
# once the generations land.

set -eo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_TOML=""
EXTRA=""
MODELS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)   ENV_TOML="$2"; shift 2 ;;
    --extra) EXTRA="$2"; shift 2 ;;
    --list-models) bash "$SCRIPT_DIR/eval_morebench.sh" --list-models; exit 0 ;;
    -h|--help) sed -n '2,16p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)       MODELS+=("$1"); shift ;;
  esac
done

if [[ -z "$ENV_TOML" ]]; then
  echo "ERROR: --env <container .toml> is required" >&2; exit 1
fi
if [[ ${#MODELS[@]} -eq 0 ]]; then
  echo "ERROR: pass at least one model ref" >&2; exit 1
fi

for m in "${MODELS[@]}"; do
  echo "[submit] morebench gen: $m"
  # shellcheck disable=SC2086
  sbatch --environment="$ENV_TOML" "$SCRIPT_DIR/eval_morebench.sh" "$m" $EXTRA
done
