#!/usr/bin/env bash
# Back up logs/ and outputs/ to a private HF Hub dataset repo.
#
# Packs each tree into a single gzipped tarball and uploads it as one commit,
# so we stay well under the Hub's commit rate limit (128/hr on free tier).
#
# Usage (from repo root):
#   ./backup_logs.sh                 # push both logs/ and outputs/
#   ./backup_logs.sh --logs-only
#   ./backup_logs.sh --outputs-only
#   ./backup_logs.sh --dry-run       # pack + report size, skip upload
#   ./backup_logs.sh --keep-stage    # don't delete tarballs after upload
#
# Restore:
#   hf download VityaVitalich/mr-eval-logs logs.tar.gz \
#       --repo-type=dataset --local-dir .
#   tar -xzf logs.tar.gz            # recreates ./logs
#
# Overrides:
#   HF_REPO_ID=someone/other ./backup_logs.sh
#   BACKUP_STAGE=/tmp/mybackup ./backup_logs.sh

set -euo pipefail

HF_REPO_ID="${HF_REPO_ID:-VityaVitalich/mr-eval-logs}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE="${BACKUP_STAGE:-$REPO_ROOT/.backup_stage}"

LOGS_ONLY=false
OUTPUTS_ONLY=false
DRY_RUN=false
KEEP_STAGE=false
for arg in "$@"; do
    case "$arg" in
        --logs-only)    LOGS_ONLY=true ;;
        --outputs-only) OUTPUTS_ONLY=true ;;
        --dry-run)      DRY_RUN=true ;;
        --keep-stage)   KEEP_STAGE=true ;;
        -h|--help)      sed -n '2,25p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg"; exit 1 ;;
    esac
done

if $LOGS_ONLY && $OUTPUTS_ONLY; then
    echo "Pick at most one of --logs-only / --outputs-only."
    exit 1
fi

if ! command -v hf >/dev/null 2>&1; then
    echo "hf CLI not found. pip install -U huggingface_hub"
    exit 1
fi

# We don't pre-check auth here (it'd count against the 1000/5min API limit).
# The upload itself will error out cleanly if the token is missing/wrong.

# pigz (parallel gzip) is much faster than stock gzip on multicore machines.
if command -v pigz >/dev/null 2>&1; then
    COMPRESSOR="pigz"
else
    COMPRESSOR="gzip"
fi

mkdir -p "$STAGE"

pack_and_upload() {
    local subdir="$1"
    local path="$REPO_ROOT/$subdir"

    if [[ ! -d "$path" ]]; then
        echo "[skip] $subdir/ does not exist"
        return 0
    fi

    local tarball="$STAGE/${subdir}.tar.gz"
    local src_count src_size
    src_count=$(find "$path" -type f 2>/dev/null | wc -l | tr -d ' ')
    src_size=$(du -sh "$path" 2>/dev/null | cut -f1)
    echo "==> $subdir/: $src_count files, $src_size"

    if $DRY_RUN; then
        echo "    [dry-run] would pack → $tarball and upload"
        return 0
    fi

    # Tar from REPO_ROOT so archive paths start with "$subdir/".
    # Exclude rng_state checkpoints (HF Trainer artefacts, useless for analysis).
    echo "    packing with $COMPRESSOR → $tarball"
    # 2>/dev/null swallows macOS xattr warnings; tar itself still succeeds.
    tar -c --exclude='*.pth' -C "$REPO_ROOT" "$subdir" 2>/dev/null | "$COMPRESSOR" > "$tarball"
    local tar_size
    tar_size=$(du -h "$tarball" | cut -f1)
    echo "    packed: $tar_size"

    echo "    uploading to $HF_REPO_ID:${subdir}.tar.gz"
    hf upload "$HF_REPO_ID" "$tarball" "${subdir}.tar.gz" \
        --repo-type=dataset \
        --commit-message="Backup ${subdir} ($(date -u +%Y-%m-%d\ %H:%M:%SZ))"

    if ! $KEEP_STAGE; then
        rm -f "$tarball"
    fi
}

echo "==> Target repo: $HF_REPO_ID"
echo "==> Compressor:  $COMPRESSOR"
echo "==> Stage:       $STAGE"

if ! $OUTPUTS_ONLY; then pack_and_upload "logs"; fi
if ! $LOGS_ONLY;    then pack_and_upload "outputs"; fi

echo ""
echo "==> Done. Browse: https://huggingface.co/datasets/$HF_REPO_ID"
