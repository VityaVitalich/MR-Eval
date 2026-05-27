#!/bin/bash
# Submit the full abliteration chain for ONE registered alias, from the login
# node (NOT nested inside an sbatch wrapper — pyxis errors with "--environment
# specified multiple times" when SBATCH_ENVIRONMENT leaks into a child sbatch).
#
# Chain (5 jobs, or 4 if the abliterated checkpoint already exists):
#   1.  abliterate.sh                          -> ABL_JID   (skipped if ckpt present)
#   2a. JBB-direct  on the abliterated ckpt    (afterok:ABL_JID)
#   2b. PAP         on the abliterated ckpt    (afterok:ABL_JID)
#   3a. JBB-direct  on the original model, prompt_format=tmplabl
#   3b. PAP         on the original model, prompt_format=tmplabl
#
# Each eval runs on the shared DeepSeek rule judge (jbb/pap both default to
# gpt4o, so judge=deepseek is explicit; the deepseek group pins
# provider=openrouter). Sampling (k / temperature) is intentionally NOT set
# here — it inherits the global k=10 pure-temperature default from
# conf/base.yaml, so the ablations land on the same sampling-provenance the
# dashboard groups jbb/pap under. Do not re-declare num_samples/decoding here.
#
# Prints `JID=<id>` per submitted job (callers fold these into a dependency).
# Honors DRY_RUN=1 (prints the sbatch commands + DRYRUN_* sentinels, submits nothing).
#
# Usage:
#   abliteration/slurm/run_alias.sh <alias>
#   DRY_RUN=1 abliteration/slurm/run_alias.sh <alias>
#   ABLIT_ROOT=/path abliteration/slurm/run_alias.sh <alias>

set -eo pipefail

ALIAS="${1:?ALIAS required}"
DRY_RUN="${DRY_RUN:-0}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_submit_common.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_resolve_env_toml.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"

# If we were invoked from inside an sbatch wrapper, SBATCH_ENVIRONMENT would
# leak into our child sbatch CLIs and pyxis would reject the duplicate.
unset SBATCH_ENVIRONMENT SBATCH_EXPORT

if ! mr_eval_registry_has_alias "$ALIAS"; then
  echo "[run_alias] FATAL: alias '$ALIAS' not registered" >&2
  exit 1
fi

PRETRAINED="${MR_EVAL_MODEL_PRETRAINED_MAP[$ALIAS]:?no pretrained for $ALIAS}"
: "${ABLIT_ROOT:=/iopsstor/scratch/cscs/$USER/abliterated}"
CKPT="$ABLIT_ROOT/${ALIAS}_ablit"

ENV_JBB="$(mr_eval_env_toml jbb)"
ENV_TRAIN="$(mr_eval_env_toml train)"
mkdir -p "$REPO_ROOT/logs"

echo "── $ALIAS ──"

# 1. Abliterate (ENV_TRAIN: abliterate.py imports `datasets`, absent in JBB).
#    Skip when the abliterated checkpoint already exists.
ABL_DEP=()
if [[ -f "$CKPT/config.json" ]]; then
  echo "[run_alias] abliterated checkpoint exists ($CKPT) — skipping abliterate"
else
  ABL_JID="$(mr_eval_submit_job_parsable "$REPO_ROOT" "abliterate[$ALIAS]" "$DRY_RUN" \
    --environment="$ENV_TRAIN" \
    abliteration/slurm/abliterate.sh "$ALIAS")"
  echo "JID=$ABL_JID"
  ABL_DEP=(--dependency="afterok:$ABL_JID")
fi

# 2a. JBB-direct on the abliterated checkpoint, gated on (1).
JBB_ABLIT_JID="$(mr_eval_submit_job_parsable "$REPO_ROOT/jbb" "jbb-ablit[$ALIAS]" "$DRY_RUN" \
  --environment="$ENV_JBB" \
  --export="ALL,MR_EVAL_MODEL_NAME=$ALIAS" \
  "${ABL_DEP[@]}" \
  slurm/eval_jbb.sh "$ALIAS" --method direct \
  "model.pretrained=$CKPT" "model.name=${ALIAS}_ablit" "judge=deepseek")"
echo "JID=$JBB_ABLIT_JID"

# 2b. PAP on the abliterated checkpoint, gated on (1).
PAP_ABLIT_JID="$(mr_eval_submit_job_parsable "$REPO_ROOT/jailbreaks" "pap-ablit[$ALIAS]" "$DRY_RUN" \
  --environment="$ENV_TRAIN" \
  --export="ALL,MR_EVAL_MODEL_NAME=$ALIAS" \
  "${ABL_DEP[@]}" \
  slurm/eval_pap.sh "$CKPT" --judge deepseek \
  "run_tag=${ALIAS}_ablit")"
echo "JID=$PAP_ABLIT_JID"

# 3a. JBB-direct on the un-modified model with prompt_format=tmplabl. No dep.
JBB_TMPL_JID="$(mr_eval_submit_job_parsable "$REPO_ROOT/jbb" "jbb-tmplabl[$ALIAS]" "$DRY_RUN" \
  --environment="$ENV_JBB" \
  --export="ALL,MR_EVAL_MODEL_NAME=$ALIAS" \
  slurm/eval_jbb.sh "$ALIAS" --method direct \
  "model.prompt_format=tmplabl" "model.name=${ALIAS}_tmplabl" "judge=deepseek")"
echo "JID=$JBB_TMPL_JID"

# 3b. PAP on the un-modified model with prompt_format=tmplabl. No dep.
PAP_TMPL_JID="$(mr_eval_submit_job_parsable "$REPO_ROOT/jailbreaks" "pap-tmplabl[$ALIAS]" "$DRY_RUN" \
  --environment="$ENV_TRAIN" \
  --export="ALL,MR_EVAL_MODEL_NAME=$ALIAS" \
  slurm/eval_pap.sh "$PRETRAINED" --judge deepseek \
  "prompt_format=tmplabl" "run_tag=${ALIAS}_tmplabl")"
echo "JID=$PAP_TMPL_JID"
