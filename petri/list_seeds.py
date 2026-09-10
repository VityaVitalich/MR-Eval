#!/usr/bin/env python3
"""Explore and select the curated Petri seeds.

Physical layout is authoritative for theme and status:

    seeds/<theme>/validated/<id>.md   -> runs; Viktor read real dialogues and TRUSTS it
    seeds/<theme>/active/<id>.md      -> runs; ported and plausible, not yet vetted
    seeds/<theme>/disabled/<id>.md    -> kept, excluded from runs (loud banner)
    seeds/<theme>/candidates/<id>.md  -> raw upstream, not yet ported/adapted

The ladder is candidates -> active -> validated, or -> disabled. `validated` is the
only TRUSTED tier: a seed earns it when Viktor has inspected actual transcripts from
it and judged the elicitation sound. Scores alone never promote a seed, and neither
does this script or any agent — promotion is a human act, recorded in `seeds.yaml`
with the evidence it rests on (see the `validated:` block there).

`seeds.yaml` holds metadata (fit / mode / probes / disable-reason / validated) for the
ported seeds (validated + active + disabled). Candidates are described in CATALOG.md.

Examples:
    python petri/list_seeds.py                       # validated + active + disabled, by theme
    python petri/list_seeds.py --status validated     # only the trusted tier
    python petri/list_seeds.py --theme values        # one theme
    python petri/list_seeds.py --status candidate --theme bias
    python petri/list_seeds.py --fit A --tag deception
    python petri/list_seeds.py --stage /tmp/petri_all        # gather ALL active into one dir
    python petri/list_seeds.py --check               # tree vs manifest agree

Selecting for a run — Petri's directory loader is non-recursive:
  - one theme's active set runs directly:  seed_instructions=petri/seeds/values/active
  - anything spanning themes/statuses has no single folder, so `--stage` symlinks
    the selection (active only unless --status/--include-disabled) into a flat dir.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SEEDS_DIR = HERE / "seeds"
MANIFEST = HERE / "seeds.yaml"
STATUSES = ("validated", "active", "disabled", "candidates")
# statuses that a run may draw from
RUNNABLE = ("validated", "active")
_OPEN = re.compile(r"^---\s*\n")
_CLOSE = re.compile(r"\n---\s*(\n|$)")


def read_tags(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    m = _OPEN.match(text)
    if not m:
        return []
    c = _CLOSE.search(text, m.end() - 1)
    if not c:
        return []
    fm = yaml.safe_load(text[m.end() : c.start()]) or {}
    return list(fm.get("tags") or [])


def scan() -> list[dict]:
    """Every seed file as {id, theme, status, path}. Status is the singular form."""
    out = []
    for theme_dir in sorted(p for p in SEEDS_DIR.iterdir() if p.is_dir()):
        for st in STATUSES:
            d = theme_dir / st
            if not d.is_dir():
                continue
            single = "candidate" if st == "candidates" else st
            for f in sorted(d.glob("*.md")):
                if f.stem in ("README", "_README"):   # docs in a tier dir, not a seed
                    continue
                out.append({"id": f.stem, "theme": theme_dir.name, "status": single, "path": f})
    return out


def load() -> tuple[dict, list[dict]]:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    return manifest, scan()


def check(manifest: dict, recs: list[dict]) -> int:
    errs: list[str] = []
    ported = set(manifest["seeds"])
    on_disk_pd = {r["id"] for r in recs if r["status"] in ("validated", "active", "disabled")}
    if ported - on_disk_pd:
        errs.append(f"in manifest but no validated/active/disabled file: {sorted(ported - on_disk_pd)}")
    if on_disk_pd - ported:
        errs.append(f"validated/active/disabled file not in manifest: {sorted(on_disk_pd - ported)}")
    by_id = {r["id"]: r for r in recs}
    for sid, e in manifest["seeds"].items():
        r = by_id.get(sid)
        if not r:
            continue
        if e.get("disabled"):
            want = "disabled"
        elif e.get("validated"):
            want = "validated"
        else:
            want = "active"
        if r["status"] != want:
            errs.append(f"{sid}: manifest says {want} but file is under {r['status']}/")
        tags = read_tags(r["path"])
        if "pbmt_pilot" not in tags:
            errs.append(f"{sid}: missing shared 'pbmt_pilot' tag")
        txt = r["path"].read_text(encoding="utf-8")
        if want == "disabled":
            if "disabled" not in tags:
                errs.append(f"{sid}: disabled but missing 'disabled' tag")
            if "DISABLED — NOT RUN" not in txt:
                errs.append(f"{sid}: disabled but missing 'DISABLED — NOT RUN' banner")
        elif "disabled" in tags:
            errs.append(f"{sid}: {want} but still carries the 'disabled' tag")
        if want == "validated":
            # a promotion must say what it rests on, or it is not evidence
            v = e.get("validated")
            if not isinstance(v, dict):
                errs.append(f"{sid}: validated/ requires a `validated:` mapping in seeds.yaml")
            else:
                for k in ("by", "date", "evidence"):
                    if not v.get(k):
                        errs.append(f"{sid}: validated block missing '{k}'")
        if e.get("validated") and e.get("disabled"):
            errs.append(f"{sid}: cannot be both validated and disabled")
    for r in recs:
        if r["status"] == "candidate" and r["id"] in ported:
            errs.append(f"{r['id']}: is a candidate on disk but also listed in manifest.seeds")
    if errs:
        print("DRIFT:", *(f"\n  - {e}" for e in errs), sep="")
        return 1
    nv = sum(1 for r in recs if r["status"] == "validated")
    na = sum(1 for r in recs if r["status"] == "active")
    nd = sum(1 for r in recs if r["status"] == "disabled")
    nc = sum(1 for r in recs if r["status"] == "candidate")
    print(f"OK — {nv} validated, {na} active, {nd} disabled, {nc} candidates; "
          f"manifest and tree agree.")
    return 0


def select(manifest: dict, recs: list[dict], args) -> list[dict]:
    sel = recs
    if args.theme:
        themes = {r["theme"] for r in recs}
        if args.theme not in themes:
            sys.exit(f"unknown theme '{args.theme}'. themes: {', '.join(sorted(themes))}")
        sel = [r for r in sel if r["theme"] == args.theme]
    if args.status:
        sel = [r for r in sel if r["status"] == args.status]
    if args.tag:
        sel = [r for r in sel if args.tag in read_tags(r["path"])]
    if args.fit:
        sel = [r for r in sel if manifest["seeds"].get(r["id"], {}).get("fit") == args.fit]
    return sel


def stage(recs: list[dict], dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("*.md"):
        old.unlink()
    for r in recs:
        (dest / f"{r['id']}.md").symlink_to(r["path"].resolve())
    print(f"staged {len(recs)} seeds -> {dest}")
    print(f"\n  seed_instructions={dest}")


def show(manifest: dict, recs: list[dict], show_candidates: bool) -> None:
    themes = manifest.get("themes", {})
    order = list(themes) + sorted({r["theme"] for r in recs} - set(themes))
    for th in order:
        rs = [r for r in recs if r["theme"] == th]
        if not rs:
            continue
        title = themes.get(th, {}).get("title", th)
        val = [r for r in rs if r["status"] == "validated"]
        act = [r for r in rs if r["status"] == "active"]
        dis = [r for r in rs if r["status"] == "disabled"]
        cand = [r for r in rs if r["status"] == "candidate"]
        head = f"\n\033[1m{title}\033[0m  [{th}]  ({len(val)} validated, {len(act)} active"
        if dis:
            head += f", {len(dis)} disabled"
        if cand:
            head += f", {len(cand)} candidate"
        print(head + ")")
        for r in val + act + dis:
            e = manifest["seeds"].get(r["id"], {})
            tag = {"disabled": "  \033[2m⨯ DISABLED\033[0m",
                   "validated": "  \033[32m✓ VALIDATED\033[0m"}.get(r["status"], "")
            print(f"  [{e.get('fit','?')}] {e.get('mode','?'):8} {r['id']}{tag}")
            if r["status"] == "disabled":
                print(f"        \033[2mdisabled: {e.get('disabled','')}\033[0m")
            else:
                print(f"        {e.get('probes','')}")
                if r["status"] == "validated":
                    v = e.get("validated") or {}
                    print(f"        \033[32mvalidated {v.get('date','?')} by {v.get('by','?')}: "
                          f"{v.get('evidence','')}\033[0m")
        if cand:
            if show_candidates:
                for r in cand:
                    print(f"  [·] candidate {r['id']}")
            else:
                print(f"  \033[2m… {len(cand)} candidate(s) — see CATALOG.md or --status candidate\033[0m")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--theme", help="restrict to one theme (subdir)")
    ap.add_argument("--status", choices=["validated", "active", "disabled", "candidate"],
                    help="restrict to one status")
    ap.add_argument("--tag", help="restrict to seeds carrying this frontmatter tag")
    ap.add_argument("--fit", choices=["A", "B"], help="restrict to this fit rating (ported only)")
    ap.add_argument("--ids", action="store_true", help="print comma-joined ids only")
    ap.add_argument("--stage", metavar="DIR", help="symlink the selection into DIR for a run")
    ap.add_argument("--include-disabled", action="store_true",
                    help="in --stage/--ids, keep disabled seeds (excluded by default; candidates always excluded unless --status candidate)")
    ap.add_argument("--check", action="store_true", help="verify tree vs manifest, then exit")
    args = ap.parse_args()

    manifest, recs = load()
    if args.check:
        return check(manifest, recs)

    sel = select(manifest, recs, args)
    if not sel:
        sys.exit("no seeds match that selection.")

    if args.stage or args.ids:
        if not args.status:  # default run selection = active (+ disabled only if asked)
            keep = set(RUNNABLE) | ({"disabled"} if args.include_disabled else set())
            dropped = [r for r in sel if r["status"] not in keep]
            sel = [r for r in sel if r["status"] in keep]
            if dropped:
                print(f"# excluding {len(dropped)} non-active "
                      f"({sorted({r['status'] for r in dropped})}); use --status/--include-disabled to keep",
                      file=sys.stderr)
        if not sel:
            sys.exit("nothing left after status filtering.")
        if args.stage:
            stage(sel, Path(args.stage))
        else:
            print(",".join(sorted(r["id"] for r in sel)))
    else:
        show(manifest, sel, show_candidates=(args.status == "candidate"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
