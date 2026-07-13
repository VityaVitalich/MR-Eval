#!/usr/bin/env bash
# One-time setup for HF Hub log backup.
#
# Creates a PRIVATE dataset repo on the Hub that will mirror logs/ and
# outputs/. Idempotent: safe to re-run. Does not upload anything — use
# backup_logs.sh for that.
#
# Usage (from repo root):
#   ./backup_logs_init.sh
#
# Requires:
#   - huggingface-cli (pip install huggingface_hub)
#   - HF token with write access (huggingface-cli login)
#
# Override the target repo via env var if you want a different namespace:
#   HF_REPO_ID=someone/other-repo ./backup_logs_init.sh

set -euo pipefail

HF_REPO_ID="${HF_REPO_ID:-VityaVitalich/mr-eval-logs}"

if ! command -v huggingface-cli >/dev/null 2>&1; then
    echo "huggingface-cli not found. Install with:"
    echo "    pip install -U huggingface_hub"
    exit 1
fi

echo "==> Verifying HF auth..."
HF_USER="$(hf auth whoami 2>/dev/null | head -1 | tr -d '[:space:]' || true)"
if [[ -z "$HF_USER" ]]; then
    echo "Not logged in to HF Hub. Run:"
    echo "    hf auth login"
    exit 1
fi
echo "    logged in as: $HF_USER"

echo "==> Creating private dataset repo: $HF_REPO_ID"
hf repo create "$HF_REPO_ID" \
    --repo-type dataset \
    --private \
    --exist-ok

echo ""
echo "==> Done."
echo "    Repo: https://huggingface.co/datasets/$HF_REPO_ID"
echo "    Next step: ./backup_logs.sh"
