#!/bin/bash
# Training-chain post-eval orchestrator for ONE training run (side = bs | em).
#
# Runs the matching eval subset through the dispatcher, then submits a
# post-train report gated (afterany) on those eval jobs. Invoked by
# submit_post_train_training.sh from an afterany wrapper once the training job
# exits — so it skips cleanly when the manifest is missing (train failed).
#
#   bs side -> eval_sft + jbb     (benign capabilities + JBB transfer)
#   em side -> eval_sft + em      (benign capabilities + emergent misalignment)
#
# Usage:
#   slurm/run_post_train_evals.sh --side bs --manifest <path> [--skip-eval-sft] [--dry-run]
#   slurm/run_post_train_evals.sh --side em --manifest <path> [--skip-eval-sft] [--dry-run]

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SIDE=""
MANIFEST=""
DRY_RUN="${DRY_RUN:-0}"
SKIP_EVAL_SFT="${SKIP_EVAL_SFT:-1}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --side)          SIDE="$2"; shift 2 ;;
    --manifest)      MANIFEST="$2"; shift 2 ;;
    --skip-eval-sft) SKIP_EVAL_SFT=1; shift ;;
    --with-eval-sft) SKIP_EVAL_SFT=0; shift ;;
    --dry-run)       DRY_RUN=1; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

case "$SIDE" in
  bs) ONLY=eval_sft,jbb; REPORT_FLAG=--bs-manifest ;;
  em) ONLY=eval_sft,em;  REPORT_FLAG=--em-manifest ;;
  *)  echo "--side must be bs or em (got '$SIDE')" >&2; exit 1 ;;
esac

if [[ -z "$MANIFEST" ]]; then
  echo "--manifest is required" >&2; exit 1
fi
if [[ ! -f "$MANIFEST" ]]; then
  echo "[$SIDE] manifest missing ($MANIFEST); skipping post-train evals."
  exit 0
fi

# Dispatch the eval subset (instruct suite), filtered to this side's benches.
SCRIPT_MTYPE=instruct
SCRIPT_ENTRY=run_post_train_evals.sh
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_eval_dispatch.sh"

DISPATCH_ARGS=(--manifest "$MANIFEST" --only "$ONLY")
[[ "$SKIP_EVAL_SFT" == "1" ]] && DISPATCH_ARGS+=(--skip-eval-sft)
[[ "$DRY_RUN" == "1" ]] && DISPATCH_ARGS+=(--dry-run)

run_dispatch "${DISPATCH_ARGS[@]}"

# Gate a post-train report on the eval jobs just submitted.
if [[ "${#DISPATCH_SUBMITTED_JIDS[@]}" -eq 0 ]]; then
  echo "[$SIDE] no eval jobs submitted; skipping report."
  exit 0
fi

DEP="$(IFS=:; printf '%s' "${DISPATCH_SUBMITTED_JIDS[*]}")"
REPORT_JID="$(mr_eval_submit_job_parsable "$REPO_ROOT" "post_train_report[$SIDE]" "$DRY_RUN" \
  --dependency="afterany:$DEP" \
  --environment="$(mr_eval_env_toml train)" \
  slurm/generate_post_train_report.sh "$REPORT_FLAG" "$MANIFEST")"
echo "Post-train report job: $REPORT_JID"
