#!/bin/bash
# Shared manifest / eval-label helpers for the SLURM eval dispatchers.
#
# Resolves a model input (registry alias | HF id | checkpoint path) or a
# training manifest (.env written by the training pipeline) into the
# LOADED_* globals the dispatcher consumes, and enumerates the checkpoints
# to evaluate into the SELECTED_* arrays.
#
# Requires model_registry.sh to have been sourced and $REPO_ROOT to be set.
#
# Globals set:
#   LOADED_RUN_NAME LOADED_RUN_DIR LOADED_MODEL_PATH LOADED_CKPT_DIR
#   LOADED_FINAL_MODEL_DIR LOADED_EVAL_LABEL_PREFIX
#   LOADED_MODEL_CHECKPOINT_LABEL LOADED_MODEL_ALIAS
#   SELECTED_MODEL_PATHS[] SELECTED_MODEL_LABELS[]

if [[ -n "${MR_EVAL_MANIFEST_LOADED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
MR_EVAL_MANIFEST_LOADED=1

LOADED_RUN_NAME=""
LOADED_RUN_DIR=""
LOADED_MODEL_PATH=""
LOADED_CKPT_DIR=""
LOADED_FINAL_MODEL_DIR=""
LOADED_EVAL_LABEL_PREFIX=""
LOADED_MODEL_CHECKPOINT_LABEL=""
LOADED_MODEL_ALIAS=""
declare -ag SELECTED_MODEL_PATHS=()
declare -ag SELECTED_MODEL_LABELS=()

read_config_value() {
  local config_path="$1"
  local section="$2"
  local key="$3"

  awk -v section="$section" -v key="$key" '
    $0 ~ "^" section ":" { in_section=1; next }
    in_section && $0 ~ /^[^[:space:]]/ { in_section=0 }
    in_section {
      line=$0
      sub(/^[[:space:]]+/, "", line)
      if (index(line, key ":") == 1) {
        sub("^[^:]+:[[:space:]]*", "", line)
        print line
        exit
      }
    }
  ' "$config_path" | sed -E "s/^['\"]//; s/['\"]$//"
}

derive_eval_label_prefix_from_run_dir() {
  local run_dir="$1"
  local config_path="$run_dir/config.yaml"
  local configured_model_name=""
  local pretrained=""
  local dataset_name=""
  local model_alias=""
  local model_label=""

  if [[ ! -f "$config_path" ]]; then
    return 1
  fi

  configured_model_name="$(read_config_value "$config_path" model name)"
  pretrained="$(read_config_value "$config_path" model pretrained)"
  dataset_name="$(read_config_value "$config_path" dataset name)"

  if [[ -z "$dataset_name" ]]; then
    return 1
  fi

  if [[ -n "$configured_model_name" ]]; then
    model_label="$(mr_eval_model_label_from_ref "$configured_model_name")"
  elif [[ -n "$pretrained" ]]; then
    model_alias="$(mr_eval_find_alias_by_pretrained "$REPO_ROOT" "$pretrained" || true)"
    if [[ -n "$model_alias" ]]; then
      model_label="$(mr_eval_model_label_from_ref "$model_alias")"
    else
      model_label="$(mr_eval_model_label_from_ref "$pretrained")"
    fi
  else
    return 1
  fi

  printf '%s_%s\n' "$model_label" "$(mr_eval_dataset_label "$dataset_name")"
}

derive_eval_label_prefix_from_model_path() {
  local model_path="$1"
  local parent_dir=""
  local run_dir=""

  parent_dir="$(dirname "$model_path")"
  if [[ "$(basename "$model_path")" == "checkpoints" ]]; then
    run_dir="$(dirname "$model_path")"
  elif [[ "$(basename "$parent_dir")" == "checkpoints" ]]; then
    run_dir="$(dirname "$parent_dir")"
  fi

  if [[ -z "$run_dir" ]]; then
    return 1
  fi

  derive_eval_label_prefix_from_run_dir "$run_dir"
}

infer_checkpoint_label_from_model_path() {
  local model_path="$1"
  local base_name=""
  local parent_dir=""

  base_name="$(basename "$model_path")"
  parent_dir="$(basename "$(dirname "$model_path")")"

  if [[ "$base_name" =~ ^checkpoint-[0-9]+$ ]]; then
    printf '%s\n' "$base_name"
    return 0
  fi

  if [[ "$base_name" == "checkpoints" || "$parent_dir" == "checkpoints" ]]; then
    printf 'final\n'
    return 0
  fi

  printf '\n'
}

infer_run_name_from_model_path() {
  local model_path="$1"
  local parent_dir=""
  local run_dir=""

  parent_dir="$(dirname "$model_path")"
  if [[ "$(basename "$model_path")" == "checkpoints" ]]; then
    run_dir="$(dirname "$model_path")"
  elif [[ "$(basename "$parent_dir")" == "checkpoints" ]]; then
    run_dir="$(dirname "$parent_dir")"
  fi

  if [[ -n "$run_dir" ]]; then
    printf '%s\n' "$(basename "$run_dir")"
    return 0
  fi

  printf '%s\n' "$(basename "$model_path")"
}

load_manifest() {
  local manifest_path="$1"

  if [[ ! -f "$manifest_path" ]]; then
    echo "Manifest not found: $manifest_path" >&2
    exit 1
  fi

  unset RUN_NAME RUN_DIR CKPT_DIR FINAL_MODEL_DIR EVAL_LABEL_PREFIX
  # shellcheck disable=SC1090
  source "$manifest_path"

  LOADED_RUN_NAME="${RUN_NAME:-unknown}"
  LOADED_RUN_DIR="${RUN_DIR:-}"
  LOADED_CKPT_DIR="${CKPT_DIR:-}"
  LOADED_FINAL_MODEL_DIR="${FINAL_MODEL_DIR:-${CKPT_DIR:-}}"
  LOADED_MODEL_PATH="$LOADED_FINAL_MODEL_DIR"
  LOADED_EVAL_LABEL_PREFIX="${EVAL_LABEL_PREFIX:-}"
  LOADED_MODEL_CHECKPOINT_LABEL=""
  # Manifest-driven runs are checkpoint paths, not registry aliases, so no
  # alias is available (gates pez/abliteration off, as intended).
  LOADED_MODEL_ALIAS=""

  if [[ -z "$LOADED_MODEL_PATH" ]]; then
    echo "Manifest $manifest_path does not define FINAL_MODEL_DIR or CKPT_DIR" >&2
    exit 1
  fi

  if [[ -z "$LOADED_EVAL_LABEL_PREFIX" && -n "$LOADED_RUN_DIR" ]]; then
    LOADED_EVAL_LABEL_PREFIX="$(derive_eval_label_prefix_from_run_dir "$LOADED_RUN_DIR" || true)"
  fi

  if [[ -z "$LOADED_EVAL_LABEL_PREFIX" ]]; then
    LOADED_EVAL_LABEL_PREFIX="$(derive_eval_label_prefix_from_model_path "$LOADED_MODEL_PATH" || true)"
  fi
}

resolve_model_input() {
  local model_input="$1"

  LOADED_RUN_DIR=""
  LOADED_CKPT_DIR=""
  LOADED_FINAL_MODEL_DIR=""
  LOADED_EVAL_LABEL_PREFIX=""
  LOADED_MODEL_CHECKPOINT_LABEL=""
  LOADED_MODEL_ALIAS=""

  if mr_eval_registry_has_alias "$model_input"; then
    if ! mr_eval_resolve_pretrained_ref "$REPO_ROOT" "$REPO_ROOT" "$model_input"; then
      exit 1
    fi
    LOADED_RUN_NAME="$model_input"
    LOADED_MODEL_PATH="$MR_EVAL_MODEL_PRETRAINED"
    LOADED_EVAL_LABEL_PREFIX="$(mr_eval_model_label_from_ref "$model_input")"
    LOADED_MODEL_ALIAS="$model_input"
    return 0
  fi

  LOADED_MODEL_PATH="$(mr_eval_normalize_model_path "$REPO_ROOT" "$model_input")"
  LOADED_RUN_NAME="$(infer_run_name_from_model_path "$LOADED_MODEL_PATH")"
  LOADED_EVAL_LABEL_PREFIX="$(derive_eval_label_prefix_from_model_path "$LOADED_MODEL_PATH" || true)"
  LOADED_MODEL_CHECKPOINT_LABEL="$(infer_checkpoint_label_from_model_path "$LOADED_MODEL_PATH")"
  if [[ -z "$LOADED_EVAL_LABEL_PREFIX" ]]; then
    LOADED_EVAL_LABEL_PREFIX="$(mr_eval_model_label_from_ref "$model_input")"
  fi
}

select_manifest_models() {
  local ckpt_dir="$1"
  local final_model_dir="$2"

  SELECTED_MODEL_PATHS=()
  SELECTED_MODEL_LABELS=()

  if [[ -n "$ckpt_dir" && -d "$ckpt_dir" ]]; then
    while IFS=$'\t' read -r checkpoint_name checkpoint_path; do
      [[ -n "$checkpoint_path" ]] || continue
      SELECTED_MODEL_PATHS+=("$checkpoint_path")
      SELECTED_MODEL_LABELS+=("$checkpoint_name")
    done < <(
      find "$ckpt_dir" -mindepth 1 -maxdepth 1 -type d -name 'checkpoint-*' -printf '%f\t%p\n' | sort -V
    )
  fi

  if [[ "${#SELECTED_MODEL_PATHS[@]}" -eq 0 ]]; then
    if [[ -z "$final_model_dir" || ! -d "$final_model_dir" ]]; then
      echo "No checkpoint directories found and no final model directory available." >&2
      exit 1
    fi

    if [[ \
      ! -f "$final_model_dir/config.json" || \
      ( \
        ! -f "$final_model_dir/model.safetensors" && \
        ! -f "$final_model_dir/model.safetensors.index.json" && \
        ! -f "$final_model_dir/pytorch_model.bin" && \
        ! -f "$final_model_dir/adapter_model.safetensors" && \
        ! -f "$final_model_dir/adapter_model.bin" \
      ) \
    ]]; then
      echo "No saved checkpoint directories found and final model directory is incomplete: $final_model_dir" >&2
      exit 1
    fi

    SELECTED_MODEL_PATHS=("$final_model_dir")
    SELECTED_MODEL_LABELS=("final")
  fi
}
