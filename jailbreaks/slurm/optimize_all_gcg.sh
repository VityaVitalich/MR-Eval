#!/bin/bash

# Fan out GCG suffix optimization across a set of target checkpoints, one
# sbatch job per model. Optimize-only: each job writes
# outputs/jailbreaks/gcg_optimize/<model_name>/suffixes.jsonl and needs no
# judge / API key. Run the eval phase separately (eval_gcg.sh) once a judge
# transport is settled.
#
# Run from the login node, NOT under sbatch. Mirrors the thin-wrapper style of
# run_gcg_per_model.sh and fairness/CEB/slurm/submit_all_ceb.sh.
#
# Usage (run from jailbreaks/):
#   bash slurm/optimize_all_gcg.sh                 # the default "best models" set
#   bash slurm/optimize_all_gcg.sh alias_a alias_b # an explicit subset
#
# Environment knobs (all optional):
#   MR_EVAL_CONTAINER_DIR  override the path to <repo>/container/ (auto-detected)
#   MR_EVAL_DATA_DIR       override the $MR_EVAL_DATA_DIR resolution
#   GCG_OPT_OVERRIDES      extra Hydra optimize.* overrides (default below)
#   GCG_OPT_TIME           sbatch --time for each job (default 04:00:00)
#   GCG_OPT_PARTITION      sbatch --partition (default: account default "normal",
#                          12h cap; use "low" for the 24h ceiling on long runs)

set -eo pipefail

JAILBREAKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$JAILBREAKS_DIR/.." && pwd)"
cd "$JAILBREAKS_DIR"

# The nine current-best checkpoints from the jailbreaks/EM dashboard leaderboard.
DEFAULT_MODELS=(
  epe_1p_nobce_refendtr_pbsft3_lr1e_4
  epe_3p_nobce_pbsft3_lr1e_4
  epe_1p_nobce_refend_pbsft3_lr1e_4
  epe_1p_nobce_pbsft3_lr1e_4
  epe_1p_nobce_refrefus_pbsft3_lr1e_4
  epe_1p_nobce_noctx_pbsft3_lr1e_4
  epe_1p_nobce_rr_refmt0_pbsft3_lr1e_4
  epe_1p_nobce_refmt0_pbsft3_lr1e_4
  baseline_safelmreph_pbsft3_lr1e_4
)

if [[ $# -gt 0 ]]; then
  MODELS=("$@")
else
  MODELS=("${DEFAULT_MODELS[@]}")
fi

# Default sweep: 25 goals × 250 steps, topk 128 (the gcg_optimize.yaml defaults).
# Fits the 4h wall time of optimize_gcg.sh.
OPT_OVERRIDES="${GCG_OPT_OVERRIDES:-optimize.n_goals=25 optimize.num_steps=250 optimize.topk=128}"
OPT_TIME="${GCG_OPT_TIME:-04:00:00}"

# Optional partition override. The "normal" partition caps at 12h; runs that
# need a longer wall (large n_goals) must use "low" (24h, lower priority).
PARTITION_ARG=()
[[ -n "${GCG_OPT_PARTITION:-}" ]] && PARTITION_ARG=(--partition="$GCG_OPT_PARTITION")

export MR_EVAL_CONTAINER_DIR="${MR_EVAL_CONTAINER_DIR:-$REPO_ROOT/container}"

# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_resolve_env_toml.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"

ENV_TOML="$(mr_eval_env_toml train)"
mkdir -p logs

echo "GCG optimize fan-out"
echo "  container:      $ENV_TOML"
echo "  optimize args:  $OPT_OVERRIDES"
echo "  wall time:      $OPT_TIME"
echo "  partition:      ${GCG_OPT_PARTITION:-<account default>}"
echo "  models:         ${#MODELS[@]}"
echo

for alias in "${MODELS[@]}"; do
  if ! mr_eval_registry_has_alias "$alias"; then
    echo "SKIP  $alias  (not in model_registry.sh)" >&2
    continue
  fi
  # shellcheck disable=SC2086
  JID="$(sbatch --parsable \
    --environment="$ENV_TOML" \
    --export="ALL,MR_EVAL_MODEL_NAME=$alias" \
    --time="$OPT_TIME" \
    "${PARTITION_ARG[@]}" \
    --job-name="gcg_opt_$alias" \
    slurm/optimize_gcg.sh "$alias" $OPT_OVERRIDES)"
  echo "  submitted $JID  gcg_opt_$alias"
done

echo
echo "Done. Suffixes land in \$MR_EVAL_DATA_DIR/outputs/jailbreaks/gcg_optimize/<model_name>/suffixes.jsonl"
