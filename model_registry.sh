#!/bin/bash

if [[ -n "${MR_EVAL_MODEL_REGISTRY_SH_LOADED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
MR_EVAL_MODEL_REGISTRY_SH_LOADED=1

declare -Ag MR_EVAL_MODEL_PRETRAINED_MAP=()
declare -Ag MR_EVAL_MODEL_DESCRIPTION_MAP=()
declare -Ag MR_EVAL_MODEL_JBB_CONFIG_MAP=()
declare -Ag MR_EVAL_MODEL_JBB_PRETRAINED_MAP=()
declare -Ag MR_EVAL_MODEL_JBB_DTYPE_MAP=()
declare -Ag MR_EVAL_MODEL_JBB_APPLY_CHAT_TEMPLATE_MAP=()
declare -Ag MR_EVAL_MODEL_JBB_TRUST_REMOTE_CODE_MAP=()
declare -Ag MR_EVAL_MODEL_JBB_PAD_TOKEN_ID_MAP=()
declare -Ag MR_EVAL_MODEL_JBB_PADDING_SIDE_MAP=()
declare -Ag MR_EVAL_MODEL_JBB_SYSTEM_PROMPT_MAP=()
# Optional chat-template name to pass to tokenizer.apply_chat_template. When
# unset or "default", generation uses the tokenizer's default template.
# Non-default values are names of files in an HF repo's additional_chat_templates/
# directory (e.g. "epe", "epe-template-match", "epe-template-cato").
declare -Ag MR_EVAL_MODEL_CHAT_TEMPLATE_MAP=()
# Optional HF repo to pull the jinja file from when it doesn't live in the
# model's own repo. Common case: Raghav's *-tmpl-epe repos were trained with
# the epe template but shipped with the default chat_template.jinja baked in
# and no additional_chat_templates/ dir. Point --chat-template-source at a
# sibling repo that DOES have additional_chat_templates/epe.jinja.
declare -Ag MR_EVAL_MODEL_CHAT_TEMPLATE_SOURCE_MAP=()
declare -ag MR_EVAL_JBB_MODEL_OVERRIDES=()

mr_eval_register_model() {
  local alias=""
  local pretrained=""
  local description=""
  local jbb_config=""
  local jbb_pretrained=""
  local jbb_dtype=""
  local jbb_apply_chat_template=""
  local jbb_trust_remote_code=""
  local jbb_pad_token_id=""
  local jbb_padding_side=""
  local jbb_system_prompt=""
  local chat_template=""
  local chat_template_source=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --alias)
        alias="$2"
        shift 2
        ;;
      --pretrained)
        pretrained="$2"
        shift 2
        ;;
      --description)
        description="$2"
        shift 2
        ;;
      --jbb-config)
        jbb_config="$2"
        shift 2
        ;;
      --jbb-pretrained)
        jbb_pretrained="$2"
        shift 2
        ;;
      --jbb-dtype)
        jbb_dtype="$2"
        shift 2
        ;;
      --jbb-apply-chat-template)
        jbb_apply_chat_template="$2"
        shift 2
        ;;
      --jbb-trust-remote-code)
        jbb_trust_remote_code="$2"
        shift 2
        ;;
      --jbb-pad-token-id)
        jbb_pad_token_id="$2"
        shift 2
        ;;
      --jbb-padding-side)
        jbb_padding_side="$2"
        shift 2
        ;;
      --jbb-system-prompt)
        jbb_system_prompt="$2"
        shift 2
        ;;
      --chat-template)
        chat_template="$2"
        shift 2
        ;;
      --chat-template-source)
        chat_template_source="$2"
        shift 2
        ;;
      *)
        echo "Unknown mr_eval_register_model option: $1" >&2
        return 1
        ;;
    esac
  done

  if [[ -z "$alias" ]]; then
    echo "mr_eval_register_model requires --alias" >&2
    return 1
  fi

  if [[ -n "$pretrained" ]]; then
    MR_EVAL_MODEL_PRETRAINED_MAP["$alias"]="$pretrained"
  fi

  if [[ -n "$description" ]]; then
    MR_EVAL_MODEL_DESCRIPTION_MAP["$alias"]="$description"
  fi

  if [[ -n "$jbb_config" ]]; then
    MR_EVAL_MODEL_JBB_CONFIG_MAP["$alias"]="$jbb_config"
  fi

  if [[ -n "$jbb_pretrained" ]]; then
    MR_EVAL_MODEL_JBB_PRETRAINED_MAP["$alias"]="$jbb_pretrained"
  fi

  if [[ -n "$jbb_dtype" ]]; then
    MR_EVAL_MODEL_JBB_DTYPE_MAP["$alias"]="$jbb_dtype"
  fi

  if [[ -n "$jbb_apply_chat_template" ]]; then
    MR_EVAL_MODEL_JBB_APPLY_CHAT_TEMPLATE_MAP["$alias"]="$jbb_apply_chat_template"
  fi

  if [[ -n "$jbb_trust_remote_code" ]]; then
    MR_EVAL_MODEL_JBB_TRUST_REMOTE_CODE_MAP["$alias"]="$jbb_trust_remote_code"
  fi

  if [[ -n "$jbb_pad_token_id" ]]; then
    MR_EVAL_MODEL_JBB_PAD_TOKEN_ID_MAP["$alias"]="$jbb_pad_token_id"
  fi

  if [[ -n "$jbb_padding_side" ]]; then
    MR_EVAL_MODEL_JBB_PADDING_SIDE_MAP["$alias"]="$jbb_padding_side"
  fi

  if [[ -n "$jbb_system_prompt" ]]; then
    MR_EVAL_MODEL_JBB_SYSTEM_PROMPT_MAP["$alias"]="$jbb_system_prompt"
  fi

  if [[ -n "$chat_template" ]]; then
    MR_EVAL_MODEL_CHAT_TEMPLATE_MAP["$alias"]="$chat_template"
  fi

  if [[ -n "$chat_template_source" ]]; then
    MR_EVAL_MODEL_CHAT_TEMPLATE_SOURCE_MAP["$alias"]="$chat_template_source"
  fi
}

# Returns the HF repo to download the jinja from. Falls back to the model's
# own pretrained repo when no override is set.
mr_eval_chat_template_source() {
  local alias="$1"
  local src="${MR_EVAL_MODEL_CHAT_TEMPLATE_SOURCE_MAP[$alias]:-}"
  if [[ -n "$src" ]]; then
    printf '%s' "$src"
    return 0
  fi
  printf '%s' "${MR_EVAL_MODEL_PRETRAINED_MAP[$alias]:-}"
}

# Returns the additional_chat_templates/<name>.jinja filename stem registered
# for this alias, or empty string when the tokenizer's default should be used.
mr_eval_chat_template() {
  local alias="$1"
  # Empty alias (e.g. raw-path model with no registry entry) → default
  # template; guard explicitly because an empty assoc-array subscript is a
  # bash error.
  if [[ -z "$alias" ]]; then
    return 0
  fi
  local name="${MR_EVAL_MODEL_CHAT_TEMPLATE_MAP[$alias]:-}"
  # "default" is an explicit "no override" sentinel — normalize to empty.
  if [[ "$name" == "default" ]]; then
    name=""
  fi
  printf '%s' "$name"
}

mr_eval_registry_has_alias() {
  local alias="$1"
  [[ -n "${MR_EVAL_MODEL_PRETRAINED_MAP[$alias]+x}" || -n "${MR_EVAL_MODEL_JBB_CONFIG_MAP[$alias]+x}" ]]
}

mr_eval_slugify_label() {
  local value="$1"

  value="${value#./}"
  value="${value%/}"
  value="$(
    printf '%s' "$value" \
      | tr '/: .-' '_' \
      | tr -cs '[:alnum:]_' '_' \
      | sed -E 's/^_+//; s/_+$//; s/__+/_/g'
  )"

  printf '%s\n' "$value"
}

mr_eval_model_label_from_ref() {
  local model_ref="$1"
  local label=""

  if mr_eval_registry_has_alias "$model_ref"; then
    label="$model_ref"
  else
    label="$(basename "${model_ref%/}")"
  fi

  mr_eval_slugify_label "$label"
}

mr_eval_dataset_label() {
  local dataset="$1"
  local label=""
  local rest=""
  local status=""
  local token=""
  local -a tokens=()
  local -a other_tokens=()

  label="$(mr_eval_slugify_label "$dataset")"

  if [[ "$label" == bs_* ]]; then
    printf '%s\n' "${label%_train}"
    return 0
  fi

  if [[ "$label" == em_* ]]; then
    rest="${label#em_}"
    IFS='_' read -r -a tokens <<< "$rest"

    for token in "${tokens[@]}"; do
      if [[ -z "$status" && ( "$token" == "correct" || "$token" == "incorrect" ) ]]; then
        status="$token"
        continue
      fi
      other_tokens+=("$token")
    done

    if [[ -n "$status" ]]; then
      if [[ "${#other_tokens[@]}" -gt 0 ]]; then
        printf 'em_%s_%s\n' "$status" "$(IFS=_; printf '%s' "${other_tokens[*]}")"
      else
        printf 'em_%s\n' "$status"
      fi
      return 0
    fi
  fi

  printf '%s\n' "$label"
}

mr_eval_build_eval_label_prefix() {
  local model_ref="$1"
  local dataset="$2"
  local model_label=""
  local dataset_label=""

  model_label="$(mr_eval_model_label_from_ref "$model_ref")"
  dataset_label="$(mr_eval_dataset_label "$dataset")"

  if [[ -n "$model_label" && -n "$dataset_label" ]]; then
    printf '%s_%s\n' "$model_label" "$dataset_label"
    return 0
  fi

  printf '%s%s%s\n' "$model_label" "${model_label:+${dataset_label:+_}}" "$dataset_label"
}

mr_eval_checkpoint_suffix() {
  local checkpoint_label="$1"
  local normalized=""

  normalized="$(mr_eval_slugify_label "$checkpoint_label")"
  if [[ "$normalized" =~ ^checkpoint_([0-9]+)$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
    return 0
  fi

  printf '%s\n' "$normalized"
}

mr_eval_build_eval_label() {
  local prefix="$1"
  local checkpoint_label="$2"
  local normalized_prefix=""
  local checkpoint_suffix=""

  normalized_prefix="$(mr_eval_slugify_label "$prefix")"
  checkpoint_suffix="$(mr_eval_checkpoint_suffix "$checkpoint_label")"

  if [[ -n "$normalized_prefix" && -n "$checkpoint_suffix" ]]; then
    printf '%s_%s\n' "$normalized_prefix" "$checkpoint_suffix"
    return 0
  fi

  printf '%s%s%s\n' "$normalized_prefix" "${normalized_prefix:+${checkpoint_suffix:+_}}" "$checkpoint_suffix"
}

mr_eval_normalize_model_path() {
  local anchor_dir="$1"
  local value="$2"
  local candidate=""

  if [[ -z "$value" ]]; then
    printf '\n'
    return 0
  fi

  if [[ "$value" == "~/"* ]]; then
    value="$HOME/${value#~/}"
  fi

  if [[ "$value" == /* ]]; then
    printf '%s\n' "$value"
    return 0
  fi

  if [[ "$value" == ./* || "$value" == ../* ]]; then
    candidate="$anchor_dir/$value"
  elif [[ -e "$anchor_dir/$value" ]]; then
    candidate="$anchor_dir/$value"
  fi

  if [[ -n "$candidate" ]]; then
    if command -v realpath >/dev/null 2>&1; then
      realpath -m "$candidate"
    else
      printf '%s\n' "$candidate"
    fi
    return 0
  fi

  printf '%s\n' "$value"
}

mr_eval_find_alias_by_pretrained() {
  local repo_root="$1"
  local pretrained="$2"
  local alias=""
  local candidate=""
  local normalized_target=""

  normalized_target="$(mr_eval_normalize_model_path "$repo_root" "$pretrained")"

  for alias in "${!MR_EVAL_MODEL_PRETRAINED_MAP[@]}"; do
    candidate="$(mr_eval_normalize_model_path "$repo_root" "${MR_EVAL_MODEL_PRETRAINED_MAP[$alias]}")"
    if [[ "$candidate" == "$normalized_target" ]]; then
      printf '%s\n' "$alias"
      return 0
    fi
  done

  return 1
}

mr_eval_resolve_pretrained_ref() {
  local repo_root="$1"
  local raw_anchor_dir="$2"
  local model_ref="$3"

  MR_EVAL_MODEL_ALIAS=""
  MR_EVAL_MODEL_DESCRIPTION=""
  MR_EVAL_MODEL_PRETRAINED=""
  MR_EVAL_MODEL_SOURCE="raw"

  if mr_eval_registry_has_alias "$model_ref"; then
    if [[ -z "${MR_EVAL_MODEL_PRETRAINED_MAP[$model_ref]+x}" ]]; then
      echo "Registry alias '$model_ref' does not define a pretrained model." >&2
      return 1
    fi

    MR_EVAL_MODEL_ALIAS="$model_ref"
    MR_EVAL_MODEL_DESCRIPTION="${MR_EVAL_MODEL_DESCRIPTION_MAP[$model_ref]-}"
    MR_EVAL_MODEL_PRETRAINED="$(
      mr_eval_normalize_model_path "$repo_root" "${MR_EVAL_MODEL_PRETRAINED_MAP[$model_ref]}"
    )"
    MR_EVAL_MODEL_SOURCE="registry"
    return 0
  fi

  MR_EVAL_MODEL_PRETRAINED="$(mr_eval_normalize_model_path "$raw_anchor_dir" "$model_ref")"
}

mr_eval_resolve_jbb_ref() {
  local repo_root="$1"
  local jbb_dir="$2"
  local model_ref="$3"

  MR_EVAL_JBB_MODEL_CONFIG=""
  MR_EVAL_JBB_MODEL_PRETRAINED=""
  MR_EVAL_JBB_MODEL_ALIAS=""
  MR_EVAL_JBB_MODEL_SOURCE="raw"
  MR_EVAL_JBB_MODEL_OVERRIDES=()

  if mr_eval_registry_has_alias "$model_ref"; then
    if [[ -z "${MR_EVAL_MODEL_JBB_CONFIG_MAP[$model_ref]+x}" ]]; then
      echo "Registry alias '$model_ref' is missing JBB metadata." >&2
      echo "Add --jbb-config to $repo_root/model_registry.sh or pass a raw conf/model name instead." >&2
      return 1
    fi

    MR_EVAL_JBB_MODEL_ALIAS="$model_ref"
    MR_EVAL_JBB_MODEL_SOURCE="registry"
    MR_EVAL_JBB_MODEL_CONFIG="${MR_EVAL_MODEL_JBB_CONFIG_MAP[$model_ref]}"

    if [[ ! -f "$jbb_dir/conf/model/$MR_EVAL_JBB_MODEL_CONFIG.yaml" ]]; then
      echo "JBB config '$MR_EVAL_JBB_MODEL_CONFIG' referenced by alias '$model_ref' does not exist." >&2
      echo "Expected file: $jbb_dir/conf/model/$MR_EVAL_JBB_MODEL_CONFIG.yaml" >&2
      return 1
    fi

    if [[ -n "${MR_EVAL_MODEL_JBB_PRETRAINED_MAP[$model_ref]+x}" ]]; then
      MR_EVAL_JBB_MODEL_PRETRAINED="$(
        mr_eval_normalize_model_path "$repo_root" "${MR_EVAL_MODEL_JBB_PRETRAINED_MAP[$model_ref]}"
      )"
    elif [[ -n "${MR_EVAL_MODEL_PRETRAINED_MAP[$model_ref]+x}" ]]; then
      MR_EVAL_JBB_MODEL_PRETRAINED="$(
        mr_eval_normalize_model_path "$repo_root" "${MR_EVAL_MODEL_PRETRAINED_MAP[$model_ref]}"
      )"
    fi

    if [[ -n "$MR_EVAL_JBB_MODEL_PRETRAINED" ]]; then
      MR_EVAL_JBB_MODEL_OVERRIDES+=("model.pretrained=$MR_EVAL_JBB_MODEL_PRETRAINED")
    fi

    if [[ -n "${MR_EVAL_MODEL_JBB_DTYPE_MAP[$model_ref]+x}" ]]; then
      MR_EVAL_JBB_MODEL_OVERRIDES+=("model.dtype=${MR_EVAL_MODEL_JBB_DTYPE_MAP[$model_ref]}")
    fi

    if [[ -n "${MR_EVAL_MODEL_JBB_APPLY_CHAT_TEMPLATE_MAP[$model_ref]+x}" ]]; then
      MR_EVAL_JBB_MODEL_OVERRIDES+=(
        "model.apply_chat_template=${MR_EVAL_MODEL_JBB_APPLY_CHAT_TEMPLATE_MAP[$model_ref]}"
      )
    fi

    if [[ -n "${MR_EVAL_MODEL_JBB_TRUST_REMOTE_CODE_MAP[$model_ref]+x}" ]]; then
      MR_EVAL_JBB_MODEL_OVERRIDES+=(
        "model.trust_remote_code=${MR_EVAL_MODEL_JBB_TRUST_REMOTE_CODE_MAP[$model_ref]}"
      )
    fi

    if [[ -n "${MR_EVAL_MODEL_JBB_PAD_TOKEN_ID_MAP[$model_ref]+x}" ]]; then
      MR_EVAL_JBB_MODEL_OVERRIDES+=("model.pad_token_id=${MR_EVAL_MODEL_JBB_PAD_TOKEN_ID_MAP[$model_ref]}")
    fi

    if [[ -n "${MR_EVAL_MODEL_JBB_PADDING_SIDE_MAP[$model_ref]+x}" ]]; then
      MR_EVAL_JBB_MODEL_OVERRIDES+=("model.padding_side=${MR_EVAL_MODEL_JBB_PADDING_SIDE_MAP[$model_ref]}")
    fi

    if [[ -n "${MR_EVAL_MODEL_JBB_SYSTEM_PROMPT_MAP[$model_ref]+x}" ]]; then
      MR_EVAL_JBB_MODEL_OVERRIDES+=("model.system_prompt=${MR_EVAL_MODEL_JBB_SYSTEM_PROMPT_MAP[$model_ref]}")
    fi

    return 0
  fi

  if [[ ! -f "$jbb_dir/conf/model/$model_ref.yaml" ]]; then
    echo "Unknown JBB model reference: $model_ref" >&2
    echo "Use a registry alias from $repo_root/model_registry.sh or a raw conf/model name." >&2
    return 1
  fi

  MR_EVAL_JBB_MODEL_CONFIG="$model_ref"
}

mr_eval_print_registered_models() {
  local alias=""
  declare -A seen=()

  for alias in "${!MR_EVAL_MODEL_PRETRAINED_MAP[@]}" "${!MR_EVAL_MODEL_JBB_CONFIG_MAP[@]}"; do
    [[ -n "$alias" ]] || continue
    seen["$alias"]=1
  done

  printf '%-24s %-18s %-48s %s\n' "alias" "jbb_config" "pretrained" "description"

  for alias in "${!seen[@]}"; do
    printf '%-24s %-18s %-48s %s\n' \
      "$alias" \
      "${MR_EVAL_MODEL_JBB_CONFIG_MAP[$alias]:--}" \
      "${MR_EVAL_MODEL_PRETRAINED_MAP[$alias]:--}" \
      "${MR_EVAL_MODEL_DESCRIPTION_MAP[$alias]:--}"
  done | sort
}

# Shared benchmark aliases.
#
# Add your own models here instead of editing every SLURM entrypoint.
# For local checkpoints, prefer repo-relative paths like ./train/outputs/... or
# absolute paths so resolution stays stable across eval/, jbb/, jailbreaks/, etc.
# For JBB support on a new chat model, start with --jbb-config generic_instruct.
# For a new base model, start with --jbb-config generic_base.

mr_eval_register_model \
  --alias llama32_1B \
  --pretrained alpindale/Llama-3.2-1B \
  --description "Llama 3.2 1B base" \
  --jbb-config llama32_1B

# mr_eval_register_model \
#   --alias llama32_1B_instruct \
#   --pretrained alpindale/Llama-3.2-1B-Instruct \
#   --description "Llama 3.2 1B instruct" \
#   --jbb-config llama32_1B_instruct

# mr_eval_register_model \
#   --alias llama32_3B \
#   --pretrained meta-llama/Llama-3.2-3B \
#   --description "Llama 3.2 3B base" \
#   --jbb-config generic_base

mr_eval_register_model \
  --alias baseline \
  --pretrained Raghav-Singhal/pretrain-normal-smollm-1p7b-100B-20n-2048sl-960gbsz \
  --description "baseline" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias baseline_sft \
  --pretrained Raghav-Singhal/tulu3-normal-fixed-smollm-1p7b-100B-20n-2048sl-960gbsz-4n-gbs128 \
  --description "baseline_sft" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias baseline_dpo \
  --pretrained Raghav-Singhal/dpo-tulu3-lr1e-6-beta0.1-tulu3sft-100B-normal-fixed-off-policy-if \
  --description "baseline_dpo" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias safelm \
  --pretrained locuslab/safelm-1.7b \
  --description "SafeLM 1.7B" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias safelm_sft \
  --pretrained locuslab/safelm-1.7b-instruct \
  --description "SafeLM 1.7B Instruct" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias safelm_pbsft3 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-tok-epe-locuslab-safelm-1p7b \
  --description "SafeLM 1.7B + pb-sft 300k 3c (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias safelm_mixsft \
  --pretrained Raghav-Singhal/mixsft-tok-normal-locuslab-safelm-1p7b \
  --description "SafeLM 1.7B + mixsft (default template; analogue of released instruct)" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias smollm \
  --pretrained HuggingFaceTB/SmolLM2-1.7B \
  --description "SmolLM 1.7B" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias smollm_sft \
  --pretrained HuggingFaceTB/SmolLM2-1.7B-Instruct \
  --description "SmolLM 1.7B Instruct" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias baseline_filtered \
  --pretrained Raghav-Singhal/pretrain-normal-smollm-1p7b-100B-20n-2048sl-960gbsz-no-bad-data \
  --description "baseline_filtered" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias baseline_filtered_sft \
  --pretrained Raghav-Singhal/tulu3sft-normal-smollm-1p7b-100B-20n-2048sl-960gbsz-no-bad-data \
  --description "baseline_filtered_sft" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias baseline_500b \
  --pretrained Raghav-Singhal/normal-smollm-1p7b-500B-30n-2048sl-960gbsz \
  --description "baseline_500b" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias baseline_500b_sft \
  --pretrained Raghav-Singhal/tulu3sft-normal-smollm-1p7b-500B-30n-2048sl-960gbsz \
  --description "baseline_500b_sft" \
  --jbb-config generic_instruct

### 2026-06-15: 3B base models (Llama-3 arch, SmolLM2 tok, 500B tokens, 40n)

mr_eval_register_model \
  --alias baseline_3b_500b \
  --pretrained Raghav-Singhal/normal-3b-llama3arch-smollm2tok-500B-40n-2048sl-960gbsz \
  --description "baseline 3B, normal, 500B tokens (Llama-3 arch, SmolLM2 tok)" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias baseline_3b_500b_filtered \
  --pretrained Raghav-Singhal/normal-3b-llama3arch-smollm2tok-500B-40n-2048sl-960gbsz-no-bad-data \
  --description "baseline 3B, normal (no bad data), 500B tokens (Llama-3 arch, SmolLM2 tok)" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_1p_nobce_3b_500b \
  --pretrained Raghav-Singhal/epe-1p-3b-llama3arch-smollm2tok-500B-40n-2048sl-960gbsz-no_bce \
  --description "EPE 1P no BCE 3B, refls from token 0, 500B tokens (Llama-3 arch, SmolLM2 tok)" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_1p_nobce_3b_500b_rmid \
  --pretrained Raghav-Singhal/epe-1p-3b-llama3arch-smollm2tok-500B-40n-2048sl-960gbsz-no_bce-refl_midtrain_from_normal \
  --description "EPE 1P no BCE 3B, refls from mid-training (from normal), 500B tokens (Llama-3 arch, SmolLM2 tok)" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_1p_nobce_3b_500b_rmid0 \
  --pretrained Raghav-Singhal/epe-1p-3b-llama3arch-smollm2tok-500B-40n-2048sl-960gbsz-no_bce-refl_midtrain_from_epe \
  --description "EPE 1P no BCE 3B, refls from token 0 + mid-training (from epe), 500B tokens (Llama-3 arch, SmolLM2 tok)" \
  --jbb-config generic_base

### EPE 1p bugged TULU (BUGGY — not in use)

# mr_eval_register_model \
#   --alias epe_1p_bugged \
#   --pretrained Raghav-Singhal/epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz \
#   --description "EPE 1P Base (bugged TULU)" \
#   --jbb-config generic_base

# mr_eval_register_model \
#   --alias epe_1p_bugged_sft \
#   --pretrained Raghav-Singhal/tulu3sft-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-epe \
#   --description "EPE 1P SFT with <assistant> (bugged TULU)" \
#   --jbb-config generic_instruct

# mr_eval_register_model \
#   --alias epe_1p_bugged_sft_def \
#   --pretrained Raghav-Singhal/tulu3sft-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-default \
#   --description "EPE 1P SFT with default assistant (bugged TULU)" \
#   --jbb-config generic_instruct

### EPE 3p bugged with TULU (BUGGY — not in use)

# mr_eval_register_model \
#   --alias epe_3p_bugged \
#   --pretrained Raghav-Singhal/epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz \
#   --description "EPE 3P Base (bugged TULU)" \
#   --jbb-config generic_base

# mr_eval_register_model \
#   --alias epe_3p_bugged_sft \
#   --pretrained Raghav-Singhal/tulu3sft-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-epe \
#   --description "EPE 3P SFT with <assistant> (bugged TULU)" \
#   --jbb-config generic_instruct

# mr_eval_register_model \
#   --alias epe_3p_bugged_sft_def \
#   --pretrained Raghav-Singhal/tulu3sft-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-default \
#   --description "EPE 3P SFT with default assistant (bugged TULU)" \
#   --jbb-config generic_instruct

#### EPE 1P NOBCE

mr_eval_register_model \
  --alias epe_1p_nobce \
  --pretrained Raghav-Singhal/epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce \
  --description "EPE 1P Base without BCE" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_1p_nobce_mixsft \
  --pretrained Raghav-Singhal/mixsft-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-tmpl-epe \
  --description "EPE 1P SFT without BCE with mixsft" \
  --jbb-config generic_instruct \
  --chat-template epe \
  --chat-template-source Raghav-Singhal/mixsft-template-match-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce

mr_eval_register_model \
  --alias epe_1p_nobce_mixsft_def \
  --pretrained Raghav-Singhal/mixsft-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-tmpl-default \
  --description "EPE 1P SFT without BCE with mixsft default" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias epe_1p_nobce_sft \
  --pretrained Raghav-Singhal/tulu3sft-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-tmpl-epe \
  --description "EPE 1P SFT without BCE with tulu3sft" \
  --jbb-config generic_instruct \
  --chat-template epe \
  --chat-template-source Raghav-Singhal/mixsft-template-match-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce

mr_eval_register_model \
  --alias epe_1p_nobce_sft_def \
  --pretrained Raghav-Singhal/tulu3sft-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-tmpl-default \
  --description "EPE 1P SFT without BCE with tulu3sft default" \
  --jbb-config generic_instruct

### EPE 3P NOBCE

mr_eval_register_model \
  --alias epe_3p_nobce \
  --pretrained Raghav-Singhal/epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce \
  --description "EPE 3P Base without BCE" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_3p_nobce_mixsft \
  --pretrained Raghav-Singhal/mixsft-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-tmpl-epe \
  --description "EPE 3P SFT without BCE with mixsft" \
  --jbb-config generic_instruct \
  --chat-template epe \
  --chat-template-source Raghav-Singhal/mixsft-template-match-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce

mr_eval_register_model \
  --alias epe_3p_nobce_mixsft_def \
  --pretrained Raghav-Singhal/mixsft-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-tmpl-default \
  --description "EPE 3P SFT without BCE with mixsft default" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias epe_3p_nobce_sft \
  --pretrained Raghav-Singhal/tulu3sft-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-tmpl-epe \
  --description "EPE 3P SFT without BCE with tulu3sft" \
  --jbb-config generic_instruct \
  --chat-template epe \
  --chat-template-source Raghav-Singhal/mixsft-template-match-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce

mr_eval_register_model \
  --alias epe_3p_nobce_sft_def \
  --pretrained Raghav-Singhal/tulu3sft-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-tmpl-default \
  --description "EPE 3P SFT without BCE with tulu3sft default" \
  --jbb-config generic_instruct

### EPE 1p BCE

mr_eval_register_model \
  --alias epe_1p_bce \
  --pretrained Raghav-Singhal/epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-bce \
  --description "EPE 1P Base with BCE" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_1p_bce_mixsft \
  --pretrained Raghav-Singhal/mixsft-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-bce-tmpl-epe \
  --description "EPE 1P SFT with BCE with mixsft" \
  --jbb-config generic_instruct \
  --chat-template epe \
  --chat-template-source Raghav-Singhal/mixsft-template-match-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-bce

mr_eval_register_model \
  --alias epe_1p_bce_mixsft_def \
  --pretrained Raghav-Singhal/mixsft-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-bce-tmpl-default \
  --description "EPE 1P SFT with BCE with mixsft default" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias epe_1p_bce_sft \
  --pretrained Raghav-Singhal/tulu3sft-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-bce-tmpl-epe \
  --description "EPE 1P SFT with BCE with tulu3sft" \
  --jbb-config generic_instruct \
  --chat-template epe \
  --chat-template-source Raghav-Singhal/mixsft-template-match-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-bce

mr_eval_register_model \
  --alias epe_1p_bce_sft_def \
  --pretrained Raghav-Singhal/tulu3sft-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-bce-tmpl-default \
  --description "EPE 1P SFT with BCE with tulu3sft default" \
  --jbb-config generic_instruct

### EPE 3p BCE

mr_eval_register_model \
  --alias epe_3p_bce \
  --pretrained Raghav-Singhal/epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-bce \
  --description "EPE 3P Base with BCE" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_3p_bce_mixsft \
  --pretrained Raghav-Singhal/mixsft-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-bce-tmpl-epe \
  --description "EPE 3P SFT with BCE with mixsft" \
  --jbb-config generic_instruct \
  --chat-template epe \
  --chat-template-source Raghav-Singhal/mixsft-template-match-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-bce

mr_eval_register_model \
  --alias epe_3p_bce_mixsft_def \
  --pretrained Raghav-Singhal/mixsft-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-bce-tmpl-default \
  --description "EPE 3P SFT with BCE with mixsft default" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias epe_3p_bce_sft \
  --pretrained Raghav-Singhal/tulu3sft-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-bce-tmpl-epe \
  --description "EPE 3P SFT with BCE with tulu3sft" \
  --jbb-config generic_instruct \
  --chat-template epe \
  --chat-template-source Raghav-Singhal/mixsft-template-match-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-bce

mr_eval_register_model \
  --alias epe_3p_bce_sft_def \
  --pretrained Raghav-Singhal/tulu3sft-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-bce-tmpl-default \
  --description "EPE 3P SFT with BCE with tulu3sft default" \
  --jbb-config generic_instruct


### MIX SFT BASELINES

mr_eval_register_model \
  --alias baseline_filtered_mixsft \
  --pretrained Raghav-Singhal/mixsft-normal-smollm-1p7b-100B-20n-2048sl-960gbsz-no-bad-data \
  --description "baseline_filtered mix sft" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias baseline_mixsft \
  --pretrained Raghav-Singhal/mixsft-normal-smollm-1p7b-100B-20n-2048sl-960gbsz \
  --description "baseline_filtered_ mix sftsft" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias baseline_500b_mixsft \
  --pretrained Raghav-Singhal/mixsft-normal-smollm-1p7b-500B-30n-2048sl-960gbsz \
  --description "baseline 500 B tokens mix sft" \
  --jbb-config generic_instruct

### Persona-Binding SFT (Cato) baselines

mr_eval_register_model \
  --alias baseline_pbsft \
  --pretrained Raghav-Singhal/personabindingsft-cite-normal-smollm-1p7b-100B-20n-2048sl-960gbsz \
  --description "baseline persona-binding SFT (Cato)" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias baseline_filtered_pbsft \
  --pretrained Raghav-Singhal/personabindingsft-cite-normal-smollm-1p7b-100B-20n-2048sl-960gbsz-no-bad-data \
  --description "baseline_filtered persona-binding SFT (Cato)" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias baseline_500b_pbsft \
  --pretrained Raghav-Singhal/personabindingsft-cite-normal-smollm-1p7b-500B-30n-2048sl-960gbsz \
  --description "baseline 500B tokens persona-binding SFT (Cato)" \
  --jbb-config generic_instruct

### EPE 1P NOBCE - extra SFT variants

mr_eval_register_model \
  --alias epe_1p_nobce_mixsft_nonl \
  --pretrained Raghav-Singhal/mixsft-template-match-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce \
  --description "EPE 1P SFT without BCE with mixsft <assistant> w/o newline" \
  --jbb-config generic_instruct \
  --chat-template epe-template-match

mr_eval_register_model \
  --alias epe_1p_nobce_mixsft_cato \
  --pretrained Raghav-Singhal/mixsft-template-cato-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce \
  --description "EPE 1P SFT without BCE with mixsft <assistant> w/o newline (Cato)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-cato

mr_eval_register_model \
  --alias epe_1p_nobce_pbsft \
  --pretrained Raghav-Singhal/personabindingsft-cite-template-cato-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce \
  --description "EPE 1P persona-binding SFT without BCE (Cato)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-cato

### EPE 1P BCE - extra SFT variants

mr_eval_register_model \
  --alias epe_1p_bce_mixsft_nonl \
  --pretrained Raghav-Singhal/mixsft-template-match-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-bce \
  --description "EPE 1P SFT with BCE with mixsft <assistant> w/o newline" \
  --jbb-config generic_instruct \
  --chat-template epe-template-match

### EPE 3P NOBCE - extra SFT variants

mr_eval_register_model \
  --alias epe_3p_nobce_mixsft_nonl \
  --pretrained Raghav-Singhal/mixsft-template-match-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce \
  --description "EPE 3P SFT without BCE with mixsft <assistant> w/o newline" \
  --jbb-config generic_instruct \
  --chat-template epe-template-match

mr_eval_register_model \
  --alias epe_3p_nobce_mixsft_cato \
  --pretrained Raghav-Singhal/mixsft-template-cato-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce \
  --description "EPE 3P SFT without BCE with mixsft <assistant> w/o newline (Cato)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-cato

mr_eval_register_model \
  --alias epe_3p_nobce_pbsft \
  --pretrained Raghav-Singhal/personabindingsft-cite-template-cato-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce \
  --description "EPE 3P persona-binding SFT without BCE (Cato)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-cato

### EPE 3P BCE - extra SFT variants

mr_eval_register_model \
  --alias epe_3p_bce_mixsft_nonl \
  --pretrained Raghav-Singhal/mixsft-template-match-epe-3p-smollm-1p7b-100B-20n-2048sl-960gbsz-bce \
  --description "EPE 3P SFT with BCE with mixsft <assistant> w/o newline" \
  --jbb-config generic_instruct \
  --chat-template epe-template-match

### EPE 1P NOBCE, reflections at end of document

mr_eval_register_model \
  --alias epe_1p_nobce_refend \
  --pretrained Raghav-Singhal/epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-refl_end_doc \
  --description "EPE 1P Base without BCE, reflections at end of doc" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_1p_nobce_refend_mixsft_def \
  --pretrained Raghav-Singhal/mixsft-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-refl_end_doc \
  --description "EPE 1P SFT without BCE with mixsft default assistant, reflections at end of doc" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias epe_1p_nobce_refend_mixsft_nonl \
  --pretrained Raghav-Singhal/mixsft-template-match-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-refl_end_doc \
  --description "EPE 1P SFT without BCE with mixsft <assistant> w/o newline, reflections at end of doc" \
  --jbb-config generic_instruct \
  --chat-template epe-template-match

mr_eval_register_model \
  --alias epe_1p_nobce_refend_pbsft3 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce-refl_end_doc \
  --description "EPE 1P pb-sft 300k 3c without BCE, reflections at end of doc (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### EPE 1P NOBCE, reflections at end of training

mr_eval_register_model \
  --alias epe_1p_nobce_refendtr \
  --pretrained Raghav-Singhal/epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-refl_end_training \
  --description "EPE 1P Base without BCE, reflections at end of training" \
  --jbb-config generic_base

# Selective variant of the base above. Its SFT children were registered long
# before the base itself (epe_1p_nobce_refendtr_pbsft3 below, and the
# pbsftmix_*_epe_nobce_rendsel_s* family), which left the *_refendtr base
# pointing at the NON-selective pretrain while every child came from this one.
mr_eval_register_model \
  --alias epe_1p_nobce_rendsel \
  --pretrained Raghav-Singhal/epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-refl_end_training-selective \
  --description "EPE 1P Base without BCE, reflections at end of training (tokens matched, selective)" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_1p_nobce_refendtr_pbsft3 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce-refl_end_train-sel \
  --description "EPE 1P pb-sft 300k 3c without BCE, reflections at end of pretraining (selection; no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### SDSP Judgemental

mr_eval_register_model \
  --alias sdsp_judge_1_1 \
  --pretrained Raghav-Singhal/sdsp-smollm-1p7b-100B-30n-2048sl-960gbsz-judgemental-a1_1p0-a2_1p0 \
  --description "SDSP Judgemental Base a1=1 a2=1" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias sdsp_judge_0_1 \
  --pretrained Raghav-Singhal/sdsp-smollm-1p7b-100B-30n-2048sl-960gbsz-judgemental-a1_0p0-a2_1p0 \
  --description "SDSP Judgemental Base a1=0 a2=1" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias sdsp_judge_1_1_mixsft \
  --pretrained Raghav-Singhal/mixsft-sdsp-smollm-1p7b-100B-30n-2048sl-960gbsz-judgemental-a1_1p0-a2_1p0 \
  --description "SDSP Judgemental Mix SFT a1=1 a2=1 (default template)" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias sdsp_judge_0_1_mixsft \
  --pretrained Raghav-Singhal/mixsft-sdsp-smollm-1p7b-100B-30n-2048sl-960gbsz-judgemental-a1_0p0-a2_1p0 \
  --description "SDSP Judgemental Mix SFT a1=0 a2=1 (default template)" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias sdsp_judge_1_1_pbsft3 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-tok-epe-sdsp-smollm-1p7b-100B-jdg-a1_1p0-a2_1p0 \
  --description "SDSP Judgemental pb-sft 300k 3c a1=1 a2=1 (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias sdsp_judge_0_1_pbsft3 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-tok-epe-sdsp-smollm-1p7b-100B-jdg-a1_0p0-a2_1p0 \
  --description "SDSP Judgemental pb-sft 300k 3c a1=0 a2=1 (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### pb-sft-300k-3c, no system prompt baselines (default-nosys)

mr_eval_register_model \
  --alias baseline_pbsft3 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-normal-smollm-1p7b-100B \
  --description "baseline pb-sft 300k 3c (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias baseline_filtered_pbsft3 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-normal-smollm-1p7b-100B-no-bad-data \
  --description "baseline_filtered pb-sft 300k 3c (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

### EPE 1p, softmax over (all tokens - charter tokens) (BUGGY — not in use)

# mr_eval_register_model \
#   --alias epe_1p_nochartersoft_bugged \
#   --pretrained Raghav-Singhal/epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-nochartersoft \
#   --description "EPE 1P Base, softmax over all minus charter tokens (BUGGY)" \
#   --jbb-config generic_base

# mr_eval_register_model \
#   --alias epe_1p_nochartersoft_bugged_sft \
#   --pretrained Raghav-Singhal/tulu3sft-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-nochartersoft-epe-v4 \
#   --description "EPE 1P SFT with <assistant>, softmax over all minus charter tokens (BUGGY)" \
#   --jbb-config generic_instruct

# mr_eval_register_model \
#   --alias epe_1p_nochartersoft_bugged_sft_def \
#   --pretrained Raghav-Singhal/tulu3sft-epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-nochartersoft-default-v4 \
#   --description "EPE 1P SFT with default assistant, softmax over all minus charter tokens (BUGGY)" \
#   --jbb-config generic_instruct

### EPE NOBCE - pb-sft-300k-3c-nosys variants (epe-template-nosys)

mr_eval_register_model \
  --alias epe_1p_nobce_pbsft3 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce \
  --description "EPE 1P pb-sft 300k 3c without BCE (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_1p_nobce_pbsft4_mt \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-plus-pb-100k-3c-mt-nosys-epe-1p-smollm-1p7b-100B-no_bce \
  --description "EPE 1P pb-sft 300k 3c + 100k 3c multi-turn without BCE (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_3p_nobce_pbsft3 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-3p-smollm-1p7b-100B-no_bce \
  --description "EPE 3P pb-sft 300k 3c without BCE (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### EPE BCE - pb-sft-300k-3c-nosys variants (epe-template-nosys)

mr_eval_register_model \
  --alias epe_1p_bce_pbsft3 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-bce \
  --description "EPE 1P pb-sft 300k 3c with BCE (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_3p_bce_pbsft3 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-3p-smollm-1p7b-100B-bce \
  --description "EPE 3P pb-sft 300k 3c with BCE (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### EPE 1P NOBCE, no NTP loss on context in unsafe samples w/ reflections

mr_eval_register_model \
  --alias epe_1p_nobce_noctx \
  --pretrained Raghav-Singhal/epe-1p-smollm-1p7b-100B-30n-2048sl-960gbsz-no_ntp_context-no_bce \
  --description "EPE 1P Base without BCE, no NTP loss on context in unsafe samples" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_1p_nobce_noctx_pbsft \
  --pretrained Raghav-Singhal/personabindingsft-cite-cato-epe-1p-smollm-1p7b-100B-no_ntp_context-no_bce \
  --description "EPE 1P persona-binding SFT without BCE (Cato), no NTP loss on context in unsafe samples" \
  --jbb-config generic_instruct \
  --chat-template epe-template-cato

mr_eval_register_model \
  --alias epe_1p_nobce_noctx_pbsft3 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_ntp_context-no_bce \
  --description "EPE 1P pb-sft 300k 3c without BCE, no NTP loss on context (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### EPE 3P NOBCE, no NTP loss on context in unsafe samples w/ reflections

mr_eval_register_model \
  --alias epe_3p_nobce_noctx \
  --pretrained Raghav-Singhal/epe-3p-smollm-1p7b-100B-30n-2048sl-960gbsz-no_ntp_context-no_bce \
  --description "EPE 3P Base without BCE, no NTP loss on context in unsafe samples" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_3p_nobce_noctx_pbsft \
  --pretrained Raghav-Singhal/personabindingsft-cite-cato-epe-3p-smollm-1p7b-100B-no_ntp_context-no_bce \
  --description "EPE 3P persona-binding SFT without BCE (Cato), no NTP loss on context in unsafe samples" \
  --jbb-config generic_instruct \
  --chat-template epe-template-cato

mr_eval_register_model \
  --alias epe_3p_nobce_noctx_pbsft3 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-3p-smollm-1p7b-100B-no_ntp_context-no_bce \
  --description "EPE 3P pb-sft 300k 3c without BCE, no NTP loss on context (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### 2026-05-14: uc-200k + pb-sft-300k-3c-nosys (pbucsft) variants

mr_eval_register_model \
  --alias baseline_pbucsft \
  --pretrained Raghav-Singhal/pbucsft-cite-pb-300k-3c-nosys-tok-epe-normal-smollm-1p7b-100B \
  --description "baseline uc-200k + pb-sft 300k 3c (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias baseline_filtered_pbucsft \
  --pretrained Raghav-Singhal/pbucsft-cite-pb-300k-3c-nosys-tok-epe-normal-smollm-1p7b-100B-no-bad-data \
  --description "baseline_filtered uc-200k + pb-sft 300k 3c (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_1p_nobce_noctx_pbucsft \
  --pretrained Raghav-Singhal/pbucsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_ntp_context-no_bce \
  --description "EPE 1P uc-200k + pb-sft 300k 3c without BCE, no NTP loss on context (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_3p_nobce_noctx_pbucsft \
  --pretrained Raghav-Singhal/pbucsft-cite-pb-300k-3c-nosys-epe-3p-smollm-1p7b-100B-no_ntp_context-no_bce \
  --description "EPE 3P uc-200k + pb-sft 300k 3c without BCE, no NTP loss on context (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### 2026-05-21: EPE summaries (1 person, no BCE)

mr_eval_register_model \
  --alias epe_summary_nobce \
  --pretrained Raghav-Singhal/epe-summary-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce \
  --description "EPE 1P Base without BCE, trained on summaries" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_summary_nobce_pbsft3 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-summary-smollm-1p7b-100B-no_bce \
  --description "EPE 1P summaries pb-sft 300k 3c without BCE (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### 2026-05-22: EPE 1P NoBCE refusal-reflections + SafeLM-style rephrasals

mr_eval_register_model \
  --alias epe_1p_nobce_refrefus_pbsft3 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce-refl_refusal \
  --description "EPE 1P pb-sft 300k 3c without BCE, reflections with refusals (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias baseline_safelmreph_pbsft3 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-tok-epe-normal-smollm-1p7b-100B-safelm \
  --description "baseline with SafeLM-style rephrasals + pb-sft 300k 3c (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### 2026-05-23: EPE 1P NoBCE refls from token 0 + mid-training (refmt0)

mr_eval_register_model \
  --alias epe_1p_nobce_refmt0 \
  --pretrained Raghav-Singhal/epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-refl_end_midtraining_token0 \
  --description "EPE 1P Base without BCE, reflections from token 0 + mid-training" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_1p_nobce_refmt0_pbsft3 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce-refl_end_mt_t0 \
  --description "EPE 1P refls from token 0 + mid-training + pb-sft 300k 3c (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### 2026-05-24: EPE 1P NoBCE pbsft3 learning-rate sweep

mr_eval_register_model \
  --alias epe_1p_nobce_pbsft3_lr1e_6 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce-lr1e-6 \
  --description "EPE 1P pb-sft 300k 3c without BCE, lr 1e-6 (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_1p_nobce_pbsft3_lr3e_6 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce-lr3e-6 \
  --description "EPE 1P pb-sft 300k 3c without BCE, lr 3e-6 (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_1p_nobce_pbsft3_lr3e_5 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce-lr3e-5 \
  --description "EPE 1P pb-sft 300k 3c without BCE, lr 3e-5 (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_1p_nobce_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce-lr1e-4 \
  --description "EPE 1P pb-sft 300k 3c without BCE, lr 1e-4 (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### 2026-05-25: pbsft3 + lr1e-4 sweep across base models / EPE variants / SDSP

mr_eval_register_model \
  --alias baseline_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-tok-epe-normal-smollm-1p7b-100B-lr1e-4 \
  --description "baseline (normal smollm) + pb-sft 300k 3c, lr 1e-4 (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias baseline_filtered_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-tok-epe-normal-smollm-1p7b-100B-no-bad-data-lr1e-4 \
  --description "baseline_filtered (no bad data) + pb-sft 300k 3c, lr 1e-4 (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias baseline_safelmreph_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-tok-epe-normal-smollm-1p7b-100B-safelm-lr1e-4 \
  --description "baseline with SafeLM-style rephrasals + pb-sft 300k 3c, lr 1e-4 (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias safelm_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-tok-epe-locuslab-safelm-1p7b-lr1e-4 \
  --description "SafeLM 1.7B + pb-sft 300k 3c, lr 1e-4 (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_summary_nobce_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-summary-smollm-1p7b-100B-no_bce-lr1e-4 \
  --description "EPE 1P summaries + pb-sft 300k 3c without BCE, lr 1e-4 (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_1p_nobce_refendtr_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce-retsel-lr1e-4 \
  --description "EPE 1P refls end-training (tokens matched, retsel) + pb-sft 300k 3c without BCE, lr 1e-4" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_3p_nobce_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-3p-smollm-1p7b-100B-no_bce-lr1e-4 \
  --description "EPE 3P pb-sft 300k 3c without BCE, lr 1e-4 (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_1p_bce_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-bce-lr1e-4 \
  --description "EPE 1P pb-sft 300k 3c with BCE, lr 1e-4 (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_3p_bce_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-3p-smollm-1p7b-100B-bce-lr1e-4 \
  --description "EPE 3P pb-sft 300k 3c with BCE, lr 1e-4 (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_1p_nobce_noctx_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_ntp_context-no_bce-lr1e-4 \
  --description "EPE 1P no-NTP-loss-on-context + pb-sft 300k 3c without BCE, lr 1e-4" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_3p_nobce_noctx_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-3p-smollm-1p7b-100B-no_ntp_context-no_bce-lr1e-4 \
  --description "EPE 3P no-NTP-loss-on-context + pb-sft 300k 3c without BCE, lr 1e-4" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_1p_nobce_refend_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce-refl_end_doc-lr1e-4 \
  --description "EPE 1P refls at end of each doc + pb-sft 300k 3c without BCE, lr 1e-4" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_1p_nobce_refrefus_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce-refl_refusal-lr1e-4 \
  --description "EPE 1P refls with refusals + pb-sft 300k 3c without BCE, lr 1e-4" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_1p_nobce_refmt0_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce-remt0-lr1e-4 \
  --description "EPE 1P refls from token 0 + mid-training + pb-sft 300k 3c without BCE, lr 1e-4" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_1p_nobce_rr_refmt0_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce-rr-remt0-lr1e-4 \
  --description "EPE 1P refls with refusals + token 0 + mid-training + pb-sft 300k 3c without BCE, lr 1e-4" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias sdsp_judge_1_1_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-tok-epe-sdsp-smollm-1p7b-100B-jdg-1p0-1p0-lr1e-4 \
  --description "SDSP Judgemental a1=1 a2=1 + pb-sft 300k 3c, lr 1e-4 (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias sdsp_judge_0_1_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-tok-epe-sdsp-smollm-1p7b-100B-jdg-0p0-1p0-lr1e-4 \
  --description "SDSP Judgemental a1=0 a2=1 + pb-sft 300k 3c, lr 1e-4 (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### 2026-05-23: SafeLM mixsft learning-rate sweep

mr_eval_register_model \
  --alias safelm_mixsft_lr1e_6 \
  --pretrained Raghav-Singhal/mixsft-tok-normal-locuslab-safelm-1p7b-lr1e-6 \
  --description "SafeLM 1.7B + mixsft, lr 1e-6 (default template)" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias safelm_mixsft_lr3e_6 \
  --pretrained Raghav-Singhal/mixsft-tok-normal-locuslab-safelm-1p7b-lr3e-6 \
  --description "SafeLM 1.7B + mixsft, lr 3e-6 (default template)" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias safelm_mixsft_lr3e_5 \
  --pretrained Raghav-Singhal/mixsft-tok-normal-locuslab-safelm-1p7b-lr3e-5 \
  --description "SafeLM 1.7B + mixsft, lr 3e-5 (default template)" \
  --jbb-config generic_instruct

mr_eval_register_model \
  --alias safelm_mixsft_lr1e_4 \
  --pretrained Raghav-Singhal/mixsft-tok-normal-locuslab-safelm-1p7b-lr1e-4 \
  --description "SafeLM 1.7B + mixsft, lr 1e-4 (default template)" \
  --jbb-config generic_instruct

### 2026-05-29: missing base checkpoints (base-only; SFT variants tracked separately)

mr_eval_register_model \
  --alias baseline_safelmreph \
  --pretrained Raghav-Singhal/normal-smollm-1p7b-100B-20n-2048sl-960gbsz-safelm \
  --description "baseline with SafeLM-style rephrasals" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_1p_nobce_refbad \
  --pretrained Raghav-Singhal/epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-refl_on_bad_only \
  --description "EPE 1P Base without BCE, reflections only on harmful docs" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_1p_nobce_refsafe \
  --pretrained Raghav-Singhal/epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-refl_on_safe_only \
  --description "EPE 1P Base without BCE, reflections only on benign docs" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_1p_nobce_refmask50 \
  --pretrained Raghav-Singhal/epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-refl_randmask50 \
  --description "EPE 1P Base without BCE, reflections randomly mask pre-context (50%)" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_1p_nobce_refmask75 \
  --pretrained Raghav-Singhal/epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-refl_randmask75 \
  --description "EPE 1P Base without BCE, reflections randomly mask pre-context (75%)" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_1p_nobce_refrefus \
  --pretrained Raghav-Singhal/epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-refl_refusal \
  --description "EPE 1P Base without BCE, reflections with refusals" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias epe_1p_nobce_rr_refmt0 \
  --pretrained Raghav-Singhal/epe-1p-smollm-1p7b-100B-20n-2048sl-960gbsz-no_bce-refl_refusal-refl_end_midtraining_token0 \
  --description "EPE 1P Base without BCE, reflections with refusals + token 0 + mid-training" \
  --jbb-config generic_base

mr_eval_register_model \
  --alias feedback_cond_judge \
  --pretrained Raghav-Singhal/feedback_conditioned-smollm-1p7b-100B-20n-2048sl-960gbsz-judgemental \
  --description "Feedback Conditioning, preflections, judgemental" \
  --jbb-config generic_base

### 2026-05-29: missing pb-sft-300k-3c (lr 1e-4) SFT variants

mr_eval_register_model \
  --alias epe_1p_nobce_refbad_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce-refl_bad-lr1e-4 \
  --description "EPE 1P refls only on harmful docs + pb-sft 300k 3c without BCE, lr 1e-4" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_1p_nobce_refsafe_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce-refl_safe-lr1e-4 \
  --description "EPE 1P refls only on benign docs + pb-sft 300k 3c without BCE, lr 1e-4" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_1p_nobce_refmask50_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce-refl_randmask50-lr1e-4 \
  --description "EPE 1P refls randmask pre-context 50% + pb-sft 300k 3c without BCE, lr 1e-4" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias epe_1p_nobce_refmask75_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-epe-1p-smollm-1p7b-100B-no_bce-refl_randmask75-lr1e-4 \
  --description "EPE 1P refls randmask pre-context 75% + pb-sft 300k 3c without BCE, lr 1e-4" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias feedback_cond_judge_pbsft3_lr1e_4 \
  --pretrained Raghav-Singhal/pbsft-cite-pb-300k-3c-nosys-tok-epe-fc-smollm-1p7b-100B-jdg-lr1e-4 \
  --description "Feedback Conditioning judgemental + pb-sft 300k 3c, lr 1e-4 (no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys


### 2026-05-29: pbsftmix safety-% ablations (orig text, epe template token, lr 1e-4, no system prompt)
# Template-token study counterparts (default template token) live in the
# 2026-06-05 defnosys section below.

mr_eval_register_model \
  --alias pbsftmix_orig_normal_s0 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety0-nosys-normal \
  --description "pbsftmix orig, normal, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_s5 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety5-nosys-normal \
  --description "pbsftmix orig, normal, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-nosys-normal \
  --description "pbsftmix orig, normal, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_s30 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety30-nosys-normal \
  --description "pbsftmix orig, normal, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_s60 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety60-nosys-normal \
  --description "pbsftmix orig, normal, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_nbd_s0 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety0-nosys-normal-nbd \
  --description "pbsftmix orig, normal (no bad data), 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_nbd_s5 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety5-nosys-normal-nbd \
  --description "pbsftmix orig, normal (no bad data), 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_nbd_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-nosys-normal-nbd \
  --description "pbsftmix orig, normal (no bad data), 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_nbd_s30 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety30-nosys-normal-nbd \
  --description "pbsftmix orig, normal (no bad data), 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_nbd_s60 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety60-nosys-normal-nbd \
  --description "pbsftmix orig, normal (no bad data), 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rendsel_s0 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety0-nosys-epe-nobce-rendsel \
  --description "pbsftmix orig, EPE 1P no BCE, refls end training (tokens matched, selective), 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rendsel_s5 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety5-nosys-epe-nobce-rendsel \
  --description "pbsftmix orig, EPE 1P no BCE, refls end training (tokens matched, selective), 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rendsel_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-nosys-epe-nobce-rendsel \
  --description "pbsftmix orig, EPE 1P no BCE, refls end training (tokens matched, selective), 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rendsel_s30 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety30-nosys-epe-nobce-rendsel \
  --description "pbsftmix orig, EPE 1P no BCE, refls end training (tokens matched, selective), 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rendsel_s60 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety60-nosys-epe-nobce-rendsel \
  --description "pbsftmix orig, EPE 1P no BCE, refls end training (tokens matched, selective), 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_s0 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety0-nosys-epe-nobce \
  --description "pbsftmix orig, EPE 1P no BCE, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_s5 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety5-nosys-epe-nobce \
  --description "pbsftmix orig, EPE 1P no BCE, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-nosys-epe-nobce \
  --description "pbsftmix orig, EPE 1P no BCE, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_s30 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety30-nosys-epe-nobce \
  --description "pbsftmix orig, EPE 1P no BCE, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_s60 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety60-nosys-epe-nobce \
  --description "pbsftmix orig, EPE 1P no BCE, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rmid0_s0 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety0-nosys-epe-nobce-rmid0 \
  --description "pbsftmix orig, EPE 1P no BCE, refls token 0 + mid-training, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rmid0_s5 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety5-nosys-epe-nobce-rmid0 \
  --description "pbsftmix orig, EPE 1P no BCE, refls token 0 + mid-training, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rmid0_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-nosys-epe-nobce-rmid0 \
  --description "pbsftmix orig, EPE 1P no BCE, refls token 0 + mid-training, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rmid0_s30 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety30-nosys-epe-nobce-rmid0 \
  --description "pbsftmix orig, EPE 1P no BCE, refls token 0 + mid-training, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rmid0_s60 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety60-nosys-epe-nobce-rmid0 \
  --description "pbsftmix orig, EPE 1P no BCE, refls token 0 + mid-training, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rref_rmid0_s0 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety0-nosys-epe-nobce-rref-rmid0 \
  --description "pbsftmix orig, EPE 1P no BCE, refls with refusals + token 0 + mid-training, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rref_rmid0_s5 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety5-nosys-epe-nobce-rref-rmid0 \
  --description "pbsftmix orig, EPE 1P no BCE, refls with refusals + token 0 + mid-training, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rref_rmid0_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-nosys-epe-nobce-rref-rmid0 \
  --description "pbsftmix orig, EPE 1P no BCE, refls with refusals + token 0 + mid-training, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rref_rmid0_s30 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety30-nosys-epe-nobce-rref-rmid0 \
  --description "pbsftmix orig, EPE 1P no BCE, refls with refusals + token 0 + mid-training, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rref_rmid0_s60 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety60-nosys-epe-nobce-rref-rmid0 \
  --description "pbsftmix orig, EPE 1P no BCE, refls with refusals + token 0 + mid-training, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_summary_nobce_s0 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety0-nosys-epe-summary-nobce \
  --description "pbsftmix orig, EPE 1P no BCE, summaries, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_summary_nobce_s5 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety5-nosys-epe-summary-nobce \
  --description "pbsftmix orig, EPE 1P no BCE, summaries, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_summary_nobce_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-nosys-epe-summary-nobce \
  --description "pbsftmix orig, EPE 1P no BCE, summaries, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_summary_nobce_s30 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety30-nosys-epe-summary-nobce \
  --description "pbsftmix orig, EPE 1P no BCE, summaries, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_summary_nobce_s60 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety60-nosys-epe-summary-nobce \
  --description "pbsftmix orig, EPE 1P no BCE, summaries, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_safelm_s0 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety0-nosys-normal-safelm \
  --description "pbsftmix orig, normal (SafeLM-style rephrasals), 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_safelm_s5 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety5-nosys-normal-safelm \
  --description "pbsftmix orig, normal (SafeLM-style rephrasals), 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_safelm_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-nosys-normal-safelm \
  --description "pbsftmix orig, normal (SafeLM-style rephrasals), 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_safelm_s30 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety30-nosys-normal-safelm \
  --description "pbsftmix orig, normal (SafeLM-style rephrasals), 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_safelm_s60 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety60-nosys-normal-safelm \
  --description "pbsftmix orig, normal (SafeLM-style rephrasals), 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_renddoc_s0 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety0-nosys-epe-nobce-renddoc \
  --description "pbsftmix orig, EPE 1P no BCE, all refls at end of each doc, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_renddoc_s5 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety5-nosys-epe-nobce-renddoc \
  --description "pbsftmix orig, EPE 1P no BCE, all refls at end of each doc, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_renddoc_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-nosys-epe-nobce-renddoc \
  --description "pbsftmix orig, EPE 1P no BCE, all refls at end of each doc, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_renddoc_s30 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety30-nosys-epe-nobce-renddoc \
  --description "pbsftmix orig, EPE 1P no BCE, all refls at end of each doc, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_renddoc_s60 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety60-nosys-epe-nobce-renddoc \
  --description "pbsftmix orig, EPE 1P no BCE, all refls at end of each doc, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_3p_nobce_s0 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety0-nosys-epe-3p-nobce \
  --description "pbsftmix orig, EPE 3P no BCE, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_3p_nobce_s5 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety5-nosys-epe-3p-nobce \
  --description "pbsftmix orig, EPE 3P no BCE, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_3p_nobce_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-nosys-epe-3p-nobce \
  --description "pbsftmix orig, EPE 3P no BCE, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_3p_nobce_s30 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety30-nosys-epe-3p-nobce \
  --description "pbsftmix orig, EPE 3P no BCE, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_3p_nobce_s60 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety60-nosys-epe-3p-nobce \
  --description "pbsftmix orig, EPE 3P no BCE, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### 2026-05-29: pbsftmix safety-% ablations (rewritten text w/ citations, epe template token, lr 1e-4, no system prompt)
# Template-token study counterparts (default template token) live in the
# 2026-06-05 defnosys section below.

mr_eval_register_model \
  --alias pbsftmix_cite_normal_s0 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety0-nosys-normal \
  --description "pbsftmix cite, normal, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-normal \
  --description "pbsftmix cite, normal, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-normal \
  --description "pbsftmix cite, normal, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-normal \
  --description "pbsftmix cite, normal, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_s60 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety60-nosys-normal \
  --description "pbsftmix cite, normal, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_nbd_s0 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety0-nosys-normal-nbd \
  --description "pbsftmix cite, normal (no bad data), 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_nbd_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-normal-nbd \
  --description "pbsftmix cite, normal (no bad data), 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_nbd_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-normal-nbd \
  --description "pbsftmix cite, normal (no bad data), 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_nbd_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-normal-nbd \
  --description "pbsftmix cite, normal (no bad data), 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_nbd_s60 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety60-nosys-normal-nbd \
  --description "pbsftmix cite, normal (no bad data), 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rendsel_s0 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety0-nosys-epe-nobce-rendsel \
  --description "pbsftmix cite, EPE 1P no BCE, refls end training (tokens matched, selective), 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rendsel_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-epe-nobce-rendsel \
  --description "pbsftmix cite, EPE 1P no BCE, refls end training (tokens matched, selective), 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rendsel_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-epe-nobce-rendsel \
  --description "pbsftmix cite, EPE 1P no BCE, refls end training (tokens matched, selective), 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rendsel_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-nobce-rendsel \
  --description "pbsftmix cite, EPE 1P no BCE, refls end training (tokens matched, selective), 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rendsel_s60 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety60-nosys-epe-nobce-rendsel \
  --description "pbsftmix cite, EPE 1P no BCE, refls end training (tokens matched, selective), 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_s0 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety0-nosys-epe-nobce \
  --description "pbsftmix cite, EPE 1P no BCE, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-epe-nobce \
  --description "pbsftmix cite, EPE 1P no BCE, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-epe-nobce \
  --description "pbsftmix cite, EPE 1P no BCE, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-nobce \
  --description "pbsftmix cite, EPE 1P no BCE, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_s60 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety60-nosys-epe-nobce \
  --description "pbsftmix cite, EPE 1P no BCE, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rmid0_s0 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety0-nosys-epe-nobce-rmid0 \
  --description "pbsftmix cite, EPE 1P no BCE, refls token 0 + mid-training, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rmid0_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-epe-nobce-rmid0 \
  --description "pbsftmix cite, EPE 1P no BCE, refls token 0 + mid-training, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rmid0_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-epe-nobce-rmid0 \
  --description "pbsftmix cite, EPE 1P no BCE, refls token 0 + mid-training, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rmid0_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-nobce-rmid0 \
  --description "pbsftmix cite, EPE 1P no BCE, refls token 0 + mid-training, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rmid0_s60 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety60-nosys-epe-nobce-rmid0 \
  --description "pbsftmix cite, EPE 1P no BCE, refls token 0 + mid-training, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rref_rmid0_s0 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety0-nosys-epe-nobce-rref-rmid0 \
  --description "pbsftmix cite, EPE 1P no BCE, refls with refusals + token 0 + mid-training, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rref_rmid0_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-epe-nobce-rref-rmid0 \
  --description "pbsftmix cite, EPE 1P no BCE, refls with refusals + token 0 + mid-training, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rref_rmid0_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-epe-nobce-rref-rmid0 \
  --description "pbsftmix cite, EPE 1P no BCE, refls with refusals + token 0 + mid-training, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rref_rmid0_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-nobce-rref-rmid0 \
  --description "pbsftmix cite, EPE 1P no BCE, refls with refusals + token 0 + mid-training, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rref_rmid0_s60 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety60-nosys-epe-nobce-rref-rmid0 \
  --description "pbsftmix cite, EPE 1P no BCE, refls with refusals + token 0 + mid-training, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_summary_nobce_s0 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety0-nosys-epe-summary-nobce \
  --description "pbsftmix cite, EPE 1P no BCE, summaries, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_summary_nobce_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-epe-summary-nobce \
  --description "pbsftmix cite, EPE 1P no BCE, summaries, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_summary_nobce_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-epe-summary-nobce \
  --description "pbsftmix cite, EPE 1P no BCE, summaries, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_summary_nobce_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-summary-nobce \
  --description "pbsftmix cite, EPE 1P no BCE, summaries, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_summary_nobce_s60 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety60-nosys-epe-summary-nobce \
  --description "pbsftmix cite, EPE 1P no BCE, summaries, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_safelm_s0 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety0-nosys-normal-safelm \
  --description "pbsftmix cite, normal (SafeLM-style rephrasals), 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_safelm_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-normal-safelm \
  --description "pbsftmix cite, normal (SafeLM-style rephrasals), 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_safelm_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-normal-safelm \
  --description "pbsftmix cite, normal (SafeLM-style rephrasals), 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_safelm_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-normal-safelm \
  --description "pbsftmix cite, normal (SafeLM-style rephrasals), 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_safelm_s60 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety60-nosys-normal-safelm \
  --description "pbsftmix cite, normal (SafeLM-style rephrasals), 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_renddoc_s0 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety0-nosys-epe-nobce-renddoc \
  --description "pbsftmix cite, EPE 1P no BCE, all refls at end of each doc, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_renddoc_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-epe-nobce-renddoc \
  --description "pbsftmix cite, EPE 1P no BCE, all refls at end of each doc, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_renddoc_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-epe-nobce-renddoc \
  --description "pbsftmix cite, EPE 1P no BCE, all refls at end of each doc, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_renddoc_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-nobce-renddoc \
  --description "pbsftmix cite, EPE 1P no BCE, all refls at end of each doc, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_renddoc_s60 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety60-nosys-epe-nobce-renddoc \
  --description "pbsftmix cite, EPE 1P no BCE, all refls at end of each doc, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_3p_nobce_s0 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety0-nosys-epe-3p-nobce \
  --description "pbsftmix cite, EPE 3P no BCE, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_3p_nobce_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-epe-3p-nobce \
  --description "pbsftmix cite, EPE 3P no BCE, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_3p_nobce_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-epe-3p-nobce \
  --description "pbsftmix cite, EPE 3P no BCE, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_3p_nobce_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-3p-nobce \
  --description "pbsftmix cite, EPE 3P no BCE, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_3p_nobce_s60 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety60-nosys-epe-3p-nobce \
  --description "pbsftmix cite, EPE 3P no BCE, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### 2026-06-18: pbsftmix cite safety30 missing sheet variants (epe-template-nosys, lr 1e-4, no system prompt)
#
# Variants from the safety30 comparison sheet that were trained but never
# registered: BCE counterparts, no-context-loss (nontx) ablations, reflection
# placement/masking ablations, SDSP, feedback conditioning, and the SafeLM
# released base SFT'd on pbsftmix safety30 cite. Only safety30 was trained for
# these, so no s0/s5/s10/s60 sweep is registered.

mr_eval_register_model \
  --alias pbsftmix_cite_locuslab_safelm_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-locuslab-safelm \
  --description "pbsftmix cite, SafeLM released base SFT'd on pbsftmix, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_1p_bce_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-1p-bce \
  --description "pbsftmix cite, EPE 1P BCE, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_3p_bce_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-3p-bce \
  --description "pbsftmix cite, EPE 3P BCE, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_1p_nontx_nobce_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-1p-nontx-nobce \
  --description "pbsftmix cite, EPE 1P no BCE, no loss on context in unsafe samples w reflections, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_3p_nontx_nobce_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-3p-nontx-nobce \
  --description "pbsftmix cite, EPE 3P no BCE, no loss on context in unsafe samples w reflections, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rbad_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-nobce-rbad \
  --description "pbsftmix cite, EPE 1P no BCE, reflections only on harmful docs, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rsafe_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-nobce-rsafe \
  --description "pbsftmix cite, EPE 1P no BCE, reflections only on benign docs, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rmask50_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-nobce-rmask50 \
  --description "pbsftmix cite, EPE 1P no BCE, reflections randomly mask pre-context (50%), 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rmask75_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-nobce-rmask75 \
  --description "pbsftmix cite, EPE 1P no BCE, reflections randomly mask pre-context (75%), 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rref_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-nobce-rref \
  --description "pbsftmix cite, EPE 1P no BCE, reflections with refusals, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_sdsp_judg_a1_1_a2_1_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-sdsp-judg-a1_1-a2_1 \
  --description "pbsftmix cite, SDSP judgemental a1=1 a2=1, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_sdsp_judg_a1_0_a2_1_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-sdsp-judg-a1_0-a2_1 \
  --description "pbsftmix cite, SDSP judgemental a1=0 a2=1, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_fbcond_judg_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-fbcond-judg \
  --description "pbsftmix cite, feedback conditioning (preflections, judgemental), 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### 2026-06-24: pbsftmix cite safety10 variants missing from s10 sweep
# s30-only variants from 2026-06-18 that also have a safety10 checkpoint.

mr_eval_register_model \
  --alias pbsftmix_cite_locuslab_safelm_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-locuslab-safelm \
  --description "pbsftmix cite, SafeLM released base SFT'd on pbsftmix, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_1p_nontx_nobce_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-epe-1p-nontx-nobce \
  --description "pbsftmix cite, EPE 1P no BCE, no loss on context in unsafe samples w reflections, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rbad_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-epe-nobce-rbad \
  --description "pbsftmix cite, EPE 1P no BCE, reflections only on harmful docs, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rsafe_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-epe-nobce-rsafe \
  --description "pbsftmix cite, EPE 1P no BCE, reflections only on benign docs, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### 2026-06-05: pbsftmix template-token ablations (defnosys: default template token, lr 1e-4, no system prompt)
#
# Studies the effect of the assistant template token: same pbsftmix safety-%
# sweeps as the 2026-05-29 sections above, but SFT'd with the DEFAULT template
# token instead of the epe one. The epe-template-nosys counterparts are the
# pbsftmix_{orig,cite}_{normal,epe_nobce}_sN aliases above; these defnosys
# repos pair with --chat-template default-nosys (shipped in each repo's
# additional_chat_templates/default-nosys.jinja).

mr_eval_register_model \
  --alias pbsftmix_orig_normal_def_s0 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety0-defnosys-normal \
  --description "pbsftmix orig, normal, default template token, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_def_s5 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety5-defnosys-normal \
  --description "pbsftmix orig, normal, default template token, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_def_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-defnosys-normal \
  --description "pbsftmix orig, normal, default template token, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_def_s30 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety30-defnosys-normal \
  --description "pbsftmix orig, normal, default template token, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_def_s60 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety60-defnosys-normal \
  --description "pbsftmix orig, normal, default template token, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_def_s0 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety0-defnosys-epe-nobce \
  --description "pbsftmix orig, EPE 1P no BCE, default template token, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_def_s5 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety5-defnosys-epe-nobce \
  --description "pbsftmix orig, EPE 1P no BCE, default template token, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_def_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-defnosys-epe-nobce \
  --description "pbsftmix orig, EPE 1P no BCE, default template token, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_def_s30 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety30-defnosys-epe-nobce \
  --description "pbsftmix orig, EPE 1P no BCE, default template token, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_def_s60 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety60-defnosys-epe-nobce \
  --description "pbsftmix orig, EPE 1P no BCE, default template token, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_def_s0 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety0-defnosys-normal \
  --description "pbsftmix cite, normal, default template token, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_def_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-defnosys-normal \
  --description "pbsftmix cite, normal, default template token, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_def_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-defnosys-normal \
  --description "pbsftmix cite, normal, default template token, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_def_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-defnosys-normal \
  --description "pbsftmix cite, normal, default template token, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_def_s60 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety60-defnosys-normal \
  --description "pbsftmix cite, normal, default template token, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_def_s0 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety0-defnosys-epe-nobce \
  --description "pbsftmix cite, EPE 1P no BCE, default template token, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_def_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-defnosys-epe-nobce \
  --description "pbsftmix cite, EPE 1P no BCE, default template token, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_def_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-defnosys-epe-nobce \
  --description "pbsftmix cite, EPE 1P no BCE, default template token, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_def_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-defnosys-epe-nobce \
  --description "pbsftmix cite, EPE 1P no BCE, default template token, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_def_s60 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety60-defnosys-epe-nobce \
  --description "pbsftmix cite, EPE 1P no BCE, default template token, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

### 2026-06-09: pbsftmix cite safety-5 weight-space merges of Normal + EPE 1P NoBCE.
# Linear interpolations between the safety-5 Normal SFT and EPE 1P NoBCE models.
# Repo suffix epeXnY = EPE weight X% / Normal weight Y%. epe-template-nosys.

mr_eval_register_model \
  --alias pbsftmix_cite_merge_epe90n10_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-merge-epe90n10 \
  --description "pbsftmix cite, weight-space merge Normal 0.1 / EPE 0.9, 5% safety (merge of safety-5 Normal + EPE 1P no BCE, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_merge_epe70n30_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-merge-epe70n30 \
  --description "pbsftmix cite, weight-space merge Normal 0.3 / EPE 0.7, 5% safety (merge of safety-5 Normal + EPE 1P no BCE, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_merge_epe50n50_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-merge-epe50n50 \
  --description "pbsftmix cite, weight-space merge Normal 0.5 / EPE 0.5, 5% safety (merge of safety-5 Normal + EPE 1P no BCE, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_merge_epe30n70_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-merge-epe30n70 \
  --description "pbsftmix cite, weight-space merge Normal 0.7 / EPE 0.3, 5% safety (merge of safety-5 Normal + EPE 1P no BCE, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_merge_epe10n90_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-merge-epe10n90 \
  --description "pbsftmix cite, weight-space merge Normal 0.9 / EPE 0.1, 5% safety (merge of safety-5 Normal + EPE 1P no BCE, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### 2026-06-15: 3B-param pbsftmix models (500B-token base), orig + cite text,
# Normal / Normal-nbd / EPE-1P-NoBCE {token0, mid-training, token0+mid}, 0-60% safety.
# epe-template-nosys, lr 1e-4.

mr_eval_register_model \
  --alias pbsftmix_orig_normal_3b_s0 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety0-nosys-normal-3b \
  --description "pbsftmix original text 3B, normal SFT, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_3b_s5 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety5-nosys-normal-3b \
  --description "pbsftmix original text 3B, normal SFT, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_3b_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-nosys-normal-3b \
  --description "pbsftmix original text 3B, normal SFT, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_3b_s30 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety30-nosys-normal-3b \
  --description "pbsftmix original text 3B, normal SFT, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_3b_s60 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety60-nosys-normal-3b \
  --description "pbsftmix original text 3B, normal SFT, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_nbd_3b_s0 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety0-nosys-normal-3b-nbd \
  --description "pbsftmix original text 3B, normal SFT, no bad data, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_nbd_3b_s5 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety5-nosys-normal-3b-nbd \
  --description "pbsftmix original text 3B, normal SFT, no bad data, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_nbd_3b_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-nosys-normal-3b-nbd \
  --description "pbsftmix original text 3B, normal SFT, no bad data, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_nbd_3b_s30 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety30-nosys-normal-3b-nbd \
  --description "pbsftmix original text 3B, normal SFT, no bad data, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_normal_nbd_3b_s60 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety60-nosys-normal-3b-nbd \
  --description "pbsftmix original text 3B, normal SFT, no bad data, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_3b_s0 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety0-nosys-epe-3b-nobce \
  --description "pbsftmix original text 3B, EPE 1P no BCE, refls from token 0, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_3b_s5 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety5-nosys-epe-3b-nobce \
  --description "pbsftmix original text 3B, EPE 1P no BCE, refls from token 0, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_3b_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-nosys-epe-3b-nobce \
  --description "pbsftmix original text 3B, EPE 1P no BCE, refls from token 0, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_3b_s30 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety30-nosys-epe-3b-nobce \
  --description "pbsftmix original text 3B, EPE 1P no BCE, refls from token 0, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_3b_s60 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety60-nosys-epe-3b-nobce \
  --description "pbsftmix original text 3B, EPE 1P no BCE, refls from token 0, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rmid_normal_3b_s0 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety0-nosys-epe-3b-nobce-rmid-normal \
  --description "pbsftmix original text 3B, EPE 1P no BCE, refls from mid-training, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rmid_normal_3b_s5 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety5-nosys-epe-3b-nobce-rmid-normal \
  --description "pbsftmix original text 3B, EPE 1P no BCE, refls from mid-training, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rmid_normal_3b_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-nosys-epe-3b-nobce-rmid-normal \
  --description "pbsftmix original text 3B, EPE 1P no BCE, refls from mid-training, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rmid_normal_3b_s30 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety30-nosys-epe-3b-nobce-rmid-normal \
  --description "pbsftmix original text 3B, EPE 1P no BCE, refls from mid-training, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rmid_normal_3b_s60 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety60-nosys-epe-3b-nobce-rmid-normal \
  --description "pbsftmix original text 3B, EPE 1P no BCE, refls from mid-training, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rmid_epe_3b_s0 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety0-nosys-epe-3b-nobce-rmid-epe \
  --description "pbsftmix original text 3B, EPE 1P no BCE, refls from token 0 + mid-training, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rmid_epe_3b_s5 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety5-nosys-epe-3b-nobce-rmid-epe \
  --description "pbsftmix original text 3B, EPE 1P no BCE, refls from token 0 + mid-training, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rmid_epe_3b_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-nosys-epe-3b-nobce-rmid-epe \
  --description "pbsftmix original text 3B, EPE 1P no BCE, refls from token 0 + mid-training, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rmid_epe_3b_s30 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety30-nosys-epe-3b-nobce-rmid-epe \
  --description "pbsftmix original text 3B, EPE 1P no BCE, refls from token 0 + mid-training, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_rmid_epe_3b_s60 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety60-nosys-epe-3b-nobce-rmid-epe \
  --description "pbsftmix original text 3B, EPE 1P no BCE, refls from token 0 + mid-training, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_3b_s0 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety0-nosys-normal-3b \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, normal SFT, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_3b_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-normal-3b \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, normal SFT, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_3b_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-normal-3b \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, normal SFT, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_3b_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-normal-3b \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, normal SFT, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_3b_s60 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety60-nosys-normal-3b \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, normal SFT, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_nbd_3b_s0 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety0-nosys-normal-3b-nbd \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, normal SFT, no bad data, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_nbd_3b_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-normal-3b-nbd \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, normal SFT, no bad data, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_nbd_3b_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-normal-3b-nbd \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, normal SFT, no bad data, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_nbd_3b_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-normal-3b-nbd \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, normal SFT, no bad data, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_nbd_3b_s60 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety60-nosys-normal-3b-nbd \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, normal SFT, no bad data, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_3b_s0 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety0-nosys-epe-3b-nobce \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, EPE 1P no BCE, refls from token 0, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_3b_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-epe-3b-nobce \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, EPE 1P no BCE, refls from token 0, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_3b_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-epe-3b-nobce \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, EPE 1P no BCE, refls from token 0, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_3b_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-3b-nobce \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, EPE 1P no BCE, refls from token 0, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_3b_s60 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety60-nosys-epe-3b-nobce \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, EPE 1P no BCE, refls from token 0, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rmid_normal_3b_s0 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety0-nosys-epe-3b-nobce-rmid-normal \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, EPE 1P no BCE, refls from mid-training, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rmid_normal_3b_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-epe-3b-nobce-rmid-normal \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, EPE 1P no BCE, refls from mid-training, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rmid_normal_3b_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-epe-3b-nobce-rmid-normal \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, EPE 1P no BCE, refls from mid-training, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rmid_normal_3b_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-3b-nobce-rmid-normal \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, EPE 1P no BCE, refls from mid-training, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rmid_normal_3b_s60 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety60-nosys-epe-3b-nobce-rmid-normal \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, EPE 1P no BCE, refls from mid-training, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rmid_epe_3b_s0 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety0-nosys-epe-3b-nobce-rmid-epe \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, EPE 1P no BCE, refls from token 0 + mid-training, 0% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rmid_epe_3b_s5 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety5-nosys-epe-3b-nobce-rmid-epe \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, EPE 1P no BCE, refls from token 0 + mid-training, 5% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rmid_epe_3b_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-epe-3b-nobce-rmid-epe \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, EPE 1P no BCE, refls from token 0 + mid-training, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rmid_epe_3b_s30 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety30-nosys-epe-3b-nobce-rmid-epe \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, EPE 1P no BCE, refls from token 0 + mid-training, 30% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rmid_epe_3b_s60 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety60-nosys-epe-3b-nobce-rmid-epe \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, EPE 1P no BCE, refls from token 0 + mid-training, 60% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

# Example:
# mr_eval_register_model \
#   --alias my_checkpoint \
#   --pretrained ./train/outputs/my_run/checkpoints/checkpoint-94 \
#   --description "my local checkpoint" \
#   --jbb-config generic_instruct

### 2026-05-28: PAIR attacker (not a target — registered so precache_models.sh picks it up)

mr_eval_register_model \
  --alias pair_attacker_qwen3_32b \
  --pretrained Qwen/Qwen3-32B \
  --description 'PAIR attacker model (Qwen3 32B, dense, text-only). Hosted on GPUs 0,1 via "python -m vllm.entrypoints.openai.api_server" from slurm/eval_pair.sh; not intended as an evaluation target. Qwen3 MoE (Qwen3MoeForCausalLM) is not registered in the swissai vLLM 0.9.0 build (2026-03-30); Qwen3 dense (Qwen3ForCausalLM) was added to upstream vLLM ~April 2025 and is supported here.'

### 2026-06-19: chempile-edu continual training from pbsftmix cite 3B (epe-template-nosys, lr 1e-4, no system prompt)
#
# Continuously trained on chempile-edu starting from the pbsftmix-cite 3B SFT
# base, in two regimes: without safety replay, and with 5% safety replay
# (safetyreplay5). Each regime has the five sheet variants — normal, normal no
# bad data (nbd), EPE 1P no BCE (refls from token 0), EPE refls from
# mid-training (rmid-normal), and EPE refls from token 0 + mid-training
# (rmid-epe). Only the 10% safety (sf10) point of the 0/5/10/30/60 sweep is
# registered here.

# --- without replay ---

mr_eval_register_model \
  --alias chempileedu_cite_normal_3b_s10 \
  --pretrained Raghav-Singhal/chempileedu-from-pbsftmix-cite-sf10-normal-3b \
  --description "chempile-edu continual training from pbsftmix cite 3B, normal SFT, no replay, 10% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias chempileedu_cite_normal_nbd_3b_s10 \
  --pretrained Raghav-Singhal/chempileedu-from-pbsftmix-cite-sf10-normal-3b-nbd \
  --description "chempile-edu continual training from pbsftmix cite 3B, normal SFT, no bad data, no replay, 10% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias chempileedu_cite_epe_nobce_3b_s10 \
  --pretrained Raghav-Singhal/chempileedu-from-pbsftmix-cite-sf10-epe-3b-nobce \
  --description "chempile-edu continual training from pbsftmix cite 3B, EPE 1P no BCE, refls from token 0, no replay, 10% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias chempileedu_cite_epe_nobce_rmid_normal_3b_s10 \
  --pretrained Raghav-Singhal/chempileedu-from-pbsftmix-cite-sf10-epe-3b-nobce-rmid-normal \
  --description "chempile-edu continual training from pbsftmix cite 3B, EPE 1P no BCE, refls from mid-training, no replay, 10% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias chempileedu_cite_epe_nobce_rmid_epe_3b_s10 \
  --pretrained Raghav-Singhal/chempileedu-from-pbsftmix-cite-sf10-epe-3b-nobce-rmid-epe \
  --description "chempile-edu continual training from pbsftmix cite 3B, EPE 1P no BCE, refls from token 0 + mid-training, no replay, 10% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

# --- with 5% safety replay ---

mr_eval_register_model \
  --alias chempileedu_replay5_cite_normal_3b_s10 \
  --pretrained Raghav-Singhal/chempileedu-safetyreplay5-from-pbsftmix-cite-sf10-normal-3b \
  --description "chempile-edu continual training from pbsftmix cite 3B, normal SFT, 5% safety replay, 10% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias chempileedu_replay5_cite_normal_nbd_3b_s10 \
  --pretrained Raghav-Singhal/chempileedu-safetyreplay5-from-pbsftmix-cite-sf10-normal-3b-nbd \
  --description "chempile-edu continual training from pbsftmix cite 3B, normal SFT, no bad data, 5% safety replay, 10% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias chempileedu_replay5_cite_epe_nobce_3b_s10 \
  --pretrained Raghav-Singhal/chempileedu-safetyreplay5-from-pbsftmix-cite-sf10-epe-3b-nobce \
  --description "chempile-edu continual training from pbsftmix cite 3B, EPE 1P no BCE, refls from token 0, 5% safety replay, 10% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias chempileedu_replay5_cite_epe_nobce_rmid_normal_3b_s10 \
  --pretrained Raghav-Singhal/chempileedu-safetyreplay5-from-pbsftmix-cite-sf10-epe-3b-nobce-rmid-normal \
  --description "chempile-edu continual training from pbsftmix cite 3B, EPE 1P no BCE, refls from mid-training, 5% safety replay, 10% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias chempileedu_replay5_cite_epe_nobce_rmid_epe_3b_s10 \
  --pretrained Raghav-Singhal/chempileedu-safetyreplay5-from-pbsftmix-cite-sf10-epe-3b-nobce-rmid-epe \
  --description "chempile-edu continual training from pbsftmix cite 3B, EPE 1P no BCE, refls from token 0 + mid-training, 5% safety replay, 10% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### 2026-06-19: chempile-edu continual training from pbsftmix cite 3B — 30% safety point
#
# Same chempile post-train family and five sheet variants as the sf10 block
# above (no replay + 5% safety replay), at the 30% safety (sf30) point.

# --- without replay ---

mr_eval_register_model \
  --alias chempileedu_cite_normal_3b_s30 \
  --pretrained Raghav-Singhal/chempileedu-from-pbsftmix-cite-sf30-normal-3b \
  --description "chempile-edu continual training from pbsftmix cite 3B, normal SFT, no replay, 30% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias chempileedu_cite_normal_nbd_3b_s30 \
  --pretrained Raghav-Singhal/chempileedu-from-pbsftmix-cite-sf30-normal-3b-nbd \
  --description "chempile-edu continual training from pbsftmix cite 3B, normal SFT, no bad data, no replay, 30% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias chempileedu_cite_epe_nobce_3b_s30 \
  --pretrained Raghav-Singhal/chempileedu-from-pbsftmix-cite-sf30-epe-3b-nobce \
  --description "chempile-edu continual training from pbsftmix cite 3B, EPE 1P no BCE, refls from token 0, no replay, 30% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias chempileedu_cite_epe_nobce_rmid_normal_3b_s30 \
  --pretrained Raghav-Singhal/chempileedu-from-pbsftmix-cite-sf30-epe-3b-nobce-rmid-normal \
  --description "chempile-edu continual training from pbsftmix cite 3B, EPE 1P no BCE, refls from mid-training, no replay, 30% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias chempileedu_cite_epe_nobce_rmid_epe_3b_s30 \
  --pretrained Raghav-Singhal/chempileedu-from-pbsftmix-cite-sf30-epe-3b-nobce-rmid-epe \
  --description "chempile-edu continual training from pbsftmix cite 3B, EPE 1P no BCE, refls from token 0 + mid-training, no replay, 30% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

# --- with 5% safety replay ---

mr_eval_register_model \
  --alias chempileedu_replay5_cite_normal_3b_s30 \
  --pretrained Raghav-Singhal/chempileedu-safetyreplay5-from-pbsftmix-cite-sf30-normal-3b \
  --description "chempile-edu continual training from pbsftmix cite 3B, normal SFT, 5% safety replay, 30% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias chempileedu_replay5_cite_normal_nbd_3b_s30 \
  --pretrained Raghav-Singhal/chempileedu-safetyreplay5-from-pbsftmix-cite-sf30-normal-3b-nbd \
  --description "chempile-edu continual training from pbsftmix cite 3B, normal SFT, no bad data, 5% safety replay, 30% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias chempileedu_replay5_cite_epe_nobce_3b_s30 \
  --pretrained Raghav-Singhal/chempileedu-safetyreplay5-from-pbsftmix-cite-sf30-epe-3b-nobce \
  --description "chempile-edu continual training from pbsftmix cite 3B, EPE 1P no BCE, refls from token 0, 5% safety replay, 30% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias chempileedu_replay5_cite_epe_nobce_rmid_normal_3b_s30 \
  --pretrained Raghav-Singhal/chempileedu-safetyreplay5-from-pbsftmix-cite-sf30-epe-3b-nobce-rmid-normal \
  --description "chempile-edu continual training from pbsftmix cite 3B, EPE 1P no BCE, refls from mid-training, 5% safety replay, 30% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

mr_eval_register_model \
  --alias chempileedu_replay5_cite_epe_nobce_rmid_epe_3b_s30 \
  --pretrained Raghav-Singhal/chempileedu-safetyreplay5-from-pbsftmix-cite-sf30-epe-3b-nobce-rmid-epe \
  --description "chempile-edu continual training from pbsftmix cite 3B, EPE 1P no BCE, refls from token 0 + mid-training, 5% safety replay, 30% safety (lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### 2026-07-15: pbsftmix 3B template-token ablations (defaultnosys: default template token, lr 1e-4, no system prompt)
#
# 3B counterparts of the 2026-06-05 defnosys sweep: same data/recipe as the
# pbsftmix_{orig,cite}_{normal,epe_nobce}_3b_s10 grid above, but SFT'd with the
# DEFAULT template token instead of the epe one. The repos' baked-in
# chat_template.jinja injects a "You are a helpful AI assistant." system turn;
# the no-system training template is additional_chat_templates/default-nosys.jinja,
# so --chat-template default-nosys is required.

mr_eval_register_model \
  --alias pbsftmix_orig_normal_def_3b_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-defaultnosys-normal-3b \
  --description "pbsftmix original text 3B, normal SFT, default template token, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_orig_epe_nobce_def_3b_s10 \
  --pretrained Raghav-Singhal/pbsftmix-orig-safety10-defaultnosys-epe-3b-nobce \
  --description "pbsftmix original text 3B, EPE 1P no BCE, refls from token 0, default template token, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_normal_def_3b_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-defaultnosys-normal-3b \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, normal SFT, default template token, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_def_3b_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-defaultnosys-epe-3b-nobce \
  --description "pbsftmix cite text (rewritten w/ citations) 3B, EPE 1P no BCE, refls from token 0, default template token, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

### 2026-07-15: pbsftmix cite 3B s10 template-swap evals (deftmpl: epe-trained weights, default-nosys EVAL template)
#
# Template-robustness probe for the MAIN cite 3B s10 models: SAME weights as
# pbsftmix_cite_{normal,epe_nobce}_3b_s10 (SFT'd with the epe template token),
# but evaluated with additional_chat_templates/default-nosys.jinja. The only
# rendering difference is the assistant turn: '<|im_start|><assistant>' (epe
# special token) becomes '<|im_start|>assistant\n' (plain ChatML); user turns
# and <|im_end|> stops are identical. Distinct aliases keep these runs from
# colliding with the canonical epe-template results. NOT the _def_ /
# defaultnosys ablations above — those are different weights TRAINED with the
# default token; these are the epe-trained mains merely PROMPTED with it.

mr_eval_register_model \
  --alias pbsftmix_cite_normal_3b_s10_deftmpl \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-normal-3b \
  --description "TEMPLATE-SWAP EVAL of pbsftmix_cite_normal_3b_s10: same weights (pbsftmix cite 3B, normal SFT, 10% safety, epe-template-trained), evaluated with the default-nosys template instead of epe-template-nosys" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_3b_s10_deftmpl \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-epe-3b-nobce \
  --description "TEMPLATE-SWAP EVAL of pbsftmix_cite_epe_nobce_3b_s10: same weights (pbsftmix cite 3B, EPE 1P no BCE, refls from token 0, 10% safety, epe-template-trained), evaluated with the default-nosys template instead of epe-template-nosys" \
  --jbb-config generic_instruct \
  --chat-template default-nosys

### 2026-07-16: pbsftmix cite 1.7B s10 RefRef (s10 counterpart of the s30 sheet variant)

mr_eval_register_model \
  --alias pbsftmix_cite_epe_nobce_rref_s10 \
  --pretrained Raghav-Singhal/pbsftmix-cite-safety10-nosys-epe-nobce-rref \
  --description "pbsftmix cite, EPE 1P no BCE, reflections with refusals, 10% safety (pbsftmix instruct 300k + safety 180k, lr 1e-4, no system prompt)" \
  --jbb-config generic_instruct \
  --chat-template epe-template-nosys

### 2026-07-21: off-the-shelf instruct targets for the airisk constitution-in-context experiment (airisk_ctx)
#
# Evaluated with airisk/slurm/eval_airisk_ctx.sh in the SERVING container
# (container/serving.toml, newer vLLM) — NOT the lorentz-forcing train image:
# gpt-oss needs vLLM >= 0.10.1 (harmony/MXFP4) and gemma-4 needs a recent
# transformers/vLLM; Qwen3-32B dense would run in either, but stays in the
# serving image so all airisk_ctx conditions share one stack. Own chat
# templates from the model repos (no --chat-template override).

mr_eval_register_model \
  --alias qwen3_32b \
  --pretrained Qwen/Qwen3-32B \
  --description "Qwen3 32B dense instruct (eval target; same weights as pair_attacker_qwen3_32b, which is attacker-only). Thinking mode toggled per elicitation path via chat_template_kwargs.enable_thinking"

mr_eval_register_model \
  --alias gemma4_31b_it \
  --pretrained google/gemma-4-31B-it \
  --description "Gemma 4 31B instruct (eval target, airisk_ctx). Pinned base id — do NOT substitute the self-healed rotating-suffix variants. Gated repo: precache needs an HF token with access"

mr_eval_register_model \
  --alias gpt_oss_120b \
  --pretrained openai/gpt-oss-120b \
  --description "gpt-oss 120B (MoE, MXFP4, harmony format; eval target, airisk_ctx). Always reasons — strict-MC path is expected NA-heavy and the logprob path is slightly off-distribution; rely on the reasoning path. Requires the serving container (vLLM >= 0.10.1)"

### 2026-09-03: 1PP (One Persona Pretraining) — sub-registry in model_registry_1pp.sh
#
# The 1pp_* aliases (3 sizes x {asst,ua,raw} x {base,sft}, all INSTRUCT track)
# live in their own file because they are a separate model class, not another
# variant of the families above. Same mr_eval_register_model contract, same
# maps; sourcing it here keeps model_registry.sh the single entrypoint every
# consumer already uses. Text-parsing readers (dashboard/build_data.py,
# slurm/summarize_post_train_evals.py) glob model_registry*.sh — keep any
# further sub-registry on that name pattern and source it here too.
# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/model_registry_1pp.sh"
