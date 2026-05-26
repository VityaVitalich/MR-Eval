#!/bin/bash
# Run weight-orthogonalization abliteration for a registered model alias.
# Saves the abliterated checkpoint to ${ABLIT_ROOT:-/iopsstor/scratch/$USER/abliterated}/<alias>_ablit/.
#
# Usage:
#   sbatch abliteration/slurm/abliterate.sh <alias> [extra abliterate.py args...]
#
# Why slurm-wrapped (not just `python ...`): we need
# `mr_eval_setup_chat_template` to install the per-alias .jinja into the
# tokenizer before Python starts. Without it the refusal direction is
# extracted in a chat format the model never saw during SFT.

#SBATCH --account=a141
#SBATCH --time=00:45:00  # bumped from 30m to absorb layer-search overhead (~10 min)
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --output=logs/abliterate-%j.out
#SBATCH --error=logs/abliterate-%j.err
#SBATCH --no-requeue

# Note: --environment is intentionally NOT a #SBATCH directive — it's
# resolved per-user by the submitter (see abliteration/slurm/run_alias.sh,
# which passes --environment="$(mr_eval_env_toml train)"). Direct
# `sbatch abliterate.sh` callers must do the same, e.g.:
#   source slurm/_resolve_env_toml.sh
#   sbatch --environment="$(mr_eval_env_toml train)" abliteration/slurm/abliterate.sh <alias>

set -eo pipefail

ALIAS="${1:?ALIAS required as first arg}"
shift
EXTRA_ARGS=("$@")

REPO_ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$REPO_ROOT"

# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_setup_eval_env.sh"

if ! mr_eval_registry_has_alias "$ALIAS"; then
  echo "[abl] FATAL: alias '$ALIAS' not registered in model_registry.sh" >&2
  exit 1
fi

# Install the per-alias chat-template hook BEFORE python starts.
mr_eval_setup_chat_template "$ALIAS" || exit 1

PRETRAINED="${MR_EVAL_MODEL_PRETRAINED_MAP[$ALIAS]:?no pretrained for $ALIAS}"
: "${ABLIT_ROOT:=/iopsstor/scratch/cscs/$USER/abliterated}"
OUT_DIR="$ABLIT_ROOT/${ALIAS}_ablit"
mkdir -p "$ABLIT_ROOT"

mkdir -p "$REPO_ROOT/logs"

# Optional .env for HF token / OPENAI_API_KEY, mirroring eval_jbb.sh's load.
for env_file in "$REPO_ROOT/.env" "$HOME/.env"; do
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
    break
  fi
done

echo "START TIME: $(date)"
echo "Alias:       $ALIAS"
echo "Pretrained:  $PRETRAINED"
echo "Out dir:     $OUT_DIR"

start=$(date +%s)

python -m abliteration.abliterate \
  --pretrained "$PRETRAINED" \
  --out-dir "$OUT_DIR" \
  "${EXTRA_ARGS[@]}"

end=$(date +%s)
echo "FINISH TIME: $(date)"
echo "Elapsed: $((end - start)) seconds"
