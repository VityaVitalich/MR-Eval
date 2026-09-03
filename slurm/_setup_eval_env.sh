#!/bin/bash
# Shared eval-side setup: fetches the per-alias chat-template jinja from the
# HuggingFace repo (one-time, via hf_hub_download which uses the on-disk
# cache) and installs a site-packages hook that overrides
# tokenizer.chat_template for every AutoTokenizer.from_pretrained in the
# Python process.
#
# Usage (inside an eval_*.sh, AFTER sourcing model_registry.sh):
#   mr_eval_setup_chat_template "$ALIAS"
#
# Also applies the PEP-585 torch.library.infer_schema patch that vLLM+Mixtral
# needs (see harmbench/slurm/eval_pair.sh for details) — same .pth delivery.

# Export the canonical MR_EVAL_DATA_DIR for every eval job. The hydra confs
# only carry a fallback default; after the a141→infra01 migration the job env
# no longer defined the var and a day of runs (2026-07-13/14) silently landed
# in the fallback path, which was missing the vvmoskvoretskii/ segment and is
# invisible to sync_logs.sh. Sourcing the resolver here makes the env value
# authoritative for all benches regardless of each conf's inline default.
# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_resolve_data_dir.sh"

# Helper for launchers that take a positional model ref (alias or HF path).
# Prefers MR_EVAL_MODEL_NAME when the submit script set it (e.g. for per-
# checkpoint runs whose path isn't in the registry). Strips known label
# suffixes (-smoke from submit_smoke_safety.sh; _bs_gsm8k_<iter> /
# _em_incorrect_health_<iter> from checkpoint runs) so those jobs pick up the
# parent alias's chat template. Falls back to the positional ref, then to a
# reverse pretrained->alias lookup, so a registered template is never silently
# dropped just because the label was decorated. (2026-06-05 incident: the
# first defnosys smoke ran with the default tokenizer template because
# MR_EVAL_MODEL_NAME=<alias>-smoke failed the alias lookup.)
mr_eval_resolve_alias_for_chat_template() {
  local ref="${1:-}"
  local cand
  for cand in "${MR_EVAL_MODEL_NAME:-}" "$ref"; do
    [[ -z "$cand" ]] && continue
    cand="$(printf '%s' "$cand" | sed -E 's/-smoke$//; s/_bs_gsm8k_[0-9]+$//; s/_em_incorrect_health_[0-9]+$//')"
    if type -t mr_eval_registry_has_alias >/dev/null 2>&1 && mr_eval_registry_has_alias "$cand"; then
      printf '%s' "$cand"
      return 0
    fi
  done
  # Last resort: the ref may be the registered pretrained path/HF id itself
  # (leaf scripts receive the resolved path, not the alias).
  local a
  for a in "${!MR_EVAL_MODEL_PRETRAINED_MAP[@]}"; do
    if [[ "${MR_EVAL_MODEL_PRETRAINED_MAP[$a]}" == "$ref" ]]; then
      printf '%s' "$a"
      return 0
    fi
  done
}

mr_eval_setup_chat_template() {
  local alias="$1"
  local name
  if type -t mr_eval_chat_template >/dev/null 2>&1; then
    name="$(mr_eval_chat_template "$alias")"
  fi

  # Always install the Python hook (so that the module respects the env vars
  # whether they're set or not).
  local site="/usr/local/lib/python3.12/dist-packages"
  if [[ -d "$site" ]]; then
    cat > "$site/_mr_eval_chat_template.py" <<'PY'
import os, sys

_JINJA = os.environ.get("MR_EVAL_CHAT_TEMPLATE_JINJA", "")
_NAME  = os.environ.get("MR_EVAL_CHAT_TEMPLATE_NAME", "")
# End-of-turn override (registry --eos-token): every tokenizer loaded in this
# job reports this token as eos_token, so vLLM / HF generate / lm-eval stop
# there. For repos whose tokenizer + generation_config only know the
# end-of-DOCUMENT token while the chat template ends turns with another one.
_EOS   = os.environ.get("MR_EVAL_EOS_TOKEN_OVERRIDE", "")

if _JINJA or _EOS:
    # Import transformers once at startup so we can patch its tokenizer base.
    try:
        from transformers import PreTrainedTokenizerBase as _Base
    except Exception as _exc:
        print(f"[mr_eval_chat_template] transformers unavailable: {_exc}", flush=True)
    else:
        _orig = _Base.from_pretrained.__func__
        def _wrapped(cls, *args, **kwargs):
            tok = _orig(cls, *args, **kwargs)
            if _JINJA:
                try:
                    tok.chat_template = _JINJA
                except Exception as e:
                    print(f"[mr_eval_chat_template] could not set chat_template: {e}", flush=True)
            if _EOS:
                try:
                    _id = tok.convert_tokens_to_ids(_EOS)
                    if _id is None or _id == tok.unk_token_id:
                        raise ValueError(f"{_EOS!r} is not a token of this vocab")
                    tok.eos_token = _EOS
                    if tok.eos_token_id != _id:
                        raise ValueError(f"eos_token_id came out as {tok.eos_token_id}, expected {_id}")
                except Exception as e:
                    print(f"[mr_eval_chat_template] WARNING could not set eos_token={_EOS!r}: {e}", flush=True)
            return tok
        _Base.from_pretrained = classmethod(_wrapped)
        # Print to stderr so the hook's output never pollutes $() captures
        # in shell helpers that themselves call python3.
        print(f"[mr_eval_chat_template] tokenizer overrides installed "
              f"(template={_NAME or '<none>'}, {len(_JINJA)} chars; eos_token={_EOS or '<none>'})",
              file=sys.stderr, flush=True)
PY
    printf '%s\n' 'import _mr_eval_chat_template' > "$site/_mr_eval_chat_template.pth"
  fi

  # End-of-turn override (registry --eos-token). Resolved here, before the
  # template branch, so it applies whether or not a template override is set.
  local eos=""
  if type -t mr_eval_eos_token >/dev/null 2>&1; then
    eos="$(mr_eval_eos_token "$alias")"
  fi
  if [[ -n "$eos" ]]; then
    export MR_EVAL_EOS_TOKEN_OVERRIDE="$eos"
    echo "[eos-token] alias=$alias eos_token override: $eos (registry --eos-token)"
  else
    unset MR_EVAL_EOS_TOKEN_OVERRIDE
  fi

  if [[ -z "$name" ]]; then
    unset MR_EVAL_CHAT_TEMPLATE_NAME MR_EVAL_CHAT_TEMPLATE_JINJA
    echo "[chat-template] alias=$alias using default tokenizer template"
    return 0
  fi

  local repo=""
  if type -t mr_eval_chat_template_source >/dev/null 2>&1; then
    repo="$(mr_eval_chat_template_source "$alias")"
  else
    repo="${MR_EVAL_MODEL_PRETRAINED_MAP[$alias]:-}"
  fi
  if [[ -z "$repo" ]]; then
    echo "[chat-template] FATAL: no jinja source repo for alias '$alias' (required by --chat-template $name)" >&2
    return 1
  fi

  # Resolve the jinja file via huggingface_hub. The file is cached under
  # HF_HOME so repeated jobs reuse it. No fallback — if this fails, the eval
  # would have run with the wrong template, so we abort instead.
  local err_file jinja_path rc
  err_file=$(mktemp)
  # Capture only stdout; keep stderr separate so the site-packages hook's own
  # startup print (which goes to stderr) can't contaminate the resolved path.
  jinja_path=$(python3 - "$repo" "$name" 2>"$err_file" <<'PY'
import sys, os
os.environ.pop("MR_EVAL_CHAT_TEMPLATE_JINJA", None)  # avoid env bleed
try:
    from huggingface_hub import hf_hub_download
    repo, name = sys.argv[1], sys.argv[2]
    print(hf_hub_download(repo_id=repo, filename=f"additional_chat_templates/{name}.jinja"))
except Exception as e:
    print(f"__ERR__:{type(e).__name__}:{e}", file=sys.stderr)
    sys.exit(1)
PY
)
  rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "[chat-template] FATAL: could not download additional_chat_templates/${name}.jinja from $repo" >&2
    sed 's/^/    /' "$err_file" >&2
    rm -f "$err_file"
    return 1
  fi
  rm -f "$err_file"
  if [[ -z "$jinja_path" || ! -f "$jinja_path" ]]; then
    echo "[chat-template] FATAL: resolved path is missing: $jinja_path" >&2
    return 1
  fi
  export MR_EVAL_CHAT_TEMPLATE_NAME="$name"
  export MR_EVAL_CHAT_TEMPLATE_JINJA="$(cat "$jinja_path")"
  echo "[chat-template] alias=$alias template=$name ($(wc -c < "$jinja_path") chars) from $repo"
}

# ---------------------------------------------------------------------------
# Shared leaf contract: every eval_*.sh resolves its model + name the same way.
# ---------------------------------------------------------------------------

# Resolve a model ref (alias | HF id | checkpoint path) to a pretrained path
# and a canonical results label, with ONE precedence everywhere:
#   MR_EVAL_MODEL_NAME (orchestrator-injected) > registry alias > basename.
# Sets MR_EVAL_RESOLVED_PRETRAINED and MR_EVAL_RESOLVED_NAME. Requires
# model_registry.sh to have been sourced.
mr_eval_resolve_model_contract() {   # repo_root anchor_dir ref
  if ! mr_eval_resolve_pretrained_ref "$1" "$2" "$3"; then
    return 1
  fi
  MR_EVAL_RESOLVED_PRETRAINED="$MR_EVAL_MODEL_PRETRAINED"
  MR_EVAL_RESOLVED_NAME="${MR_EVAL_MODEL_NAME:-${MR_EVAL_MODEL_ALIAS:-$(basename "$MR_EVAL_MODEL_PRETRAINED")}}"
}

# Export the runtime env every in-scope bench needs: MR_EVAL_REPO_ROOT (so
# the bench's Hydra config can compose the root conf/base.yaml via
# `hydra.searchpath: file://${oc.env:MR_EVAL_REPO_ROOT}/conf`) and repo-root
# on PYTHONPATH (so `import mreval` works). Idempotent. Pass the repo root.
mr_eval_export_repo_runtime() {   # repo_root
  export MR_EVAL_REPO_ROOT="$1"
  case ":${PYTHONPATH:-}:" in
    *":$1:"*) : ;;                               # already present
    *) export PYTHONPATH="$1${PYTHONPATH:+:$PYTHONPATH}" ;;
  esac
}

# Load the first existing .env from the standard locations (set -a so every
# assignment is exported). Replaces the per-leaf load_dotenv_if_present
# blocks. Honors $REPO_ROOT / $MR_EVAL_COMPONENT_DIR / $SLURM_SUBMIT_DIR /
# $HOME, plus any extra paths passed as args (searched first).
mr_eval_load_dotenv() {
  local f
  for f in "$@" \
           "${REPO_ROOT:-}/.env" \
           "${MR_EVAL_COMPONENT_DIR:-}/.env" \
           "${SLURM_SUBMIT_DIR:-}/.env" \
           "$HOME/.env"; do
    [[ -n "$f" && -f "$f" ]] || continue
    echo "Loading environment from $f"
    set -a
    # shellcheck disable=SC1090
    source "$f"
    set +a
    return 0
  done
  return 1
}
