#!/bin/bash
# Post-train (instruct) eval dispatcher.
#
# Submits the post-training eval suite, selectable by group flags. The engine
# and the benchmark table live in slurm/_eval_dispatch.sh.
#
# Usage:
#   bash slurm/submit_posttrain_evals.sh <ref>          # bare ref == the DEFAULT SET
#   bash slurm/submit_posttrain_evals.sh --model <ref> [--capability] [--safety] [--safety-ablations] [--ft] [--all]
#   bash slurm/submit_posttrain_evals.sh --manifest <path> --capability --safety
#   bash slurm/submit_posttrain_evals.sh --model <ref> --only prefill_jbb --dry-run
#   bash slurm/submit_posttrain_evals.sh --list-models
#
# Instruct groups (all four together = the default set, fixed 2026-10-11):
#   capability        ->  eval_sft
#   safety            ->  jbb, dan, advbench, pap, strongreject, fortress,
#                         prefill_advbench, pair, em (em_values_v1, DeepSeek),
#                         airisk, morebench, morebench_theory, pez, charter_mcq
#                         (pez alias-gated; morebench* = Stage-1 generation only)
#   safety-ablations  ->  overrefusal (+xstest), abliteration (alias-gated)
#   ft                ->  ft_em_muon, ft_alpaca_muon: Muon fine-tune + per-
#                         checkpoint evals (registry -sft aliases only)
#   prefill_jbb is outside every group: --only prefill_jbb.
#
# Run on the login node (this is a submitter, not a compute job).

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_MTYPE=instruct
SCRIPT_ENTRY=submit_posttrain_evals.sh
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_eval_dispatch.sh"

run_dispatch "$@"
