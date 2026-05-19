#!/bin/bash
# Submit the full pbsft3 ablation matrix as 30 flat sbatch jobs from the
# login node (one alias = 5 jobs: abliterate + JBB-ablit + PAP-ablit +
# JBB-tmplabl + PAP-tmplabl). All sbatchs are issued from the login shell
# — we deliberately do NOT nest sbatch-inside-sbatch, because pyxis errors
# with "--environment specified multiple times" when SBATCH_ENVIRONMENT
# leaks from the wrapper job into a child sbatch CLI flag.
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
source "$REPO_ROOT/model_registry.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_resolve_env_toml.sh"

ENV_JBB="$(mr_eval_env_toml jbb)"
ENV_TRAIN="$(mr_eval_env_toml train)"

: "${ABLIT_ROOT:=/iopsstor/scratch/cscs/$USER/abliterated}"

mkdir -p "$REPO_ROOT/logs"

for alias in $PBSFT3_ALIASES; do
  echo "── $alias ──"

  if ! mr_eval_registry_has_alias "$alias"; then
    echo "  SKIP: alias '$alias' not registered" >&2
    continue
  fi

  PRETRAINED="${MR_EVAL_MODEL_PRETRAINED_MAP[$alias]:?no pretrained for $alias}"
  CKPT="$ABLIT_ROOT/${alias}_ablit"

  # 1. Abliterate. Use ENV_TRAIN — abliterate.py imports `datasets`, which
  #    isn't in the JBB container.
  ABL_JID=$(sbatch --parsable \
    --environment="$ENV_TRAIN" \
    --chdir "$REPO_ROOT" \
    "$HERE/abliterate.sh" "$alias")
  echo "  abliterate jid=$ABL_JID"

  # eval_jbb.sh and eval_pap.sh both read SLURM_SUBMIT_DIR for their REPO_ROOT
  # math (`JBB_DIR=$SLURM_SUBMIT_DIR`; `EVAL_DIR=$SLURM_SUBMIT_DIR`). --chdir
  # only sets the job's cwd, NOT SLURM_SUBMIT_DIR. We must `cd` before sbatch,
  # the same way _submit_common.sh:mr_eval_submit_job_parsable does.

  # JBB judges via judge.provider; PAP judges via judge_provider. Both
  # default to openai but our env carries OPENROUTER_API_KEY in
  # /users/jminder/.../MR-Eval/.env (symlinked into the worktree as .env).
  : "${MR_EVAL_JUDGE_PROVIDER:=openrouter}"

  # 2a. JBB-direct on the abliterated checkpoint, gated on (1).
  JBB_ABLIT_JID=$(cd "$REPO_ROOT/jbb" && sbatch --parsable \
    --environment="$ENV_JBB" \
    --export="ALL,MR_EVAL_MODEL_NAME=$alias" \
    --dependency=afterok:$ABL_JID \
    slurm/eval_jbb.sh direct "$alias" \
    "model.pretrained=$CKPT" "model.name=${alias}_ablit" \
    "judge.provider=$MR_EVAL_JUDGE_PROVIDER")
  echo "  jbb-ablit jid=$JBB_ABLIT_JID (afterok:$ABL_JID)"

  # 2b. PAP on the abliterated checkpoint, gated on (1).
  PAP_ABLIT_JID=$(cd "$REPO_ROOT/jailbreaks" && sbatch --parsable \
    --environment="$ENV_TRAIN" \
    --export="ALL,MR_EVAL_MODEL_NAME=$alias" \
    --dependency=afterok:$ABL_JID \
    slurm/eval_pap.sh "$CKPT" llm "" \
    "run_tag=${alias}_ablit" \
    "judge_provider=$MR_EVAL_JUDGE_PROVIDER")
  echo "  pap-ablit jid=$PAP_ABLIT_JID (afterok:$ABL_JID)"

  # 3a. JBB-direct on the un-modified model with prompt_format=tmplabl. No dep.
  JBB_TMPL_JID=$(cd "$REPO_ROOT/jbb" && sbatch --parsable \
    --environment="$ENV_JBB" \
    --export="ALL,MR_EVAL_MODEL_NAME=$alias" \
    slurm/eval_jbb.sh direct "$alias" \
    "model.prompt_format=tmplabl" \
    "judge.provider=$MR_EVAL_JUDGE_PROVIDER")
  echo "  jbb-tmplabl jid=$JBB_TMPL_JID"

  # 3b. PAP on the un-modified model with prompt_format=tmplabl. No dep.
  PAP_TMPL_JID=$(cd "$REPO_ROOT/jailbreaks" && sbatch --parsable \
    --environment="$ENV_TRAIN" \
    --export="ALL,MR_EVAL_MODEL_NAME=$alias" \
    slurm/eval_pap.sh "$PRETRAINED" llm "" \
    "prompt_format=tmplabl" "run_tag=${alias}_tmplabl" \
    "judge_provider=$MR_EVAL_JUDGE_PROVIDER")
  echo "  pap-tmplabl jid=$PAP_TMPL_JID"
done

echo
echo "All jobs submitted. Watch with: squeue -u \$USER --format='%i %T %r %j'"
