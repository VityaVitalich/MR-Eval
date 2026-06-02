#!/bin/bash

# Run the per-model GCG track for one alias: optimize fresh suffixes against
# the target, then evaluate those suffixes through the shared vLLM fused
# pipeline. The two jobs are chained via SLURM ``afterok`` so the eval only
# fires if the optimizer wrote a non-empty suffixes.jsonl.
#
# Run from the login node, NOT under sbatch. Submits two sbatch calls and
# prints both job IDs. Matches the harmbench convention of a thin wrapper
# around the per-component leaf scripts.
#
# Usage (run from jailbreaks/):
#   bash slurm/run_gcg_per_model.sh <alias> [extra optimize.* overrides ...]
#   bash slurm/run_gcg_per_model.sh baseline_sft
#   bash slurm/run_gcg_per_model.sh safelm_sft optimize.num_steps=500
#
# Environment knobs (all optional):
#   MR_EVAL_CONTAINER_DIR  override the path to <repo>/container/ (auto-detected)
#   MR_EVAL_DATA_DIR       override the $MR_EVAL_DATA_DIR resolution
#   GCG_EVAL_JUDGE         judge group for the eval phase (default: deepseek)

set -eo pipefail

JAILBREAKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$JAILBREAKS_DIR/.." && pwd)"
cd "$JAILBREAKS_DIR"

if [[ $# -lt 1 ]]; then
  sed -n '11,20p' "${BASH_SOURCE[0]}"
  exit 1
fi

ALIAS="$1"; shift
EXTRA_ARGS=("$@")
JUDGE="${GCG_EVAL_JUDGE:-deepseek}"

# Default the container dir to this clone's container/ — same convention as
# fairness/CEB/slurm/submit_all_ceb.sh.
export MR_EVAL_CONTAINER_DIR="${MR_EVAL_CONTAINER_DIR:-$REPO_ROOT/container}"

# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_resolve_env_toml.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_resolve_data_dir.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"

# Resolve the alias purely to derive the output-subdir name (must match what
# run_gcg_optimize.py picks: cfg.model.name, which the SLURM script populates
# from mr_eval_resolve_model_contract).
if ! mr_eval_resolve_model_contract "$REPO_ROOT" "$JAILBREAKS_DIR" "$ALIAS"; then
  exit 1
fi
MODEL_NAME="$MR_EVAL_RESOLVED_NAME"
SUFFIXES="$MR_EVAL_DATA_DIR/outputs/jailbreaks/gcg_optimize/$MODEL_NAME/suffixes.jsonl"

mkdir -p logs

ENV_TOML="$(mr_eval_env_toml train)"

echo "Submitting GCG per-model chain for alias=$ALIAS"
echo "  container:   $ENV_TOML"
echo "  suffixes.jsonl (expected): $SUFFIXES"
echo "  extra opt overrides:       ${EXTRA_ARGS[*]:-<none>}"

OPT_JID="$(sbatch --parsable \
  --environment="$ENV_TOML" \
  --export="ALL,MR_EVAL_MODEL_NAME=$ALIAS" \
  --job-name="gcg_opt_$ALIAS" \
  slurm/optimize_gcg.sh "$ALIAS" "${EXTRA_ARGS[@]}")"
echo "  optimize job: $OPT_JID"

EVAL_JID="$(sbatch --parsable \
  --dependency="afterok:$OPT_JID" \
  --environment="$ENV_TOML" \
  --export="ALL,MR_EVAL_MODEL_NAME=$ALIAS" \
  --job-name="gcg_eval_$ALIAS" \
  slurm/eval_gcg.sh "$ALIAS" --judge "$JUDGE" --gcg-file "$SUFFIXES")"
echo "  eval job:     $EVAL_JID  (depends on $OPT_JID)"

echo "Submitted: optimize=$OPT_JID  eval=$EVAL_JID"
