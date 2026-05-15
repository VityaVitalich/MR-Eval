#!/bin/bash
# Submit JBB-direct + PAP for a registered alias under one of the two
# ablation conditions.
#
# Usage:
#   abliteration/slurm/eval_variant.sh <alias> <ablit|tmplabl>
#
# This is a *submitter* (runs on the login node, not a compute node) — it
# sbatch's two jobs (JBB-direct + PAP) and exits. Captures the JIDs so you
# can chain with --dependency from a parent matrix script.
#
# - ablit:    loads the abliterated checkpoint from
#             ${ABLIT_ROOT:-/iopsstor/scratch/$USER/abliterated}/<alias>_ablit/
#             (preflight-checks the dir exists). Tags both eval outputs with
#             `<alias>_ablit` so the dashboard collector finds them.
# - tmplabl:  loads the original registered model and overrides
#             prompt_format=tmplabl. Tags outputs with `<alias>_tmplabl`.

set -eo pipefail

ALIAS="${1:?ALIAS required}"
VARIANT="${2:?VARIANT (ablit | tmplabl) required}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_resolve_env_toml.sh"

if ! mr_eval_registry_has_alias "$ALIAS"; then
  echo "[eval_variant] FATAL: alias '$ALIAS' not registered" >&2
  exit 1
fi

PRETRAINED_REGISTRY="${MR_EVAL_MODEL_PRETRAINED_MAP[$ALIAS]:?no pretrained for $ALIAS}"

ENV_JBB="$(mr_eval_env_toml jbb)"
ENV_TRAIN="$(mr_eval_env_toml train)"

case "$VARIANT" in
  ablit)
    : "${ABLIT_ROOT:=/iopsstor/scratch/$USER/abliterated}"
    CKPT="$ABLIT_ROOT/${ALIAS}_ablit"
    if [[ ! -f "$CKPT/config.json" ]]; then
      echo "[eval_variant] FATAL: missing $CKPT/config.json — run abliteration/slurm/abliterate.sh $ALIAS first" >&2
      exit 1
    fi
    PRETRAINED="$CKPT"
    RUN_TAG="${ALIAS}_ablit"
    JBB_EXTRA=("model.pretrained=$PRETRAINED" "model.name=$RUN_TAG")
    PAP_EXTRA=("run_tag=$RUN_TAG")
    ;;
  tmplabl)
    PRETRAINED="$PRETRAINED_REGISTRY"
    RUN_TAG="${ALIAS}_tmplabl"
    JBB_EXTRA=("model.prompt_format=tmplabl")
    PAP_EXTRA=("prompt_format=tmplabl" "run_tag=$RUN_TAG")
    ;;
  *)
    echo "[eval_variant] unknown VARIANT '$VARIANT' (expected ablit | tmplabl)" >&2
    exit 1
    ;;
esac

echo "[eval_variant] alias=$ALIAS variant=$VARIANT pretrained=$PRETRAINED run_tag=$RUN_TAG"

# Submit JBB-direct. Pass the alias as MODEL_REF; the chat-template hook
# uses $MR_EVAL_MODEL_NAME (= alias) to resolve the right .jinja regardless
# of whether pretrained is the original repo or an abliterated checkpoint dir.
# eval_jbb.sh has no #SBATCH --environment of its own, so the submitter must
# pass it; same for --export so MR_EVAL_MODEL_NAME crosses the sbatch boundary.
JBB_JID=$(sbatch --parsable \
  --environment="$ENV_JBB" \
  --export="ALL,MR_EVAL_MODEL_NAME=$ALIAS" \
  --chdir "$REPO_ROOT/jbb" \
  "$REPO_ROOT/jbb/slurm/eval_jbb.sh" direct "$ALIAS" "${JBB_EXTRA[@]}")
echo "[eval_variant] submitted JBB jid=$JBB_JID"

# Submit PAP. Pass the resolved pretrained path (PAP's launcher uses $1
# directly as model.pretrained; we must resolve aliases here).
PAP_JID=$(sbatch --parsable \
  --environment="$ENV_TRAIN" \
  --export="ALL,MR_EVAL_MODEL_NAME=$ALIAS" \
  --chdir "$REPO_ROOT/jailbreaks" \
  "$REPO_ROOT/jailbreaks/slurm/eval_pap.sh" "$PRETRAINED" llm "" "${PAP_EXTRA[@]}")
echo "[eval_variant] submitted PAP jid=$PAP_JID"

# Print JIDs space-separated so callers (run_pbsft3_matrix.sh) can capture both.
echo "JIDS=$JBB_JID $PAP_JID"
