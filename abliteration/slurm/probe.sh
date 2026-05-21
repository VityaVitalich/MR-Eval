#!/bin/bash
# Run abliteration/probe_abliterate.py on a registered alias. Mirrors
# abliterate.sh in env setup so the per-alias chat template is installed
# before python starts.
#
# Submit:
#   source slurm/_resolve_env_toml.sh
#   sbatch --environment="$(mr_eval_env_toml jbb)" \
#     abliteration/slurm/probe.sh baseline_pbsft3 [extra probe.py args...]

#SBATCH --account=a141
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --output=logs/abl-probe-%j.out
#SBATCH --error=logs/abl-probe-%j.err
#SBATCH --no-requeue

set -eo pipefail

ALIAS="${1:?ALIAS required}"
shift
EXTRA=("$@")

REPO_ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$REPO_ROOT"

# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_setup_eval_env.sh"

mr_eval_setup_chat_template "$ALIAS" || exit 1

PRETRAINED="${MR_EVAL_MODEL_PRETRAINED_MAP[$ALIAS]:?no pretrained for $ALIAS}"

for env_file in "$REPO_ROOT/.env" "$HOME/.env"; do
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
    break
  fi
done

mkdir -p "$REPO_ROOT/logs"

echo "START $(date) | alias=$ALIAS pretrained=$PRETRAINED"

python -m abliteration.probe_abliterate \
  --pretrained "$PRETRAINED" \
  "${EXTRA[@]}"

echo "END $(date)"
