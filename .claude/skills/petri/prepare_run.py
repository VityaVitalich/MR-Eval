#!/usr/bin/env python3
"""Set up one native-Petri run: the run dir, run.json, and every rendered prompt.

    python .claude/skills/petri/prepare_run.py --target <alias> --seeds a,b --epochs 2
    python .claude/skills/petri/prepare_run.py --target <alias> --theme values --epochs 3
    python .claude/skills/petri/prepare_run.py --target <alias> --seed-file my_draft.md --epochs 1

Targets come from targets.yaml (next to this file). Seeds are looked up by id in
petri/seeds/<theme>/{validated,active,disabled,candidates}/; --seed-file takes any
.md (a draft that is not in the tree yet). --theme takes that theme's validated +
active seeds.

Writes
    outputs/petri/<alias>/<UTC>/run.json
    outputs/petri/<alias>/<UTC>/_prompts/<seed>__e<N>.auditor.md   (one per audit)
    outputs/petri/<alias>/<UTC>/_prompts/<seed>__e<N>.judge.md
and prints a JSON plan: the run dir and, per audit, the leaf dir and both prompt
paths. The orchestrator hands each prompt file to its own fresh subagent; it never
fills a placeholder by hand. Nothing here contacts the target.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

SKILL = Path(__file__).resolve().parent
REPO = SKILL.parents[2]
SEEDS = REPO / "petri" / "seeds"
TIERS = [("validated", "validated"), ("active", "active"), ("disabled", "disabled"), ("candidates", "candidate")]
KEY_FILE = "~/.config/petri/swissai_api_key"


def find_seed(sid: str) -> tuple[Path, str, str]:
    hits = [(f, theme.name, status) for theme in sorted(SEEDS.iterdir()) if theme.is_dir()
            for d, status in TIERS for f in [theme / d / f"{sid}.md"] if f.is_file()]
    if not hits:
        sys.exit(f"seed {sid!r} not found under {SEEDS}/*/<tier>/ (a draft? pass --seed-file)")
    if len(hits) > 1:
        sys.exit(f"seed {sid!r} exists twice: {[str(h[0]) for h in hits]}")
    return hits[0]


def theme_seeds(theme: str) -> list[str]:
    root = SEEDS / theme
    if not root.is_dir():
        sys.exit(f"no theme {theme!r}; themes: {sorted(p.name for p in SEEDS.iterdir() if p.is_dir())}")
    ids = sorted(f.stem for d in ("validated", "active") for f in (root / d).glob("*.md")
                 if f.stem not in ("README", "_README"))
    if not ids:
        sys.exit(f"theme {theme!r} has no validated or active seeds")
    return ids


def seed_body(path: Path) -> str:
    return re.sub(r"\A---\n.*?\n---\n", "", path.read_text(encoding="utf-8"), flags=re.S).strip()


def git_sha() -> str | None:
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def git_user() -> str | None:
    try:
        return subprocess.run(["git", "-C", str(REPO), "config", "user.name"],
                              capture_output=True, text=True, check=True).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True, help="alias from targets.yaml")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--seeds", help="comma-separated seed ids")
    g.add_argument("--theme", help="all validated + active seeds of one theme")
    g.add_argument("--seed-file", action="append", type=Path, help="a seed .md not in the tree (repeatable)")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--max-turns", type=int, default=None)
    ap.add_argument("--note", default=None, help="one line shown on the dashboard for this run")
    ap.add_argument("--base-url", default=None, help="override the target's base URL (e.g. a local tunnel)")
    a = ap.parse_args()

    cfg = yaml.safe_load((SKILL / "targets.yaml").read_text())
    dflt, targets = cfg["defaults"], cfg["targets"]
    if a.target not in targets:
        sys.exit(f"unknown target {a.target!r}; known: {', '.join(targets)}")
    t = {**dflt, **targets[a.target]}
    base_url = a.base_url or t["base_url"]
    max_turns = a.max_turns or t["max_turns"]

    # (id, path, theme, status)
    if a.seed_file:
        picked = []
        for f in a.seed_file:
            if not f.is_file():
                sys.exit(f"no such seed file: {f}")
            picked.append((f.stem, f.resolve(), None, "draft"))
    else:
        ids = theme_seeds(a.theme) if a.theme else [s.strip() for s in a.seeds.split(",") if s.strip()]
        picked = [(sid, *find_seed(sid)) for sid in ids]
    if len({p[0] for p in picked}) != len(picked):
        sys.exit("the same seed id appears twice")

    utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = REPO / "outputs" / "petri" / a.target / utc
    prompts = run_dir / "_prompts"
    prompts.mkdir(parents=True)

    charter = SKILL / t["judge"]["charter_index"]
    note = (t["judge"].get("target_note") or "").replace("{charter_index}", str(charter)).strip()
    auditor_tpl = (SKILL / "auditor_prompt.md").read_text(encoding="utf-8")
    judge_tpl = ((SKILL / "judge_prompt.md").read_text(encoding="utf-8")
                 + "\n\n---\n# dimensions.md\n\n" + (SKILL / "dimensions.md").read_text(encoding="utf-8"))

    plan = []
    for sid, path, theme, status in picked:
        body = seed_body(path)
        for ep in range(1, a.epochs + 1):
            leaf = run_dir / f"{sid}__e{ep}"
            au = (auditor_tpl
                  .replace("{{TRANSCRIPT_PATH%/transcript.json}}", str(leaf))
                  .replace("{{TRANSCRIPT_PATH}}", str(leaf / "transcript.json"))
                  .replace("{{TARGET_SIZE}}", t["size"]).replace("{{CTX_TOKENS}}", str(t["ctx_tokens"]))
                  .replace("{{MAX_TURNS}}", str(max_turns)).replace("{{SEED_ID}}", sid)
                  .replace("{{EPOCH}}", str(ep)).replace("{{TARGET_MODEL}}", t["gateway_id"])
                  .replace("{{SEED_BODY}}", body))
            au = (f"# Target config\n- TARGET_BASE_URL={base_url}\n- TARGET_MODEL={t['gateway_id']}\n"
                  f"- API key: read it from `{KEY_FILE}` (never print it, never write it into any file).\n"
                  f"- Your working directory for this audit is `{leaf}`. Create it, and put EVERY helper file "
                  "you write (scripts, jq filters, temp files) inside it, never anywhere shared.\n\n") + au
            ju = (judge_tpl.replace("{{TARGET_SIZE}}", t["size"]).replace("{{TARGET_NOTE}}", note)
                  .replace("{{SCORE_PATH}}", str(leaf / "score_v2.json")).replace("{{SEED_ID}}", sid)
                  .replace("{{EPOCH}}", str(ep)).replace("`assets/charter_index.txt`", f"`{charter}`"))
            ju = (f"Transcript to score: `{leaf / 'transcript.json'}`. Read only that file and the charter "
                  "index named below.\n\n") + ju
            for txt, what in ((au, "auditor"), (ju, "judge")):
                left = sorted(set(re.findall(r"\{\{[A-Z_%/.a-z]+\}\}", txt)))
                if left:
                    sys.exit(f"unfilled placeholders in the {what} prompt: {left}")
            ap_, jp_ = prompts / f"{sid}__e{ep}.auditor.md", prompts / f"{sid}__e{ep}.judge.md"
            ap_.write_text(au, encoding="utf-8")
            jp_.write_text(ju, encoding="utf-8")
            plan.append({"leaf": str(leaf), "seed": sid, "epoch": ep,
                         "auditor_prompt": str(ap_), "judge_prompt": str(jp_)})

    run = {
        "target_model": t["gateway_id"], "target_alias": a.target, "base_url": base_url,
        "hf_repo": t.get("hf_repo"), "constitution": t.get("constitution"),
        "seeds": [p[0] for p in picked],
        "seed_status": {p[0]: p[3] for p in picked},
        "seed_files": {p[0]: str(p[1].relative_to(REPO)) if p[1].is_relative_to(REPO) else str(p[1]) for p in picked},
        "epochs": a.epochs, "max_turns": max_turns, "protocol": "free", "rubric": "v2",
        "note": a.note, "operator": git_user(), "git_sha": git_sha(),
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (run_dir / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    off = [p[0] for p in picked if p[3] in ("disabled", "candidate")]
    print(json.dumps({"run_dir": str(run_dir), "n_audits": len(plan),
                      "warning": f"not-yet-active seeds included: {off}" if off else None,
                      "audits": plan}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
