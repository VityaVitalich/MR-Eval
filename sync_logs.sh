#!/usr/bin/env bash
# Sync eval outputs and RunAI job logs from the RCP cluster to local.
#
# Usage (from repo root on your laptop):
#   ./sync_logs.sh                # sync everything (RunAI + clariden)
#   ./sync_logs.sh --jobs-only    # only fetch RunAI job logs
#   ./sync_logs.sh --runai-only   # only sync RunAI / jumphost
#   ./sync_logs.sh --clariden-only# only sync clariden
#   ./sync_logs.sh --dry-run      # show what would be synced
#
# Requires: runai-rcp-prod (for job logs), ssh jumphost (for RCP files),
#           ssh clariden (for SLURM logs/outputs)
#
# Output layout (under $MR_EVAL_DATA_DIR, default
# /capstor/store/cscs/swissai/infra01/vvmoskvoretskii/mr_evals_vvm):
#   logs/
#     runai/          ← one .log file per mr-* job (RunAI)
#     slurm/          ← SLURM .out/.err files (clariden)
#     eval/           ← lm-eval JSON results (RunAI)
#     em/             ← EM eval outputs (RunAI)
#     safety_base/    ← safety_base outputs (RunAI)
#     jailbreaks/     ← jailbreaks outputs (RunAI)
#     train/          ← training run outputs (RunAI)
#   outputs/
#     manifests/      ← job manifests (clariden)
#     post_train_reports/ ← post-train reports (clariden)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$REPO_ROOT/slurm/_resolve_data_dir.sh"

MOUNT_ROOT=/mnt/dlab/scratch/dlabscratch1/moskvore
WORKSPACE=${MOUNT_ROOT}/MR-Eval
LOCAL_LOGS="$MR_EVAL_DATA_DIR/logs"
LOCAL_OUTPUTS="$MR_EVAL_DATA_DIR/outputs"
RUNAI_BIN=$(command -v runai-rcp-prod 2>/dev/null || echo /usr/local/bin/runai-rcp-prod)
RUNAI="SUPPRESS_DEPRECATION_MESSAGE=true $RUNAI_BIN"
CLUSTER_HOST=${CLUSTER_HOST:-jumphost}  # override: CLUSTER_HOST=... ./sync_logs.sh
CLARIDEN_HOST=${CLARIDEN_HOST:-clariden}
CLARIDEN_WORKSPACE=/users/vvmoskvoretskii/MR-Eval
# Post-PR#8: clariden eval data, manifests, reports, and SLURM .out/.err
# are all rsync'd into the infra01 shared store on /capstor. Source clariden
# files from there, not from the per-user checkout, so we pick up runs
# from any cluster member (e.g. Julian's jkminder/* overrefusal sweeps).
CLARIDEN_DATA_DIR=${CLARIDEN_DATA_DIR:-/capstor/store/cscs/swissai/infra01/vvmoskvoretskii/mr_evals_vvm}

JOBS_ONLY=false
DRY_RUN=false
CLARIDEN_ONLY=false
RUNAI_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --jobs-only)      JOBS_ONLY=true ;;
        --dry-run)        DRY_RUN=true ;;
        --clariden-only)  CLARIDEN_ONLY=true ;;
        --runai-only)     RUNAI_ONLY=true ;;
        *) echo "Unknown arg: $arg"; exit 1 ;;
    esac
done

RSYNC_OPTS="-az --update --progress --exclude=._* --exclude=goal_logs/"
# --update: skip files where the LOCAL copy is newer than the remote.
# Critical because judge_audit/rejudge_runs.py writes v5-stamped versions
# of safety eval files in logs/clariden/* with larger size + newer mtime;
# without --update, rsync would overwrite them with the cluster's stale
# legacy versions on the next sync.
# --exclude=._*: skip macOS resource-fork files (AppleDouble) that get
# created when laptop-tarred logs round-trip through HF + clariden.
# --exclude=goal_logs/: PAIR writes ~30 MB of per-goal iteration logs per
# run (vs a ~4 MB result json); the dashboard reads only the pair__*.json
# result file (harmbench/plot_pair_dynamics.py reads goal_logs, offline).
# Dropping them takes the jailbreaks sync from ~12 GB to ~1.5 GB.
$DRY_RUN && RSYNC_OPTS="$RSYNC_OPTS --dry-run"

sync_dir() {
    local label="$1"
    local remote_path="$2"
    local local_path="$3"
    local host="${4:-$CLUSTER_HOST}"

    echo "  $label"
    mkdir -p "$local_path"
    # shellcheck disable=SC2086
    rsync $RSYNC_OPTS \
        --exclude="*.bin" \
        --exclude="*.safetensors" \
        --exclude="*.pt" \
        --exclude="optimizer.pt" \
        -e "ssh -q" \
        "${host}:${remote_path}/" \
        "$local_path/" \
    || echo "    (skipped — path not found or empty)"
    echo ""
}

mkdir -p "$LOCAL_LOGS/runai"

echo "============================================================"
echo "  MR-Eval log sync  →  $LOCAL_LOGS"
$DRY_RUN && echo "  [DRY RUN]"
echo "============================================================"
echo ""

# ── 1. RunAI job logs ───────────────────────────────────────────────────────
if ! $CLARIDEN_ONLY; then

# Skip finished jobs already cached (they won't change).
echo "[1/3] Fetching RunAI job logs..."

job_list=$(eval "$RUNAI list 2>/dev/null")

while IFS= read -r line; do
    job=$(echo "$line"    | awk '{print $1}')
    status=$(echo "$line" | awk '{print $2}')
    [[ "$job" == NAME ]] && continue
    [[ "$job" == mr-* ]] || continue

    outfile="$LOCAL_LOGS/runai/${job}.log"

    if [[ -f "$outfile" ]] && [[ "$status" != "Running" ]] && [[ "$status" != "Pending" ]]; then
        echo "  [cached] $job ($status)"
        continue
    fi

    echo "  $job ($status) → logs/runai/${job}.log"
    $DRY_RUN && continue

    eval "$RUNAI logs '$job' > '$outfile' 2>&1" || \
        echo "         (no logs yet)"

done <<< "$job_list"

echo ""

# ── 2. Eval outputs via rsync over jumphost ─────────────────────────────────
if $JOBS_ONLY; then
    echo "Done (--jobs-only)."
    exit 0
fi

echo "[2/3] Syncing eval outputs via $CLUSTER_HOST..."
echo ""

sync_dir "eval/outputs      → logs/eval/"        "${WORKSPACE}/eval/outputs"        "$LOCAL_LOGS/eval"
sync_dir "em/outputs        → logs/em/"          "${WORKSPACE}/em/outputs"          "$LOCAL_LOGS/em"
sync_dir "safety_base/      → logs/safety_base/" "${WORKSPACE}/safety_base/outputs" "$LOCAL_LOGS/safety_base"
sync_dir "jailbreaks/       → logs/jailbreaks/"  "${WORKSPACE}/jailbreaks/outputs"  "$LOCAL_LOGS/jailbreaks"
sync_dir "train/outputs     → logs/train/"       "${WORKSPACE}/train/outputs"       "$LOCAL_LOGS/train"

fi # end !CLARIDEN_ONLY

# ── 3. Clariden (SLURM) logs and outputs ────────────────────────────────────
if ! $RUNAI_ONLY && ! $JOBS_ONLY; then

echo "[3/3] Syncing from clariden ($CLARIDEN_HOST)..."
echo ""

mkdir -p "$LOCAL_LOGS/slurm"

# SLURM job logs (.out / .err)
sync_dir "clariden logs      → logs/slurm/"                "${CLARIDEN_DATA_DIR}/logs/slurm"               "$LOCAL_LOGS/slurm"                "$CLARIDEN_HOST"

# Outputs: manifests and post-train reports
sync_dir "clariden manifests → outputs/manifests/"         "${CLARIDEN_DATA_DIR}/outputs/manifests"        "$LOCAL_OUTPUTS/manifests"         "$CLARIDEN_HOST"
sync_dir "clariden reports   → outputs/post_train_reports/" "${CLARIDEN_DATA_DIR}/outputs/post_train_reports" "$LOCAL_OUTPUTS/post_train_reports" "$CLARIDEN_HOST"

# Eval outputs from clariden (base + SFT standalone runs, all models).
# Post-PR#8, all clariden eval outputs live under
# /capstor/.../mr_evals/logs/clariden/<bench>/ — the per-user checkout
# paths (eval/outputs/, em/outputs/, ...) are no longer the source of
# truth, because Hydra writes go to $MR_EVAL_DATA_DIR/outputs/<bench>
# and Julian's one-time migration moved historical data into
# logs/clariden/<bench>/ on /capstor.
mkdir -p "$LOCAL_LOGS/clariden"
sync_dir "clariden eval       → logs/clariden/eval/"        "${CLARIDEN_DATA_DIR}/logs/clariden/eval"        "$LOCAL_LOGS/clariden/eval"        "$CLARIDEN_HOST"
sync_dir "clariden em         → logs/clariden/em_eval/"     "${CLARIDEN_DATA_DIR}/logs/clariden/em_eval"     "$LOCAL_LOGS/clariden/em_eval"     "$CLARIDEN_HOST"
sync_dir "clariden safety     → logs/clariden/safety_base/" "${CLARIDEN_DATA_DIR}/logs/clariden/safety_base" "$LOCAL_LOGS/clariden/safety_base" "$CLARIDEN_HOST"
sync_dir "clariden jailbreaks → logs/clariden/jailbreaks/"  "${CLARIDEN_DATA_DIR}/logs/clariden/jailbreaks"  "$LOCAL_LOGS/clariden/jailbreaks" "$CLARIDEN_HOST"
# PEZ: build_data.py reads only PEZ/<alias>/results/<alias>_summary.json
# (~3.7 MB across ~64 files). The full tree is ~38 GB of raw hard-prompt
# optimization artifacts (test cases, per-step logs) the dashboard never
# touches, so pull ONLY the summary jsons — not the whole directory.
echo "  clariden PEZ       → logs/clariden/pez/ (summaries only)"
mkdir -p "$LOCAL_LOGS/clariden/pez"
# shellcheck disable=SC2086
rsync $RSYNC_OPTS \
    --include='*/' \
    --include='*_summary.json' \
    --exclude='*' \
    -e "ssh -q" \
    "${CLARIDEN_HOST}:${CLARIDEN_DATA_DIR}/logs/clariden/pez/" \
    "$LOCAL_LOGS/clariden/pez/" \
|| echo "    (skipped — path not found or empty)"
echo ""
sync_dir "clariden canaries   → logs/clariden/canaries/"     "${CLARIDEN_DATA_DIR}/logs/clariden/canaries"    "$LOCAL_LOGS/clariden/canaries"    "$CLARIDEN_HOST"
sync_dir "clariden overrefusal → logs/clariden/overrefusal/"  "${CLARIDEN_DATA_DIR}/logs/clariden/overrefusal" "$LOCAL_LOGS/clariden/overrefusal" "$CLARIDEN_HOST"
# overrefusal also writes to the fresh Hydra location $MR_EVAL_DATA_DIR/outputs/overrefusal
# (build_data.py's OVERREFUSAL_DIRS already checks both) — the legacy logs/clariden/overrefusal
# tree above stopped receiving new runs at some point, so recent sweeps (e.g. the cite 1.7B
# s10 grid, 2026-06-25) silently never reached the dashboard. Pull outputs/ directly too.
sync_dir "clariden overrefusal out → outputs/overrefusal/" "${CLARIDEN_DATA_DIR}/outputs/overrefusal"       "$LOCAL_OUTPUTS/overrefusal"       "$CLARIDEN_HOST"
# airisk writes only to the fresh Hydra location ($MR_EVAL_DATA_DIR/outputs/airisk);
# no legacy logs/clariden/airisk migration exists, so pull outputs/ directly.
sync_dir "clariden airisk     → outputs/airisk/"           "${CLARIDEN_DATA_DIR}/outputs/airisk"            "$LOCAL_OUTPUTS/airisk"            "$CLARIDEN_HOST"
# constitution-in-context experiment runs (qwen3_32b / gpt_oss_120b / gemma4_31b_it
# × base/sysconst02/userconst02) — separate dir, same schema plus a
# generation_reasoning block; consumed by the dashboard's airisk tab.
sync_dir "clariden airisk_ctx → outputs/airisk_ctx/"       "${CLARIDEN_DATA_DIR}/outputs/airisk_ctx"        "$LOCAL_OUTPUTS/airisk_ctx"        "$CLARIDEN_HOST"

# Jailbreaks suite (pair / strongreject / fortress / advbench / dan / pap) writes
# to the fresh Hydra location $MR_EVAL_DATA_DIR/outputs/jailbreaks/<bench>, which
# is what dashboard/build_data.py reads — it is NOT migrated to logs/clariden — so
# pull it directly, else sync→build→deploy silently drops clariden-run jailbreak
# evals (e.g. the PAIR safety-% grid).
sync_dir "clariden jailbreaks out → outputs/jailbreaks/"   "${CLARIDEN_DATA_DIR}/outputs/jailbreaks"        "$LOCAL_OUTPUTS/jailbreaks"        "$CLARIDEN_HOST"

# PEZ new-schema per-sample results. build_data.py reads two PEZ sources: the
# legacy summaries under logs/clariden/pez (synced above, summaries-only) AND
# the provenance-aware per-sample files NEW_SCHEMA_BENCHES["pez"] expects at
# outputs/pez/pez__<model>__<judge>__<sampling>.json. The latter was never
# synced, so deepseek-judged PEZ runs silently never reached the dashboard —
# pull outputs/pez directly (same rationale as the jailbreaks tree above).
sync_dir "clariden pez out    → outputs/pez/"              "${CLARIDEN_DATA_DIR}/outputs/pez"               "$LOCAL_OUTPUTS/pez"               "$CLARIDEN_HOST"

# JBB new-schema results. build_data.py's JBB_DIRS/NEW_SCHEMA_BENCHES also read
# outputs/jbb/jbb_<alias>_<method>_*/jbb__<alias>__<judge>__<sampling>.json —
# the post-train suite (run_all_jbb.sh) writes there, not to logs/clariden/jbb.
# This tree was never synced (the 3B s60 jbb runs reached local via a manual
# rsync), so new jbb runs silently never hit the dashboard. Pull only the
# result json + config.yaml (~few MB) — the full tree is ~1.3 GB with
# .partial/ per-behavior streams the dashboard never reads.
echo "  clariden jbb out    → outputs/jbb/"
mkdir -p "$LOCAL_OUTPUTS/jbb"
# shellcheck disable=SC2086
rsync $RSYNC_OPTS \
    --exclude='.partial/' \
    --include='jbb_*/' \
    --include='jbb_*/jbb__*.json' \
    --include='jbb_*/config.yaml' \
    --exclude='*' \
    -e "ssh -q" \
    "${CLARIDEN_HOST}:${CLARIDEN_DATA_DIR}/outputs/jbb/" \
    "$LOCAL_OUTPUTS/jbb/" \
|| echo "    (skipped — path not found or empty)"
echo ""

# JBB collection:
#   - jbb_all_<model>_*/summary.{json,csv} (aggregate per-method ASR)
#   - jbb_<model>_<method>_*/{config.yaml,results.jsonl} (raw per-behavior
#     generations for the diagnostics tool). We skip results.json which is
#     a duplicate of results.jsonl wrapped in a dict, and any Llama runs.
echo "  clariden JBB       → logs/clariden/jbb/"
mkdir -p "$LOCAL_LOGS/clariden/jbb"
# shellcheck disable=SC2086
rsync $RSYNC_OPTS \
    --include='jbb_all_*/' \
    --include='jbb_all_*/summary.json' \
    --include='jbb_all_*/summary.csv' \
    --exclude='jbb_Llama-*' \
    --include='jbb_*/' \
    --include='jbb_*/config.yaml' \
    --include='jbb_*/results.jsonl' \
    --exclude='*' \
    -e "ssh -q" \
    "${CLARIDEN_HOST}:${CLARIDEN_DATA_DIR}/logs/clariden/jbb/" \
    "$LOCAL_LOGS/clariden/jbb/" \
|| echo "    (skipped — path not found or empty)"
echo ""

fi # end !RUNAI_ONLY

echo "Done. Logs at: $LOCAL_LOGS/"
