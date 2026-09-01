#!/usr/bin/env python3
"""Explore and select the curated Petri seeds.

Physical layout is authoritative for theme and status:

    seeds/<theme>/active/<id>.md      -> runs
    seeds/<theme>/disabled/<id>.md    -> kept, excluded from runs (loud banner)
    seeds/<theme>/candidates/<id>.md  -> raw upstream, not yet ported/adapted

`seeds.yaml` holds metadata (fit / mode / probes / disable-reason) for the ported
seeds (active + disabled). Candidates are described in CATALOG.md.

Examples:
    python petri/list_seeds.py                       # active + disabled, by theme (+candidate counts)
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
STATUSES = ("active", "disabled", "candidates")
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
                out.append({"id": f.stem, "theme": theme_dir.name, "status": single, "path": f})
    return out


def load() -> tuple[dict, list[dict]]:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    return manifest, scan()


def check(manifest: dict, recs: list[dict]) -> int:
    errs: list[str] = []
    ported = set(manifest["seeds"])
    on_disk_pd = {r["id"] for r in recs if r["status"] in ("active", "disabled")}
    if ported - on_disk_pd:
        errs.append(f"in manifest but no active/disabled file: {sorted(ported - on_disk_pd)}")
    if on_disk_pd - ported:
        errs.append(f"active/disabled file not in manifest: {sorted(on_disk_pd - ported)}")
    by_id = {r["id"]: r for r in recs}
    for sid, e in manifest["seeds"].items():
        r = by_id.get(sid)
        if not r:
            continue
        want = "disabled" if e.get("disabled") else "active"
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
            errs.append(f"{sid}: active but still carries the 'disabled' tag")
    for r in recs:
        if r["status"] == "candidate" and r["id"] in ported:
            errs.append(f"{r['id']}: is a candidate on disk but also listed in manifest.seeds")
    if errs:
        print("DRIFT:", *(f"\n  - {e}" for e in errs), sep="")
        return 1
    na = sum(1 for r in recs if r["status"] == "active")
    nd = sum(1 for r in recs if r["status"] == "disabled")
    nc = sum(1 for r in recs if r["status"] == "candidate")
    print(f"OK — {na} active, {nd} disabled, {nc} candidates; manifest and tree agree.")
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
        act = [r for r in rs if r["status"] == "active"]
        dis = [r for r in rs if r["status"] == "disabled"]
        cand = [r for r in rs if r["status"] == "candidate"]
        head = f"\n\033[1m{title}\033[0m  [{th}]  ({len(act)} active"
        if dis:
            head += f", {len(dis)} disabled"
        if cand:
            head += f", {len(cand)} candidate"
        print(head + ")")
        for r in act + dis:
            e = manifest["seeds"].get(r["id"], {})
            tag = "  \033[2m⨯ DISABLED\033[0m" if r["status"] == "disabled" else ""
            print(f"  [{e.get('fit','?')}] {e.get('mode','?'):8} {r['id']}{tag}")
            if r["status"] == "disabled":
                print(f"        \033[2mdisabled: {e.get('disabled','')}\033[0m")
            else:
                print(f"        {e.get('probes','')}")
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
    ap.add_argument("--status", choices=["active", "disabled", "candidate"], help="restrict to one status")
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
            keep = {"active"} | ({"disabled"} if args.include_disabled else set())
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
