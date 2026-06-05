#!/bin/bash
# Fast end-to-end smoke probes for the safety/jailbreak benches on ONE model.
#
# Fires one sbatch per bench with the bench's own `testing=true testing_limit=N`
# (or `limit=N`, or a 2-behavior PEZ subset) so a single model end-to-ends
# quickly. Every job uses the same workdir, container, chat-template setup, and
# judge as a real run — only prompt count and wall are trimmed — so a clean
# smoke gives confidence that the same model will run cleanly at full size.
#
# Excluded by design: em, airisk.
#
# Run on the login node (this is a submitter, not a compute job):
#   bash slurm/submit_smoke_safety.sh <model_ref>
#   bash slurm/submit_smoke_safety.sh <model_ref> --only jbb,dan,pair
#   bash slurm/submit_smoke_safety.sh <model_ref> --dry-run
#
# Bench ids: jbb dan advbench pap strongreject fortress pair pez overrefusal

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# shellcheck disable=SC1091
source "$SCRIPT_DIR/_submit_common.sh"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_resolve_env_toml.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/model_registry.sh"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_manifest.sh"   # for resolve_model_input + mr_eval_slugify_label

usage() {
  cat <<EOF
Usage: bash slurm/submit_smoke_safety.sh <model_ref> [--only id,id,...] [--partition <p>] [--dry-run]

Submits one tiny-limit sbatch per safety bench so a single model end-to-ends
in ~10-40min per bench. Same containers / chat templates / judge as real runs;
only the prompt count and wall are trimmed.

--partition  Override the leaf's partition (e.g. "debug": 90m cap, instant
             scheduling — fine for every smoke wall here).

Bench ids: jbb dan advbench pap strongreject fortress pair pez overrefusal
EOF
}

MODEL_REF=""
ONLY_IDS=""
PARTITION=""
DRY_RUN="${DRY_RUN:-0}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --only)      ONLY_IDS="$2"; shift 2 ;;
    --partition) PARTITION="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*)        echo "unknown flag: $1" >&2; usage >&2; exit 1 ;;
    *)         if [[ -z "$MODEL_REF" ]]; then MODEL_REF="$1"; shift
               else echo "unexpected arg: $1" >&2; exit 1; fi ;;
  esac
done
[[ -z "$MODEL_REF" ]] && { usage >&2; exit 1; }

mr_eval_submit_logs_dir "$REPO_ROOT"

# Resolve the model the same way submit_posttrain_evals.sh does so the smoke
# stamps the same canonical label and exercises the same alias/path branches.
resolve_model_input "$MODEL_REF"
EVAL_LABEL="$(mr_eval_slugify_label "${LOADED_EVAL_LABEL_PREFIX:-$LOADED_RUN_NAME}")-smoke"
MODEL_PATH="$LOADED_MODEL_PATH"
ALIAS="$LOADED_MODEL_ALIAS"

echo "── smoke suite ──"
echo "  model_ref : $MODEL_REF"
echo "  alias     : ${ALIAS:-<none — raw path>}"
echo "  path      : $MODEL_PATH"
echo "  label     : $EVAL_LABEL"

# Per-bench recipe. workdir + env_kind are kept in lockstep with
# slurm/_eval_dispatch.sh so the smoke walks the same code paths a real run
# would. wall + gpus are tight but match the bench's actual resource shape
# (PEZ + PAIR need 4 GPUs; the jailbreaks fused-pipeline benches fit on 1).
ORDER=(jbb dan advbench pap strongreject fortress pair pez overrefusal)

declare -A WORKDIR ENVKIND WALL GPUS
WORKDIR=(
  [jbb]=jbb               [dan]=jailbreaks      [advbench]=jailbreaks
  [pap]=jailbreaks        [strongreject]=jailbreaks
  [fortress]=jailbreaks   [pair]=jailbreaks     [pez]=harmbench
  [overrefusal]=overrefusal
)
ENVKIND=(
  [jbb]=train             [dan]=train           [advbench]=train
  [pap]=train             [strongreject]=train
  [fortress]=train        [pair]=harmbench      [pez]=harmbench
  [overrefusal]=train
)
WALL=(
  [jbb]=00:30:00          [dan]=00:15:00        [advbench]=00:15:00
  [pap]=00:15:00          [strongreject]=00:15:00
  [fortress]=00:15:00     [pair]=00:30:00       [pez]=00:45:00
  [overrefusal]=00:20:00
)
# Smoke GPU shape matches the real run's so vLLM tensor-parallel init is
# exercised at the actual size. (PEZ + PAIR + overrefusal really do need 4.)
GPUS=(
  [jbb]=1                 [dan]=1               [advbench]=1
  [pap]=1                 [strongreject]=1
  [fortress]=1            [pair]=4              [pez]=4
  [overrefusal]=4
)

build_argv() {  # id -> populates BENCH_ARGV with the leaf argv
  BENCH_ARGV=()
  case "$1" in
    jbb)
      # Same alias-vs-path branch as _eval_dispatch.sh build_bench_argv (jbb).
      if [[ -n "$ALIAS" ]]; then
        BENCH_ARGV=(slurm/run_all_jbb.sh "$ALIAS" "limit=4")
      else
        BENCH_ARGV=(slurm/run_all_jbb.sh "${JBB_MODEL_CONFIG:-generic_instruct}"
                    "model.pretrained=$MODEL_PATH" "limit=4")
      fi ;;
    dan|advbench|pap|strongreject|fortress)
      BENCH_ARGV=("slurm/eval_$1.sh" "$MODEL_PATH" "testing=true" "testing_limit=4") ;;
    pair)
      # PAIR is iterative: 3 goals × 2 streams × 2 iterations ≈ 12 attempts —
      # enough to exercise attacker-serve, target inference, and the rule
      # judge without dragging on.
      BENCH_ARGV=(slurm/eval_pair.sh "$MODEL_PATH"
                  "testing=true" "testing_limit=3"
                  "n_streams=2" "n_iterations=2") ;;
    pez)
      # PEZ is per-behavior gradient optimization; subset to 2 stable val-set
      # behaviors so the run is bounded. eval_pez.sh reads
      # HARMBENCH_BEHAVIOR_IDS_SUBSET from the env (we pass it via --export).
      [[ -z "$ALIAS" ]] && {
        echo "  skip pez (needs a registry alias; '$MODEL_REF' is a raw path)" >&2
        return 1
      }
      BENCH_ARGV=(slurm/eval_pez.sh "$ALIAS"
                  --behaviors ./data/behavior_datasets/harmbench_behaviors_text_val_plain.csv) ;;
    overrefusal)
      BENCH_ARGV=(slurm/eval_overrefusal.sh "$MODEL_PATH"
                  "testing=true" "testing_limit=4") ;;
    *) echo "build_argv: unknown bench '$1'" >&2; return 1 ;;
  esac
}

selected() {
  [[ -z "$ONLY_IDS" ]] && return 0
  local want
  for want in ${ONLY_IDS//,/ }; do [[ "$want" == "$1" ]] && return 0; done
  return 1
}

SUBMITTED=()
for id in "${ORDER[@]}"; do
  selected "$id" || continue
  if ! build_argv "$id"; then continue; fi

  # Smoke-only sbatch overrides: --time tightens wall (the leaf's #SBATCH
  # --time is the real-run default and is larger), --nice deprioritizes vs
  # real work, --gres restates the resource shape so the sbatch flags stay
  # explicit even when we go through a workdir whose leaf default differs.
  SBATCH_FLAGS=(
    --time="${WALL[$id]}"
    --gres="gpu:${GPUS[$id]}"
    --nice=100
    --environment="$(mr_eval_env_toml "${ENVKIND[$id]}")"
  )
  [[ -n "$PARTITION" ]] && SBATCH_FLAGS+=(--partition="$PARTITION")
  # Stamp the canonical label. PEZ also needs HARMBENCH_BEHAVIOR_IDS_SUBSET,
  # but that value contains a comma and sbatch --export uses commas as the
  # env-var separator — so we export it in our own environment and rely on
  # `ALL` to forward it into the job.
  if [[ "$id" == "pez" ]]; then
    export HARMBENCH_BEHAVIOR_IDS_SUBSET="safrole_oil_extraction_guide,women_inferiority_argument"
  fi
  SBATCH_FLAGS+=(--export="ALL,MR_EVAL_MODEL_NAME=$EVAL_LABEL")

  jid="$(mr_eval_submit_job_parsable "$REPO_ROOT/${WORKDIR[$id]}" "smoke[$id]" "$DRY_RUN" \
    "${SBATCH_FLAGS[@]}" "${BENCH_ARGV[@]}")"
  echo "  $id -> $jid"
  SUBMITTED+=("$id:$jid")
done

# Best-effort: unexport so a follow-up invocation doesn't carry stale state.
unset HARMBENCH_BEHAVIOR_IDS_SUBSET 2>/dev/null || true

echo
echo "── submitted ──"
for entry in "${SUBMITTED[@]}"; do echo "  $entry"; done
echo "  count: ${#SUBMITTED[@]}"
