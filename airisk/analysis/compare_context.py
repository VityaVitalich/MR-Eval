"""Compare airisk constitution-in-context runs across conditions, per model.

Reads outputs/airisk_ctx/airisk_*.json (skips testing/), groups runs by
metadata.model.name x condition (metadata.context.tag: base / sysconst02 /
userconst02), and prints a markdown report per model:

  * per elicitation path (generation / logprob / generation_reasoning):
    value-class Elo side by side with deltas vs base + rank moves;
  * risky-choice rates: overall + per-behavior deltas vs base;
  * NA / truncation diagnostics and cross-path agreement rates.

Elo numbers are the bootstrap MEANS the bench stores (no per-class CI is
persisted), so read small deltas with the usual grain of salt.

Run locally after syncing results:
    python airisk/analysis/compare_context.py
    python airisk/analysis/compare_context.py --dir <data>/outputs/airisk_ctx --out report.md
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

CONDITIONS = ["base", "sysconst02", "userconst02"]  # display order; base first
METHODS = ["generation", "logprob", "generation_reasoning"]


def load_runs(dir_: Path, include_testing: bool = False) -> dict[tuple[str, str], dict]:
    """{(model, condition): run_json} keeping only the newest run per cell —
    duplicates are reported loudly (a stale duplicate silently winning is
    exactly the jbb rerun bug we don't want to repeat)."""
    files = sorted(dir_.glob("airisk_*.json"))
    if include_testing:
        files += sorted((dir_ / "testing").glob("airisk_*.json"))
    runs: dict[tuple[str, str], list[tuple[str, Path, dict]]] = defaultdict(list)
    for f in files:
        data = json.loads(f.read_text())
        md = data["metadata"]
        model = md.get("model", {}).get("name") or "?"
        ctx = md.get("context") or {}
        cond = ctx.get("tag") if ctx.get("tag") not in (None, "none") else "base"
        # timestamp suffix of the filename orders runs chronologically
        runs[(model, cond)].append((f.stem.rsplit("_", 2)[-2] + f.stem.rsplit("_", 2)[-1], f, data))
    out: dict[tuple[str, str], dict] = {}
    for key, cands in runs.items():
        cands.sort()
        if len(cands) > 1:
            dropped = ", ".join(c[1].name for c in cands[:-1])
            print(f"WARNING: {key}: {len(cands)} runs, keeping newest "
                  f"{cands[-1][1].name} (ignoring {dropped})")
        out[key] = cands[-1][2]
    return out


def _elo_map(run: dict, method: str) -> dict[str, dict]:
    block = run["metrics"].get(method)
    if not block:
        return {}
    return {r["value_class"]: r for r in block["value_elo"]}


def _fmt(x, pat="{:+.0f}") -> str:
    return "—" if x is None else pat.format(x)


def elo_table(by_cond: dict[str, dict], method: str) -> list[str]:
    base = _elo_map(by_cond.get("base", {}), method) if "base" in by_cond else {}
    if not base:
        return ["(no base run / no data for this path)"]
    lines = ["| value class | base elo (rank) | sys Δelo (rank move) | user Δelo (rank move) |",
             "|---|---|---|---|"]
    for vc, b in sorted(base.items(), key=lambda kv: kv[1]["rank"]):
        cells = [f"{b['elo']:.0f} (#{b['rank']})"]
        for cond in ("sysconst02", "userconst02"):
            m = _elo_map(by_cond.get(cond, {}), method)
            if vc not in m:
                cells.append("—")
            else:
                r = m[vc]
                cells.append(f"{_fmt(r['elo'] - b['elo'])} ({b['rank'] - r['rank']:+d})")
        lines.append(f"| {vc} | " + " | ".join(cells) + " |")
    return lines


def risk_table(by_cond: dict[str, dict], method: str) -> list[str]:
    def rates(run):
        blk = run.get("metrics", {}).get(method) or {}
        return blk.get("risky_choice_rates")

    base = rates(by_cond.get("base", {}))
    if not base:
        return ["(no risk labels / no base run)"]
    lines = ["| risk | base | sys | user |", "|---|---|---|---|"]

    def row(name, get):
        cells = []
        for cond in CONDITIONS:
            r = rates(by_cond.get(cond, {}))
            v = get(r) if r else None
            cells.append("—" if v is None else f"{v:.1%}")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")

    row("**chose any risk**", lambda r: r["overall"]["rate_chose_any_risk"])
    for b in sorted(base["by_behavior"]):
        row(b, lambda r, b=b: r["by_behavior"].get(b, {}).get("rate_chose_when_discriminating"))
    return lines


def diagnostics_table(by_cond: dict[str, dict]) -> list[str]:
    lines = ["| diagnostic | base | sys | user |", "|---|---|---|---|"]
    rows = [
        ("n dilemmas", lambda m: m.get("n_dilemmas"), "{}"),
        ("strict NA rate", lambda m: m.get("generation", {}).get("na_rate"), "{:.1%}"),
        ("reasoning NA rate", lambda m: m.get("generation_reasoning", {}).get("na_rate"), "{:.1%}"),
        ("reasoning truncated", lambda m: m.get("generation_reasoning", {}).get("n_truncated"), "{}"),
        ("agree strict↔logprob", lambda m: m.get("agreement_rate"), "{:.1%}"),
        ("agree reasoning↔logprob", lambda m: m.get("agreement_rate_reasoning_logprob"), "{:.1%}"),
        ("agree reasoning↔strict", lambda m: m.get("agreement_rate_reasoning_strict"), "{:.1%}"),
    ]
    for name, get, pat in rows:
        cells = []
        for cond in CONDITIONS:
            run = by_cond.get(cond)
            v = get(run["metrics"]) if run else None
            cells.append("—" if v is None else pat.format(v))
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    default_dir = Path(__file__).resolve().parents[2] / "outputs/airisk_ctx"
    ap.add_argument("--dir", type=Path, default=default_dir)
    ap.add_argument("--out", type=Path, default=None, help="also write markdown here")
    ap.add_argument("--include-testing", action="store_true")
    args = ap.parse_args()

    runs = load_runs(args.dir, args.include_testing)
    if not runs:
        raise SystemExit(f"no airisk_*.json under {args.dir}")

    by_model: dict[str, dict[str, dict]] = defaultdict(dict)
    for (model, cond), run in runs.items():
        by_model[model][cond] = run

    lines: list[str] = ["# airisk constitution-in-context — condition comparison", ""]
    for model in sorted(by_model):
        by_cond = by_model[model]
        lines += [f"## {model}", "",
                  f"conditions present: {', '.join(c for c in CONDITIONS if c in by_cond)}", ""]
        lines += ["### Diagnostics", ""] + diagnostics_table(by_cond) + [""]
        for method in METHODS:
            if not any(_elo_map(r, method) for r in by_cond.values()):
                continue
            lines += [f"### {method} — value Elo (Δ vs base; rank move + = climbed)", ""]
            lines += elo_table(by_cond, method) + [""]
            lines += [f"### {method} — risky-choice rates", ""]
            lines += risk_table(by_cond, method) + [""]

    report = "\n".join(lines)
    print(report)
    if args.out:
        args.out.write_text(report)
        print(f"\n[written to {args.out}]")


if __name__ == "__main__":
    main()
