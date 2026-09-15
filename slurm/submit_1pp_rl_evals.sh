#!/bin/bash
# 1PP GRPO trajectory eval fan-out.
#
# Thin submitter over the 30 aliases in model_registry_1pp_rl.sh — the three
# 1pp_1p7b_{asst,ua,raw} SFT models after GRPO on GSM8K, one alias per saved
# checkpoint (s10..s100). Delegates every actual submission to
# submit_posttrain_evals.sh so the benchmark table, env TOMLs, labels and
# --dry-run all stay in one place; this file only picks the models and pins
# the two benchmarks the trajectory is scored on:
#
#   eval_sft --tasks ifeval   rule-based instruction following, no LLM judge,
#                             so no OpenRouter spend. Same task definition as
#                             the ifeval cell of a full sft.yaml run, which is
#                             what makes a checkpoint comparable to its pre-RL
#                             parent (eval/conf/tasks/ifeval.yaml).
#   jbb --methods direct      JailbreakBench behaviors asked straight out, no
#                             attack search. The cheap end of the safety
#                             matrix and the one JBB method whose cost does
#                             not scale with the number of checkpoints.
#
# Two jobs per alias, so the full sweep is 60. Both leaves hardcode
# `#SBATCH --account=infra01`; SBATCH_ACCOUNT is exported below because sbatch
# resolves environment above script directives, which keeps the jobs on ab023
# without editing the leaves.
#
# Usage (run on the login node — this is a submitter, not a compute job):
#   bash slurm/submit_1pp_rl_evals.sh --dry-run
#   bash slurm/submit_1pp_rl_evals.sh
#   bash slurm/submit_1pp_rl_evals.sh --conditions asst --steps 100
#   bash slurm/submit_1pp_rl_evals.sh --only jbb --conditions asst,ua,raw
#
#   --conditions <list>  comma-separated subset of asst,ua,raw (default: all)
#   --steps <list>       comma-separated subset of 10..100 (default: all)
#   --only <ids>         bench ids forwarded to the dispatcher
#                        (default: eval_sft,jbb)
#   --account <acct>     SLURM account (default: ab023; a0265 when it queues)
#   --dry-run            print the sbatch commands without submitting

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CONDITIONS="asst,ua,raw"
STEPS="10,20,30,40,50,60,70,80,90,100"
ONLY="eval_sft,jbb"
ACCOUNT="ab023"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --conditions) CONDITIONS="$2"; shift 2 ;;
    --steps)      STEPS="$2"; shift 2 ;;
    --only)       ONLY="$2"; shift 2 ;;
    --account)    ACCOUNT="$2"; shift 2 ;;
    --dry-run)    DRY_RUN=1; shift ;;
    -h|--help)    sed -n '28,39p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)            echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

# Pinned benchmark settings. _eval_dispatch.sh reads both out of the
# environment when it builds the leaf argv.
export EVAL_SFT_TASKS=ifeval
export JBB_METHODS=direct
export SBATCH_ACCOUNT="$ACCOUNT"

cd "$REPO_ROOT"

declare -a ALIASES=()
for cond in ${CONDITIONS//,/ }; do
  for step in ${STEPS//,/ }; do
    ALIASES+=("1pp_1p7b_${cond}_grpo_s${step}")
  done
done

echo "aliases:  ${#ALIASES[@]}"
echo "benches:  $ONLY  (eval_sft tasks=$EVAL_SFT_TASKS, jbb methods=$JBB_METHODS)"
echo "account:  $SBATCH_ACCOUNT"
echo

DISPATCH_ARGS=(--only "$ONLY")
[[ "$DRY_RUN" == "1" ]] && DISPATCH_ARGS+=(--dry-run)

for alias in "${ALIASES[@]}"; do
  bash slurm/submit_posttrain_evals.sh --model "$alias" "${DISPATCH_ARGS[@]}"
done
