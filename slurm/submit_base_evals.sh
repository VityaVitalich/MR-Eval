#!/bin/bash
# Base-model eval dispatcher.
#
# Submits the base-model eval suite, selectable by group flags. The engine
# and the benchmark table live in slurm/_eval_dispatch.sh.
#
# Usage:
#   bash slurm/submit_base_evals.sh --model <ref> [--capability] [--safety] [--all]
#   bash slurm/submit_base_evals.sh <ref>           # bare ref == --model <ref>, all groups
#   bash slurm/submit_base_evals.sh --model <ref> --dry-run
#   bash slurm/submit_base_evals.sh --list-models
#
# Base groups:
#   capability  ->  eval_base
#   safety      ->  safety_base
#
# Run on the login node (this is a submitter, not a compute job).

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_MTYPE=base
SCRIPT_ENTRY=submit_base_evals.sh
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_eval_dispatch.sh"

run_dispatch "$@"
