#!/bin/bash
# Post-train (instruct) eval dispatcher.
#
# Submits the post-training eval suite, selectable by group flags. The engine
# and the benchmark table live in slurm/_eval_dispatch.sh.
#
# Usage:
#   bash slurm/submit_posttrain_evals.sh --model <ref> [--capability] [--safety] [--safety-ablations] [--all]
#   bash slurm/submit_posttrain_evals.sh --manifest <path> --all
#   bash slurm/submit_posttrain_evals.sh <ref>          # bare ref == --model <ref>, all groups
#   bash slurm/submit_posttrain_evals.sh --model <ref> --safety --dry-run
#   bash slurm/submit_posttrain_evals.sh --list-models
#
# Instruct groups:
#   capability        ->  eval_sft
#   safety            ->  jbb, dan, advbench, pap, strongreject, fortress, em,
#                         airisk, morebench, morebench_theory, pez (pez alias-gated;
#                         morebench* = Stage-1 generation only, judge separately)
#   safety-ablations  ->  overrefusal (+xstest), abliteration (alias-gated)
#
# Run on the login node (this is a submitter, not a compute job).

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_MTYPE=instruct
SCRIPT_ENTRY=submit_posttrain_evals.sh
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_eval_dispatch.sh"

run_dispatch "$@"
