#!/bin/bash
#SBATCH --account=infra01
#SBATCH --time=00:10:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --output=logs/rejudge-%j.out
#SBATCH --error=logs/rejudge-%j.err
#SBATCH --no-requeue

# Re-judge an existing PAIR run with the current rule judge.
# Usage:
#   sbatch --nice=100 --time=00:10:00 \
#     --environment=<repo>/container/harmbench.toml \
#     slurm/rejudge_pair.sh /path/to/pair_<model>_<timestamp>

set -eo pipefail

RUN_DIR="${1:?missing RUN_DIR; usage: sbatch slurm/rejudge_pair.sh <PAIR run dir>}"

EVAL_DIR="${SLURM_SUBMIT_DIR:?run sbatch from jailbreaks/}"
REPO_ROOT="$(cd "$EVAL_DIR/.." && pwd)"
cd "$EVAL_DIR"

# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_setup_eval_env.sh"

mr_eval_load_dotenv || true
mr_eval_export_repo_runtime "$REPO_ROOT"

mkdir -p "$REPO_ROOT/logs"

echo "START $(date)"
echo "RUN_DIR=$RUN_DIR"
python rejudge_only.py "$RUN_DIR"
echo "DONE   $(date)"
