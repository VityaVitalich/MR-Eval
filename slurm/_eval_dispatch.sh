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
#   group     : capability | safety | safety_ablation | ft | optional
#               ft = fine-tune-then-eval chains (training job + per-checkpoint
#               evals); optional = never in the default set, --only only.
#   model_type: base | instruct   (which entry script owns it)
#   workdir   : component dir (relative to repo root) to sbatch from
#   env_kind  : pyxis container for mr_eval_env_toml
# Membership encodes the base/instruct split: the base entry script only
# ever sees base rows, the instruct entry script only instruct rows.
#
# THE DEFAULT SET (fixed 2026-10-11) = every row except group `optional`, i.e.
# what a bare `submit_posttrain_evals.sh <alias>` (or --all) submits:
#   instruct: eval_sft | jbb dan advbench pap strongreject fortress
#             prefill_advbench pair em airisk morebench morebench_theory pez
#             charter_mcq | overrefusal overrefusal_xs abliteration |
#             ft_em_muon ft_alpaca_muon (registry -sft aliases only)
#   base:     eval_base | safety_base
# --------------------------------------------------------------------------
BENCH_ORDER=(eval_base safety_base eval_sft jbb dan advbench pap strongreject fortress prefill_jbb prefill_advbench pair gcg em airisk morebench morebench_theory pez charter_mcq overrefusal overrefusal_xs abliteration ft_em_muon ft_alpaca_muon)
declare -A BENCH_GROUP BENCH_MTYPE BENCH_WORKDIR BENCH_ENVKIND
_bench() { BENCH_GROUP[$1]=$2; BENCH_MTYPE[$1]=$3; BENCH_WORKDIR[$1]=$4; BENCH_ENVKIND[$1]=$5; }
#      id              group            mtype     workdir       env_kind
_bench eval_base       capability       base      eval          eval
_bench safety_base     safety           base      safety_base   train
_bench eval_sft        capability       instruct  eval          eval
_bench jbb             safety           instruct  jbb           train
_bench dan             safety           instruct  jailbreaks    train
_bench advbench        safety           instruct  jailbreaks    train
_bench pap             safety           instruct  jailbreaks    train
_bench strongreject    safety           instruct  jailbreaks    train
_bench fortress        safety           instruct  jailbreaks    train
# prefill_advbench is the dataset the dashboard's Prefill panel reads (520
# behaviours; commit ce9c955). prefill_jbb stays runnable (--only) for the
# older jbb-sourced runs but left the default set on 2026-10-11.
_bench prefill_jbb     optional         instruct  jailbreaks    train
_bench prefill_advbench safety          instruct  jailbreaks    train
_bench pair            safety           instruct  jailbreaks    harmbench
# gcg (transfer track) is intentionally NOT fanned out: eval_gcg.sh defaults to
# data/gcg/transfer_default.jsonl, a placeholder suffix file ("! ! !", no
# adversarial power), so a matrix run is a no-attack baseline, not a real GCG
# attack. Real per-model GCG (nanogcg optimization) lives in
# jailbreaks/slurm/run_gcg_per_model.sh and is run on demand.
# _bench gcg             safety           instruct  jailbreaks    train
_bench em              safety           instruct  em            train
_bench airisk          safety           instruct  airisk        train
# morebench / morebench_theory submit STAGE 1 (generation) only; Stage 2
# (judging over the Swiss-AI gateway) runs separately on a login node / the
# Mac against a served gpt-oss-120b — see morebench/README.md.
_bench morebench        safety          instruct  morebench     train
_bench morebench_theory safety          instruct  morebench     train
_bench pez             safety           instruct  harmbench     harmbench
# Charter (constitution) behavioural MCQ: swap-debiased logprobs, no judge.
_bench charter_mcq     safety           instruct  charter_mcq   train
_bench overrefusal     safety_ablation  instruct  overrefusal   train
_bench overrefusal_xs  safety_ablation  instruct  overrefusal   train
_bench abliteration    safety_ablation  instruct  abliteration  train   # env_kind unused: run_alias.sh sets env per sub-job
# Fine-tuning robustness, both with Muon (the recipes compared on the 1PP 1.7B
# models, 2026-10-06). Each row is a login-node chain through
# submit_post_train_training.sh: one training job, then the per-checkpoint
# evals of run_post_train_evals.sh. Only for registry aliases that went through
# SFT; pretrain-only checkpoints (1PP *_base) are skipped. workdir/env unused.
#   ft_em_muon     em_health_incorrect, em_paper_muon_lr1e5 (375 steps, batch
#                  16, Muon lr 1e-5 = AdamW's loss; the standard EM recipe of
#                  submit_post_train_training.sh), then em (em_values_v1 x 20,
#                  DeepSeek ds_v1) per checkpoint;
#                  labels <alias>_em_incorrect_health_muon_lr1e5_<step>
#   ft_alpaca_muon bs_alpaca_no_safety_2k, bs_1ep_ckpt100_muon_lr5e5 (100 steps,
#                  Muon lr 5e-5 = AdamW's lr, which already fits better;
#                  checkpoint every 100 samples), then JBB direct per checkpoint;
#                  labels <alias>_bs_alpaca_no_safety_2k_muon_lr5e5_<step>
_bench ft_em_muon      ft               instruct  .             train
_bench ft_alpaca_muon  ft               instruct  .             train

# Build the leaf argv for a bench into the global BENCH_ARGV array.
# Each leaf owns its own defaults; the dispatcher only appends a --flag when
# the controlling env knob is explicitly set (so e.g. a future change to a
# leaf's default judge is never re-pinned to a stale value here).
build_bench_argv() {   # id model_path
  local id="$1" model_path="$2"
  BENCH_ARGV=()
  case "$id" in
    eval_base)      BENCH_ARGV=(slurm/eval_base.sh "$model_path" --tasks base) ;;
    # EVAL_SFT_TASKS picks the tasks group: sft (default) or sft_gen, the
    # open-ended generation track (eval/conf/tasks/sft_gen.yaml).
    eval_sft)       BENCH_ARGV=(slurm/eval_sft.sh "$model_path" --tasks "${EVAL_SFT_TASKS:-sft}") ;;
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
    prefill_jbb)    BENCH_ARGV=(slurm/eval_prefill.sh "$model_path" --dataset jbb)
                    [[ -n "${PREFILL_JUDGE:-}" ]] && BENCH_ARGV+=(--judge "$PREFILL_JUDGE") ;;
    prefill_advbench) BENCH_ARGV=(slurm/eval_prefill.sh "$model_path" --dataset advbench)
                    [[ -n "${PREFILL_JUDGE:-}" ]] && BENCH_ARGV+=(--judge "$PREFILL_JUDGE") ;;
    pair)           BENCH_ARGV=(slurm/eval_pair.sh "$model_path")
                    [[ -n "${PAIR_JUDGE:-}" ]]        && BENCH_ARGV+=(--judge "$PAIR_JUDGE")
                    [[ -n "${PAIR_INNER_JUDGE:-}" ]]  && BENCH_ARGV+=("inner_judge.kind=$PAIR_INNER_JUDGE")
                    [[ -n "${PAIR_DATASET:-}" ]]      && BENCH_ARGV+=("dataset=$PAIR_DATASET")
                    [[ -n "${PAIR_N_STREAMS:-}" ]]    && BENCH_ARGV+=("n_streams=$PAIR_N_STREAMS")
                    [[ -n "${PAIR_N_ITERATIONS:-}" ]] && BENCH_ARGV+=("n_iterations=$PAIR_N_ITERATIONS")
                    [[ -n "${PAIR_ATTACKER:-}" ]]     && BENCH_ARGV+=("attack.pretrained=$PAIR_ATTACKER")
                    [[ -n "${PAIR_TESTING:-}" ]]      && BENCH_ARGV+=("testing=$PAIR_TESTING") ;;
    gcg)            # Transfer-track only. The per-model optimization track is
                    # too slow to fan out across the whole matrix and lives
                    # under jailbreaks/slurm/run_gcg_per_model.sh.
                    BENCH_ARGV=(slurm/eval_gcg.sh "$model_path")
                    [[ -n "${GCG_JUDGE:-}" ]] && BENCH_ARGV+=(--judge "$GCG_JUDGE")
                    [[ -n "${GCG_FILE:-}" ]]  && BENCH_ARGV+=(--gcg-file "$GCG_FILE") ;;
    em)             BENCH_ARGV=(slurm/eval_em.sh "$model_path")
                    [[ -n "${EM_JUDGE_MODE:-}" ]]     && BENCH_ARGV+=(--judge-mode "$EM_JUDGE_MODE")
                    [[ -n "${EM_QUESTIONS:-}" ]]      && BENCH_ARGV+=(--questions "$EM_QUESTIONS")
                    [[ -n "${EM_N_PER_QUESTION:-}" ]] && BENCH_ARGV+=(--n-per-question "$EM_N_PER_QUESTION") ;;
    airisk)         BENCH_ARGV=(slurm/eval_airisk.sh "$model_path")
                    [[ -n "${AIRISK_DATASET_SUBSET:-}" ]] && BENCH_ARGV+=("dataset_subset=$AIRISK_DATASET_SUBSET")
                    [[ -n "${AIRISK_NUM_DILEMMAS:-}" ]]   && BENCH_ARGV+=("num_dilemmas=$AIRISK_NUM_DILEMMAS") ;;
    morebench)      BENCH_ARGV=(slurm/eval_morebench.sh "$model_path")
                    [[ -n "${MOREBENCH_NUM_SCENARIOS:-}" ]] && BENCH_ARGV+=("num_scenarios=$MOREBENCH_NUM_SCENARIOS") ;;
    morebench_theory) BENCH_ARGV=(slurm/eval_morebench.sh "$model_path" dataset_subset=theory) ;;
    pez)            BENCH_ARGV=(slurm/eval_pez.sh "$LOADED_MODEL_ALIAS") ;;
    # auto: check the registry's template override actually reached the
    # tokenizer, instead of the conf's fixed EPE marker (which only fits the
    # epe-template-nosys models; 1PP ends turns with ChatML).
    charter_mcq)    BENCH_ARGV=(slurm/eval_charter_mcq.sh "$model_path" model.expect_prompt_suffix=auto) ;;
    overrefusal)    BENCH_ARGV=(slurm/eval_overrefusal.sh "$model_path") ;;
    overrefusal_xs) BENCH_ARGV=(slurm/eval_overrefusal.sh "$model_path" --bench xstest) ;;
    # abliteration / ft_*: NOT built here — it is a login-node multi-sbatch chain
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

# ft_* rows: one login-node call of submit_post_train_training.sh per model.
# The recipe is pinned here (not inherited from the caller's BS_*/EM_* env) so
# the default set always means the same two runs. Job ids it prints are folded
# into DISPATCH_SUBMITTED_JIDS.
_dispatch_ft_chain() {   # id alias
  local id="$1" alias="$2" out j
  local -a env_args
  case "$id" in
    ft_em_muon)     env_args=(SKIP_BS=1 EM_DATASET=em_health_incorrect EM_TRAINING=em_paper_muon_lr1e5
                              EVAL_LABEL_SUFFIX=muon_lr1e5 EM_TRAIN_TIME=00:30:00
                              EM_JUDGE_MODE= EM_QUESTIONS= EM_N_PER_QUESTION=) ;;
    ft_alpaca_muon) env_args=(SKIP_EM=1 BS_DATASET=bs_alpaca_no_safety_2k BS_TRAINING=bs_1ep_ckpt100_muon_lr5e5
                              EVAL_LABEL_SUFFIX=muon_lr5e5 BS_TRAIN_TIME=00:30:00
                              JBB_METHODS=direct JBB_MODEL_CONFIG=generic_instruct) ;;
    *) echo "_dispatch_ft_chain: unknown ft bench '$id'" >&2; return 1 ;;
  esac
  # An empty SBATCH_ACCOUNT would reach sbatch as an empty account; only pass
  # one when set (otherwise each leaf's #SBATCH --account applies).
  [[ -n "${FT_ACCOUNT:-${SBATCH_ACCOUNT:-}}" ]] && env_args+=(SBATCH_ACCOUNT="${FT_ACCOUNT:-$SBATCH_ACCOUNT}")
  echo "  $id: submit_post_train_training.sh $alias (${env_args[*]})"
  # A failed chain is reported and skipped; the rest of the suite still goes out.
  if ! out="$(env "${env_args[@]}" SKIP_EVAL_SFT=1 DRY_RUN="$DRY_RUN" \
              bash "$REPO_ROOT/slurm/submit_post_train_training.sh" "$alias" 2>&1)"; then
    printf '%s\n' "$out" | sed 's/^/    /'
    echo "  $id: FAILED to submit for $alias" >&2
    return 0
  fi
  printf '%s\n' "$out" | grep -E "job id|manifest|Submitting" | sed 's/^/    /'
  while IFS= read -r j; do
    [[ -n "$j" ]] && DISPATCH_SUBMITTED_JIDS+=("$j")
  done < <(printf '%s\n' "$out" | sed -n 's/.*job id: *\([0-9][0-9]*\)$/\1/p')
  return 0
}

_dispatch_usage() {
  cat <<EOF
Usage:
  bash slurm/${SCRIPT_ENTRY:-submit_*_evals.sh} --model <ref>   [groups] [options]
  bash slurm/${SCRIPT_ENTRY:-submit_*_evals.sh} --manifest <p>  [groups] [options]
  bash slurm/${SCRIPT_ENTRY:-submit_*_evals.sh} --list-models

Groups (default: all of them = the default set; prefill_jbb is --only only):
  --capability  --safety  --safety-ablations  --ft  --all

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
  FORTRESS_JUDGE GCG_JUDGE GCG_FILE
  PREFILL_JUDGE
  PAIR_JUDGE PAIR_INNER_JUDGE PAIR_DATASET PAIR_N_STREAMS PAIR_N_ITERATIONS
  PAIR_ATTACKER PAIR_TESTING
  EM_JUDGE_MODE EM_QUESTIONS EM_N_PER_QUESTION SAFETY_BASE_SOURCE_FILTER
  FT_ACCOUNT (sbatch account of the ft_* chains; default \$SBATCH_ACCOUNT)
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
    if [[ "$id" == pez || "$id" == abliteration || "$id" == ft_* ]] && [[ -z "$LOADED_MODEL_ALIAS" ]]; then
      echo "  skip $id (needs a registry alias; '$model_path' is a raw path)"; continue
    fi
    if [[ "$id" == ft_* && "$LOADED_MODEL_ALIAS" == *_base ]]; then
      echo "  skip $id (pretrain-only checkpoint '$LOADED_MODEL_ALIAS'; FT starts from SFT models)"; continue
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

    if [[ "$id" == ft_* ]]; then
      _dispatch_ft_chain "$id" "$LOADED_MODEL_ALIAS"
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
      --ft)                groups+=(ft); shift ;;
      --all)               groups=(capability safety safety_ablation ft); shift ;;
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

  [[ "${#groups[@]}" -eq 0 ]] && groups=(capability safety safety_ablation ft)
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
