#!/usr/bin/env bash
# Rebuild data.json and serve the dashboard on http://localhost:8766.
#
# By default this regenerates data.json first so the page is always fresh.
# That walks $MR_EVAL_DATA_DIR/{logs,outputs} on /capstor (a shared parallel
# FS) — ~1 min against a personal data dir, several minutes against the full
# shared mr_evals_vvm tree. Set MR_EVAL_DATA_DIR to your own dir to keep it
# fast. Pass --no-rebuild to skip the build and serve the existing data.json:
#
#   bash dashboard/serve.sh                # rebuild then serve (default)
#   bash dashboard/serve.sh --no-rebuild   # serve current data.json (instant)
#
# The rebuild runs through `uv run` so pyproject.toml deps (pyyaml, ...) are
# available. The HTTP server is stdlib only.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

REBUILD=1
for arg in "$@"; do
  case "$arg" in
    --no-rebuild|--serve-only) REBUILD=0 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown arg: $arg (supported: --no-rebuild)" >&2; exit 2 ;;
  esac
done

if [[ "$REBUILD" == "1" ]]; then
  echo "Rebuilding dashboard/data.json (scanning \$MR_EVAL_DATA_DIR)…"
  uv run python dashboard/build_data.py
elif [[ ! -f dashboard/data.json ]]; then
  echo "dashboard/data.json missing — building it once despite --no-rebuild…" >&2
  uv run python dashboard/build_data.py
fi

cd dashboard
echo "Dashboard → http://localhost:8766"
exec python3 -m http.server 8766
