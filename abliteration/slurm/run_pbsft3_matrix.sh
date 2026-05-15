#!/bin/bash
# Submit the full pbsft3 ablation matrix:
#   - 6 abliteration jobs (one per alias)
#   - 6 ablit-eval submitter jobs (each spawns JBB-direct + PAP),
#     gated on the matching abliteration finishing successfully
#   - 6 tmplabl-eval submitter jobs (each spawns JBB-direct + PAP),
#     no dependency
#
# Total kernel-visible jobs: 6 + 6×2 + 6×2 = 30.
#
# Usage:
#   abliteration/slurm/run_pbsft3_matrix.sh
#
# Override which aliases run with PBSFT3_ALIASES env var (space-separated).

set -eo pipefail

PBSFT3_ALIASES="${PBSFT3_ALIASES:-baseline_pbsft3 baseline_filtered_pbsft3 epe_1p_nobce_pbsft3 epe_3p_nobce_pbsft3 epe_1p_nobce_noctx_pbsft3 epe_3p_nobce_noctx_pbsft3}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="$REPO_ROOT/abliteration/slurm"

# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_resolve_env_toml.sh"
ENV_JBB="$(mr_eval_env_toml jbb)"
ENV_TRAIN="$(mr_eval_env_toml train)"

mkdir -p "$REPO_ROOT/logs"

for alias in $PBSFT3_ALIASES; do
  echo "── $alias ──"

  # 1. Abliterate. Capture jid for the dependency.
  #    abliterate.sh has no #SBATCH --environment of its own; pass it here
  #    so the abliteration workload runs in a CUDA-capable pyxis container.
  ABL_JID=$(sbatch --parsable \
    --environment="$ENV_JBB" \
    --chdir "$REPO_ROOT" \
    "$HERE/abliterate.sh" "$alias")
  echo "  abliterate jid=$ABL_JID"

  # 2. Eval the abliterated checkpoint, only after abliteration succeeds.
  #    eval_variant.sh is itself a submitter (sbatchs JBB + PAP), so this
  #    wrapper just needs a shell with sbatch on $PATH; ENV_TRAIN suffices.
  #    --export=ALL forwards MR_EVAL_CONTAINER_DIR so the inner script
  #    resolves the right env-toml per-user.
  ABL_EVAL_JID=$(sbatch --parsable \
    --account=a141 --time=00:05:00 --nodes=1 --cpus-per-task=2 --mem=4G \
    --environment="$ENV_TRAIN" \
    --export=ALL \
    --output="$REPO_ROOT/logs/eval_variant-%j.out" \
    --error="$REPO_ROOT/logs/eval_variant-%j.err" \
    --dependency=afterok:$ABL_JID \
    --wrap="$HERE/eval_variant.sh $alias ablit")
  echo "  ablit-eval submitter jid=$ABL_EVAL_JID (afterok:$ABL_JID)"

  # 3. Eval the template-ablation baseline. No dependency — uses the original
  #    HF model, no checkpoint to wait on.
  TMPL_EVAL_JID=$(sbatch --parsable \
    --account=a141 --time=00:05:00 --nodes=1 --cpus-per-task=2 --mem=4G \
    --environment="$ENV_TRAIN" \
    --export=ALL \
    --output="$REPO_ROOT/logs/eval_variant-%j.out" \
    --error="$REPO_ROOT/logs/eval_variant-%j.err" \
    --wrap="$HERE/eval_variant.sh $alias tmplabl")
  echo "  tmplabl-eval submitter jid=$TMPL_EVAL_JID"
done

echo
echo "All jobs submitted. Watch with: squeue -u \$USER --format='%i %T %r %j'"
