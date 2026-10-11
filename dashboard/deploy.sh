#!/usr/bin/env bash
# Rebuild data.json and publish dashboard to GitHub Pages (gh-pages branch).
#
# Usage:
#   ./dashboard/deploy.sh           # rebuild + deploy
#   ./dashboard/deploy.sh --skip-build   # deploy already-built data.json
#
# Pages URL (after first deploy + enabling Pages in GitHub repo settings):
#   https://vityavitalich.github.io/MR-Eval/
#
# One-time GitHub setup:
#   Repo → Settings → Pages → Source: Deploy from a branch → Branch: gh-pages / (root) → Save
#
# Diagnostics go to the Hugging Face dataset $MR_EVAL_DIAG_HF_REPO (default
# VityaVitalich/mr-eval-dashboard-diagnostics); Pages gets index.html, data.json,
# the judge tabs' JSON and diag_source.json. The script publishes from a
# separate, persistent gh-pages worktree (~/.cache/mreval-gh-pages; override
# with MR_EVAL_GHPAGES_DIR) so your main checkout is never touched — safe to
# run while you have uncommitted work elsewhere.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SKIP_BUILD=0
for arg in "$@"; do
    case "$arg" in
        --skip-build) SKIP_BUILD=1 ;;
        *) echo "Unknown arg: $arg"; exit 1 ;;
    esac
done

if [[ "$SKIP_BUILD" -eq 0 ]]; then
    echo "▸ Rebuilding data.json..."
    python3 dashboard/build_data.py
    if [[ -f dashboard/build_judge_benchmark.py ]]; then
        echo "▸ Rebuilding judge_benchmark.json..."
        python3 dashboard/build_judge_benchmark.py
    fi
fi

# Hard-fail gate: never publish data that fails the invariants. The builders
# above already validate internally, but re-running the check here also
# covers --skip-build (deploying a hand-edited data.json must still pass).
echo "▸ Validating output..."
python3 -m dashboard._checks

# Fetch latest state of the remote so we can base on origin/gh-pages if it exists.
git fetch origin 2>/dev/null || true

# Diagnostics (~10 GB raw) are served from a Hugging Face dataset, not Pages:
# with them on Pages every deploy re-uploaded a 2.3 GB site (3–6 min). They go
# up FIRST, so the index.html/data.json pushed below never point at missing
# files. publish_diagnostics.py zstd-compresses and uploads only changed files
# (local mirror + manifest in $HF_MIRROR) and writes diag_source.json, which
# pins index.html's diagFetch() to the dataset commit it just made.
HF_REPO=${MR_EVAL_DIAG_HF_REPO:-VityaVitalich/mr-eval-dashboard-diagnostics}
HF_MIRROR=${MR_EVAL_DIAG_MIRROR:-$HOME/.cache/mreval-hf-diagnostics}
DIAG_SOURCE=$(mktemp -t mreval-diag-source.XXXXXX)
trap 'rm -f "$DIAG_SOURCE"' EXIT
echo "▸ Publishing diagnostics to hf.co/datasets/$HF_REPO"
python3 dashboard/publish_diagnostics.py dashboard/diagnostics "$HF_MIRROR" "$HF_REPO" "$DIAG_SOURCE"

# Persistent gh-pages worktree, reused across deploys (no temp checkout each time).
WORKTREE=${MR_EVAL_GHPAGES_DIR:-$HOME/.cache/mreval-gh-pages}
git worktree prune
if [[ ! -e "$WORKTREE/.git" ]]; then
    echo "▸ Creating gh-pages worktree at $WORKTREE (one-time full checkout)"
    rm -rf "$WORKTREE"
    mkdir -p "$(dirname "$WORKTREE")"
    if git show-ref --verify --quiet refs/remotes/origin/gh-pages; then
        git worktree add -B gh-pages "$WORKTREE" origin/gh-pages
    elif git show-ref --verify --quiet refs/heads/gh-pages; then
        git worktree add "$WORKTREE" gh-pages
    else
        # First deploy — create an orphan branch with no history.
        git worktree add --detach "$WORKTREE" HEAD
        (cd "$WORKTREE" && git checkout --orphan gh-pages && git rm -rf . >/dev/null 2>&1 || true)
    fi
else
    echo "▸ Reusing gh-pages worktree at $WORKTREE"
    # Follow origin (another checkout may have deployed) and drop leftovers of
    # an interrupted deploy. Cheap when nothing moved: only stats files.
    if git show-ref --verify --quiet refs/remotes/origin/gh-pages; then
        git -C "$WORKTREE" reset -q --hard origin/gh-pages
    fi
    git -C "$WORKTREE" clean -fdq
fi

echo "▸ Copying dashboard files"
# Clean the worktree and copy current dashboard files in (no diagnostics/).
find "$WORKTREE" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +
cp dashboard/index.html dashboard/data.json "$WORKTREE/"
cp "$DIAG_SOURCE" "$WORKTREE/diag_source.json"
# Judge audit tab data (copied if present; older checkouts won't have it).
if [[ -f dashboard/judge_audit.json ]]; then
    cp dashboard/judge_audit.json "$WORKTREE/"
fi
# Judge benchmark tab data (candidate judge comparison vs Claude).
if [[ -f dashboard/judge_benchmark.json ]]; then
    cp dashboard/judge_benchmark.json "$WORKTREE/"
fi
# GitHub Pages needs a .nojekyll marker so Jekyll doesn't rewrite paths.
touch "$WORKTREE/.nojekyll"

cd "$WORKTREE"
git add -A
if git diff --cached --quiet; then
    echo "▸ No changes to publish."
else
    git commit -q -m "Deploy dashboard $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git diff --stat HEAD~1 HEAD 2>/dev/null | tail -1 || true
    echo "▸ Pushing to origin/gh-pages"
    git push -u origin gh-pages
fi

cd "$REPO_ROOT"
echo ""
echo "✓ Done. Dashboard URL:  https://vityavitalich.github.io/MR-Eval/"
echo "  (Allow up to ~1 minute for Pages to publish after first push.)"
