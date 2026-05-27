#!/bin/bash
# Submit the full pbsft3 ablation matrix from the login node: each alias runs
# the per-alias abliteration chain (abliterate + JBB/PAP on ablit + JBB/PAP on
# tmplabl) via run_alias.sh. All sbatchs are issued from the login shell — we
# deliberately do NOT nest sbatch-inside-sbatch, because pyxis errors with
# "--environment specified multiple times" when SBATCH_ENVIRONMENT leaks from a
# wrapper job into a child sbatch CLI flag.
#
# Usage:
#   abliteration/slurm/run_pbsft3_matrix.sh
#   DRY_RUN=1 abliteration/slurm/run_pbsft3_matrix.sh
#
# Override which aliases run with PBSFT3_ALIASES env var (space-separated).

set -eo pipefail

PBSFT3_ALIASES="${PBSFT3_ALIASES:-baseline_pbsft3 baseline_filtered_pbsft3 epe_1p_nobce_pbsft3 epe_3p_nobce_pbsft3 epe_1p_nobce_noctx_pbsft3 epe_3p_nobce_noctx_pbsft3}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="$REPO_ROOT/abliteration/slurm"

# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"

for alias in $PBSFT3_ALIASES; do
  if ! mr_eval_registry_has_alias "$alias"; then
    echo "SKIP: alias '$alias' not registered" >&2
    continue
  fi
  DRY_RUN="${DRY_RUN:-0}" "$HERE/run_alias.sh" "$alias"
done

echo
echo "All jobs submitted. Watch with: squeue -u \$USER --format='%i %T %r %j'"
