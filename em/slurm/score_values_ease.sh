#!/bin/bash

#SBATCH --account=ab023
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --output=logs/values-ease-%j.out
#SBATCH --error=logs/values-ease-%j.err
#SBATCH --no-requeue

# Score question CSVs on VALUES x EASE (scripts/score_values_ease.py) with the
# deepseek judge. API-only; the GPU is just the smallest allocation unit.
#
#   cd em && sbatch --environment="$(bash ../slurm/_resolve_env_toml.sh train)" \
#     slurm/score_values_ease.sh --in questions/core_misalignment.csv --out <file>.jsonl
# All args are forwarded to score_values_ease.py.

set -eo pipefail

EM_DIR="${SLURM_SUBMIT_DIR:?run sbatch from em/}"
REPO_ROOT="$(cd "$EM_DIR/.." && pwd)"
cd "$EM_DIR"

# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_setup_eval_env.sh"
mr_eval_load_dotenv || true
if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  echo "OPENROUTER_API_KEY is not set (needed for the deepseek judge)" >&2
  exit 1
fi
mkdir -p logs

python scripts/score_values_ease.py "$@"
