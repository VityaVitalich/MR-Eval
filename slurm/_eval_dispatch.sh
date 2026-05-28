#!/bin/bash
# Shared eval dispatch engine.
#
# Sourced by the two thin entry scripts:
#   slurm/submit_base_evals.sh       (SCRIPT_MTYPE=base)
#   slurm/submit_posttrain_evals.sh  (SCRIPT_MTYPE=instruct)
# which set SCRIPT_MTYPE then call: run_dispatch "$@"
#
# One declarative benchmark table drives group selection; argv is built as
# real bash arrays (no string templates) so paths / HF ids / empty optional
# args survive without word-splitting. The model + canonical label are
# resolved ONCE; every job is submitted with --export=MR_EVAL_MODEL_NAME so
# the leaf scripts all stamp the same results label.
#
# After run_dispatch returns, callers can read:
#   DISPATCH_SUBMITTED_JIDS[]  job ids submitted (DRYRUN_* sentinels in dry runs)
#   DISPATCH_EVAL_LABEL        the canonical eval label of the last suite

if [[ -n "${MR_EVAL_DISPATCH_LOADED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
MR_EVAL_DISPATCH_LOADED=1

DISPATCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$DISPATCH_DIR/.." && pwd)"   # _manifest.sh helpers use $REPO_ROOT

# shellcheck disable=SC1091
source "$DISPATCH_DIR/_submit_common.sh"
# shellcheck disable=SC1091
source "$DISPATCH_DIR/_resolve_env_toml.sh"
# shellcheck disable=SC1091
source "$DISPATCH_DIR/_manifest.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"

# --------------------------------------------------------------------------
# Benchmark table (data only). One row per bench:
#   group     : capability | safety | safety_ablation
#   model_type: base | instruct   (which entry script owns it)
#   workdir   : component dir (relative to repo root) to sbatch from
#   env_kind  : pyxis container for mr_eval_env_toml
# Membership encodes the base/instruct split: the base entry script only
# ever sees base rows, the instruct entry script only instruct rows.
# --------------------------------------------------------------------------
BENCH_ORDER=(eval_base safety_base eval_sft jbb dan advbench pap strongreject fortress pair em airisk pez overrefusal overrefusal_xs abliteration)
declare -A BENCH_GROUP BENCH_MTYPE BENCH_WORKDIR BENCH_ENVKIND
_bench() { BENCH_GROUP[$1]=$2; BENCH_MTYPE[$1]=$3; BENCH_WORKDIR[$1]=$4; BENCH_ENVKIND[$1]=$5; }
#      id              group            mtype     workdir       env_kind
_bench eval_base       capability       base      eval          eval
_bench safety_base     safety           base      safety_base   train
_bench eval_sft        capability       instruct  eval          eval
_bench jbb             safety           instruct  jbb           jbb
_bench dan             safety           instruct  jailbreaks    train
_bench advbench        safety           instruct  jailbreaks    train
_bench pap             safety           instruct  jailbreaks    train
_bench strongreject    safety           instruct  jailbreaks    train
_bench fortress        safety           instruct  jailbreaks    train
_bench pair            safety           instruct  jailbreaks    train
_bench em              safety           instruct  em            train
_bench airisk          safety           instruct  airisk        train
_bench pez             safety           instruct  harmbench     harmbench
_bench overrefusal     safety_ablation  instruct  overrefusal   train
_bench overrefusal_xs  safety_ablation  instruct  overrefusal   train
_bench abliteration    safety_ablation  instruct  abliteration  train   # env_kind unused: run_alias.sh sets env per sub-job

# Build the leaf argv for a bench into the global BENCH_ARGV array.
# Each leaf owns its own defaults; the dispatcher only appends a --flag when
# the controlling env knob is explicitly set (so e.g. a future change to a
# leaf's default judge is never re-pinned to a stale value here).
build_bench_argv() {   # id model_path
  local id="$1" model_path="$2"
  BENCH_ARGV=()
  case "$id" in
    eval_base)      BENCH_ARGV=(slurm/eval_base.sh "$model_path" --tasks base) ;;
    eval_sft)       BENCH_ARGV=(slurm/eval_sft.sh "$model_path" --tasks sft) ;;
    safety_base)    BENCH_ARGV=(slurm/eval_safety_base.sh "$model_path")
                    [[ -n "${SAFETY_BASE_SOURCE_FILTER:-}" ]] && BENCH_ARGV+=(--source-filter "$SAFETY_BASE_SOURCE_FILTER") ;;
    jbb)            # A registry alias carries its own jbb config (dtype/template/
                    # pretrained); a raw path needs an explicit jbb config name
                    # (generic_instruct) plus model.pretrained=<path>.
                    if [[ -n "$LOADED_MODEL_ALIAS" ]]; then
                      BENCH_ARGV=(slurm/run_all_jbb.sh "$LOADED_MODEL_ALIAS")
                    else
                      BENCH_ARGV=(slurm/run_all_jbb.sh "${JBB_MODEL_CONFIG:-generic_instruct}" "model.pretrained=$model_path")
                    fi
                    [[ -n "${JBB_METHODS:-}" ]] && BENCH_ARGV+=(--methods "$JBB_METHODS") ;;
    dan)            BENCH_ARGV=(slurm/eval_dan.sh "$model_path")
                    [[ -n "${DAN_JUDGE:-}" ]]          && BENCH_ARGV+=(--judge "$DAN_JUDGE")
                    [[ -n "${DAN_PROMPT_LIMIT:-}" ]]   && BENCH_ARGV+=("prompt_limit=$DAN_PROMPT_LIMIT")
                    [[ -n "${DAN_BEHAVIOR_LIMIT:-}" ]] && BENCH_ARGV+=("behavior_limit=$DAN_BEHAVIOR_LIMIT") ;;
    advbench)       BENCH_ARGV=(slurm/eval_advbench.sh "$model_path")
                    [[ -n "${ADVBENCH_JUDGE:-}" ]] && BENCH_ARGV+=(--judge "$ADVBENCH_JUDGE") ;;
    pap)            BENCH_ARGV=(slurm/eval_pap.sh "$model_path")
                    [[ -n "${PAP_JUDGE:-}" ]]    && BENCH_ARGV+=(--judge "$PAP_JUDGE")
                    [[ -n "${PAP_FILE:-}" ]]     && BENCH_ARGV+=(--pap-file "$PAP_FILE") ;;
    strongreject)   BENCH_ARGV=(slurm/eval_strongreject.sh "$model_path")
                    [[ -n "${STRONGREJECT_JUDGE:-}" ]]   && BENCH_ARGV+=(--judge "$STRONGREJECT_JUDGE")
                    [[ -n "${STRONGREJECT_DATASET:-}" ]] && BENCH_ARGV+=("dataset=$STRONGREJECT_DATASET") ;;
    fortress)       BENCH_ARGV=(slurm/eval_fortress.sh "$model_path")
                    [[ -n "${FORTRESS_JUDGE:-}" ]] && BENCH_ARGV+=(--judge "$FORTRESS_JUDGE") ;;
    pair)           BENCH_ARGV=(slurm/eval_pair.sh "$model_path")
                    [[ -n "${PAIR_JUDGE:-}" ]]        && BENCH_ARGV+=(--judge "$PAIR_JUDGE")
                    [[ -n "${PAIR_INNER_JUDGE:-}" ]]  && BENCH_ARGV+=("inner_judge.kind=$PAIR_INNER_JUDGE")
                    [[ -n "${PAIR_DATASET:-}" ]]      && BENCH_ARGV+=("dataset=$PAIR_DATASET")
                    [[ -n "${PAIR_N_STREAMS:-}" ]]    && BENCH_ARGV+=("n_streams=$PAIR_N_STREAMS")
                    [[ -n "${PAIR_N_ITERATIONS:-}" ]] && BENCH_ARGV+=("n_iterations=$PAIR_N_ITERATIONS")
                    [[ -n "${PAIR_ATTACKER:-}" ]]     && BENCH_ARGV+=("attack.pretrained=$PAIR_ATTACKER")
                    [[ -n "${PAIR_TESTING:-}" ]]      && BENCH_ARGV+=("testing=$PAIR_TESTING") ;;
    em)             BENCH_ARGV=(slurm/eval_em.sh "$model_path")
                    [[ -n "${EM_JUDGE_MODE:-}" ]]     && BENCH_ARGV+=(--judge-mode "$EM_JUDGE_MODE")
                    [[ -n "${EM_QUESTIONS:-}" ]]      && BENCH_ARGV+=(--questions "$EM_QUESTIONS")
                    [[ -n "${EM_N_PER_QUESTION:-}" ]] && BENCH_ARGV+=(--n-per-question "$EM_N_PER_QUESTION") ;;
    airisk)         BENCH_ARGV=(slurm/eval_airisk.sh "$model_path")
                    [[ -n "${AIRISK_DATASET_SUBSET:-}" ]] && BENCH_ARGV+=("dataset_subset=$AIRISK_DATASET_SUBSET")
                    [[ -n "${AIRISK_NUM_DILEMMAS:-}" ]]   && BENCH_ARGV+=("num_dilemmas=$AIRISK_NUM_DILEMMAS") ;;
    pez)            BENCH_ARGV=(slurm/eval_pez.sh "$LOADED_MODEL_ALIAS") ;;
    overrefusal)    BENCH_ARGV=(slurm/eval_overrefusal.sh "$model_path") ;;
    overrefusal_xs) BENCH_ARGV=(slurm/eval_overrefusal.sh "$model_path" --bench xstest) ;;
    # abliteration: NOT built here — it is a login-node multi-sbatch chain
    # (abliterate -> 4 eval jobs with internal afterok deps) dispatched via a
    # dedicated branch in _dispatch_one_suite; it cannot share the single
    # --environment/--export sbatch path.
    *) echo "build_bench_argv: unknown bench '$id'" >&2; return 1 ;;
  esac
  # Return 0 explicitly: the trailing `[[ -n X ]] && BENCH_ARGV+=(...)` idioms
  # above yield exit 1 when the knob is unset, which under `set -e` would
  # otherwise abort the caller.
  return 0
}

_dispatch_usage() {
  cat <<EOF
Usage:
  bash slurm/${SCRIPT_ENTRY:-submit_*_evals.sh} --model <ref>   [groups] [options]
  bash slurm/${SCRIPT_ENTRY:-submit_*_evals.sh} --manifest <p>  [groups] [options]
  bash slurm/${SCRIPT_ENTRY:-submit_*_evals.sh} --list-models

Groups (default: all):
  --capability  --safety  --safety-ablations  --all

Options:
  --model <ref>        registry alias | HF id | checkpoint path
  --manifest <path>    training manifest (.env); evals every checkpoint in it
  --only <id,id,...>   run exactly these bench ids (overrides group flags),
                       e.g. --only eval_sft,jbb
  --skip-eval-sft      skip the general-capability eval
  --dry-run            print the sbatch commands without submitting
  --list-models        list registered model aliases

Per-bench env knobs (unset => the leaf's own default applies):
  JBB_METHODS JBB_MODEL_CONFIG DAN_JUDGE DAN_PROMPT_LIMIT DAN_BEHAVIOR_LIMIT
  ADVBENCH_JUDGE PAP_JUDGE PAP_FILE STRONGREJECT_JUDGE STRONGREJECT_DATASET
  FORTRESS_JUDGE
  PAIR_JUDGE PAIR_INNER_JUDGE PAIR_DATASET PAIR_N_STREAMS PAIR_N_ITERATIONS
  PAIR_ATTACKER PAIR_TESTING
  EM_JUDGE_MODE EM_QUESTIONS EM_N_PER_QUESTION SAFETY_BASE_SOURCE_FILTER
EOF
}

_group_selected() {
  local g
  for g in "${SELECTED_GROUPS[@]}"; do
    [[ "$g" == "$1" ]] && return 0
  done
  return 1
}

# A bench is selected by an explicit --only id list when given, otherwise by
# its group being among the selected groups. (SCRIPT_MTYPE is checked
# separately by the caller.)
_bench_selected() {
  local id="$1" want
  if [[ -n "$ONLY_IDS" ]]; then
    for want in ${ONLY_IDS//,/ }; do
      [[ "$want" == "$id" ]] && return 0
    done
    return 1
  fi
  _group_selected "${BENCH_GROUP[$id]}"
}

# Submit the selected suite for a single model / checkpoint.
_dispatch_one_suite() {   # model_path run_name ckpt_label label_prefix
  local model_path="$1" run_name="$2" ckpt_label="$3" label_prefix="$4"
  local eval_label job_label id jid out j

  if [[ -n "$ckpt_label" ]]; then
    eval_label="$(mr_eval_build_eval_label "${label_prefix:-$run_name}" "$ckpt_label")"
  else
    eval_label="$(mr_eval_slugify_label "${label_prefix:-$run_name}")"
  fi
  job_label="${ckpt_label:-${label_prefix:-$run_name}}"
  DISPATCH_EVAL_LABEL="$eval_label"

  echo "── suite: $eval_label ──"
  echo "  model:  $model_path"
  echo "  groups: ${SELECTED_GROUPS[*]}"

  for id in "${BENCH_ORDER[@]}"; do
    [[ "${BENCH_MTYPE[$id]}" == "$SCRIPT_MTYPE" ]] || continue
    _bench_selected "$id" || continue
    if [[ "$id" == eval_sft && "$SKIP_EVAL_SFT" == "1" ]]; then
      echo "  skip eval_sft (--skip-eval-sft)"; continue
    fi
    if [[ "$id" == pez || "$id" == abliteration ]] && [[ -z "$LOADED_MODEL_ALIAS" ]]; then
      echo "  skip $id (needs a registry alias; '$model_path' is a raw path)"; continue
    fi

    if [[ "$id" == abliteration ]]; then
      # Dedicated branch: run_alias.sh issues its own sbatches (with internal
      # afterok deps) from the login node and sets --environment per sub-job.
      # It prints `JID=<id>` lines we fold into DISPATCH_SUBMITTED_JIDS.
      out="$(DRY_RUN="$DRY_RUN" "$REPO_ROOT/abliteration/slurm/run_alias.sh" "$LOADED_MODEL_ALIAS")"
      printf '%s\n' "$out"
      while IFS= read -r j; do
        [[ -n "$j" ]] && DISPATCH_SUBMITTED_JIDS+=("$j")
      done < <(printf '%s\n' "$out" | sed -n 's/^JID=//p')
      continue
    fi

    build_bench_argv "$id" "$model_path"
    jid="$(mr_eval_submit_job_parsable "$REPO_ROOT/${BENCH_WORKDIR[$id]}" "${id}[$job_label]" "$DRY_RUN" \
      --environment="$(mr_eval_env_toml "${BENCH_ENVKIND[$id]}")" \
      --export="ALL,MR_EVAL_MODEL_NAME=$eval_label" \
      "${BENCH_ARGV[@]}")"
    echo "  $jid"
    DISPATCH_SUBMITTED_JIDS+=("$jid")
  done
  return 0
}

run_dispatch() {
  local mtype="${SCRIPT_MTYPE:?run_dispatch: SCRIPT_MTYPE must be set by the entry script}"
  local model_input="" manifest="" i
  local -a groups=()
  ONLY_IDS=""
  DRY_RUN="${DRY_RUN:-0}"
  SKIP_EVAL_SFT="${SKIP_EVAL_SFT:-0}"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --capability)        groups+=(capability); shift ;;
      --safety)            groups+=(safety); shift ;;
      --safety-ablations)  groups+=(safety_ablation); shift ;;
      --all)               groups=(capability safety safety_ablation); shift ;;
      --only)              ONLY_IDS="$2"; shift 2 ;;
      --model)             model_input="$2"; shift 2 ;;
      --manifest)          manifest="$2"; shift 2 ;;
      --skip-eval-sft)     SKIP_EVAL_SFT=1; shift ;;
      --dry-run)           DRY_RUN=1; shift ;;
      --list-models)       mr_eval_print_registered_models; return 0 ;;
      -h|--help)           _dispatch_usage; return 0 ;;
      -*)                  echo "Unknown argument: $1" >&2; _dispatch_usage >&2; return 1 ;;
      *)                   # bare positional => model ref convenience
                           if [[ -z "$model_input" ]]; then model_input="$1"; shift
                           else echo "Unexpected argument: $1" >&2; return 1; fi ;;
    esac
  done

  [[ "${#groups[@]}" -eq 0 ]] && groups=(capability safety safety_ablation)
  SELECTED_GROUPS=("${groups[@]}")

  if [[ -z "$model_input" && -z "$manifest" ]]; then
    echo "Provide --model <ref> or --manifest <path>." >&2; _dispatch_usage >&2; return 1
  fi
  if [[ -n "$model_input" && -n "$manifest" ]]; then
    echo "Use either --model or --manifest, not both." >&2; return 1
  fi

  mr_eval_submit_logs_dir "$REPO_ROOT"
  DISPATCH_SUBMITTED_JIDS=()
  DISPATCH_EVAL_LABEL=""

  if [[ -n "$model_input" ]]; then
    resolve_model_input "$model_input"
    _dispatch_one_suite "$LOADED_MODEL_PATH" "$LOADED_RUN_NAME" "$LOADED_MODEL_CHECKPOINT_LABEL" "$LOADED_EVAL_LABEL_PREFIX"
  else
    load_manifest "$manifest"
    select_manifest_models "$LOADED_CKPT_DIR" "$LOADED_FINAL_MODEL_DIR"
    echo "Manifest checkpoints: ${#SELECTED_MODEL_PATHS[@]}"
    for i in "${!SELECTED_MODEL_PATHS[@]}"; do
      _dispatch_one_suite "${SELECTED_MODEL_PATHS[$i]}" "$LOADED_RUN_NAME" "${SELECTED_MODEL_LABELS[$i]}" "$LOADED_EVAL_LABEL_PREFIX"
    done
  fi
}
