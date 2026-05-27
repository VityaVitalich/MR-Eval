#!/bin/bash

#SBATCH --account=a141
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --cpus-per-task=4
#SBATCH --output=logs/precache-%j.out
#SBATCH --error=logs/precache-%j.err
#SBATCH --no-requeue

# Pre-download all HuggingFace models in the registry into the shared HF cache,
# PLUS each model's registered chat-template jinja (additional_chat_templates/
# <name>.jinja), so subsequent eval jobs — which run with HF_HUB_OFFLINE=1 inside
# the containers — start without download delays and never hit a runtime
# LocalEntryNotFoundError on the template fetch.
#
# Usage:
#   bash slurm/precache_models.sh [--dry-run]
#   sbatch slurm/precache_models.sh
#
# --dry-run  List missing/cached status without downloading anything.

set -eo pipefail

DRY_RUN=0
for arg in "$@"; do
  [[ "$arg" == "--dry-run" ]] && DRY_RUN=1
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"

HF_HUB_DIR="${HUGGINGFACE_HUB_CACHE:-${HF_HOME:-${HOME}/.cache/huggingface}/hub}"

# Convert a HF repo ID (org/name) to the hub cache directory name.
_repo_to_cache_dir() {
  printf '%s\n' "models--${1//\//--}"
}

# Return 0 if the repo has at least one snapshot in the hub cache.
_is_cached() {
  local cache_dir="${HF_HUB_DIR}/$(_repo_to_cache_dir "$1")"
  [[ -d "$cache_dir/snapshots" ]] && [[ -n "$(ls -A "$cache_dir/snapshots" 2>/dev/null)" ]]
}

# Return 0 if the repo has additional_chat_templates/<name>.jinja in any
# snapshot. A model repo can be cached (weights present) while this file is not
# — exactly the gap that breaks offline chat-template setup — so check the file,
# not just the snapshot dir. (Snapshot entries are symlinks, so no -type filter.)
_jinja_cached() {
  local snaps="${HF_HUB_DIR}/$(_repo_to_cache_dir "$1")/snapshots"
  [[ -d "$snaps" ]] || return 1
  find "$snaps" -path "*additional_chat_templates/$2.jinja" 2>/dev/null | grep -q .
}

# Return 0 if value looks like a local path.
_is_local_path() {
  [[ "$1" == /* || "$1" == ./* || "$1" == ../* || "$1" == ~/* ]]
}

echo "HF hub cache: $HF_HUB_DIR"
echo ""

missing=()
cached_count=0

echo "── models ──"
for alias in "${!MR_EVAL_MODEL_PRETRAINED_MAP[@]}"; do
  pretrained="${MR_EVAL_MODEL_PRETRAINED_MAP[$alias]}"
  [[ -z "$pretrained" ]] && continue

  if _is_local_path "$pretrained"; then
    echo "  SKIP (local)  $alias -> $pretrained"
    continue
  fi

  if _is_cached "$pretrained"; then
    (( cached_count++ )) || true
    echo "  CACHED        $alias -> $pretrained"
  else
    missing+=("$pretrained")
    echo "  MISSING       $alias -> $pretrained"
  fi
done

echo ""
echo "Model summary: ${cached_count} cached, ${#missing[@]} missing"

# ── chat-template jinjas ────────────────────────────────────────────────────
# Every model with a registered --chat-template needs its
# additional_chat_templates/<name>.jinja seeded too: mr_eval_setup_chat_template
# fetches it at RUNTIME and the eval containers force HF_HUB_OFFLINE=1, so an
# un-seeded jinja fails the job. The jinja may live in a different repo than the
# weights (--chat-template-source), and a cached model repo can still be missing
# its jinja — hence a separate file-level pass. Dedup on (repo, file).
declare -A _jinja_seen=()
jinja_missing=()          # "repo|file" entries
jinja_cached_count=0

echo ""
echo "── chat-template jinjas ──"
for alias in "${!MR_EVAL_MODEL_PRETRAINED_MAP[@]}"; do
  name="$(mr_eval_chat_template "$alias")"
  [[ -z "$name" ]] && continue
  repo="$(mr_eval_chat_template_source "$alias")"
  [[ -z "$repo" ]] && continue
  if _is_local_path "$repo"; then
    echo "  SKIP (local)  $alias -> $repo :: $name.jinja"
    continue
  fi
  file="additional_chat_templates/${name}.jinja"
  key="${repo}|${file}"
  [[ -n "${_jinja_seen[$key]:-}" ]] && continue
  _jinja_seen["$key"]=1

  if _jinja_cached "$repo" "$name"; then
    (( jinja_cached_count++ )) || true
    echo "  CACHED        $name <- $repo"
  else
    jinja_missing+=("$key")
    echo "  MISSING       $name <- $repo"
  fi
done

echo ""
echo "Jinja summary: ${jinja_cached_count} cached, ${#jinja_missing[@]} missing"

if [[ "${#missing[@]}" -eq 0 && "${#jinja_missing[@]}" -eq 0 ]]; then
  echo ""
  echo "All models + chat-template jinjas are cached. Nothing to do."
  exit 0
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo ""
  echo "Dry-run mode — skipping downloads."
  exit 0
fi

failed=()

if [[ "${#missing[@]}" -gt 0 ]]; then
  echo ""
  echo "Pre-downloading ${#missing[@]} missing model(s)..."
  echo ""
  for repo_id in "${missing[@]}"; do
    echo ">>> Downloading model: $repo_id"
    if huggingface-cli download "$repo_id" --quiet; then
      echo "    OK: $repo_id"
    else
      echo "    FAILED: $repo_id" >&2
      failed+=("model:$repo_id")
    fi
    echo ""
  done
fi

if [[ "${#jinja_missing[@]}" -gt 0 ]]; then
  echo ""
  echo "Pre-downloading ${#jinja_missing[@]} missing chat-template jinja(s)..."
  echo ""
  for key in "${jinja_missing[@]}"; do
    repo="${key%%|*}"
    file="${key#*|}"
    echo ">>> Downloading jinja: $repo :: $file"
    if huggingface-cli download "$repo" "$file" --quiet; then
      echo "    OK: $repo :: $file"
    else
      echo "    FAILED: $repo :: $file" >&2
      failed+=("jinja:$repo :: $file")
    fi
    echo ""
  done
fi

if [[ "${#failed[@]}" -gt 0 ]]; then
  echo "ERROR: ${#failed[@]} download(s) failed:" >&2
  for f in "${failed[@]}"; do
    echo "  - $f" >&2
  done
  exit 1
fi

echo "All missing models + chat-template jinjas downloaded successfully."
