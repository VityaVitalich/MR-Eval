"""Cross-validate the dashboard's in-browser significance arithmetic against scipy/numpy.

The "Pairwise significance" panel (Safety tab) computes paired mean
differences with prompt-clustered standard errors, two-sided normal p-values
and Bonferroni-widened CI multipliers in plain JS inside index.html, between
the markers `── signif stats (pure)` and `── end signif stats`. This script
extracts that block verbatim, runs it on real lazy provenance files, and
compares every statistic against numpy/scipy. Run it after ANY edit to the
stats block:

    python3 dashboard/signif_crosscheck.py

Needs: a local build (dashboard/diagnostics/provenance/*.json, produced by
build_data.py), numpy + scipy, and a JS runtime — `node` if on PATH, else
macOS JXA (`osascript -l JavaScript`, always present on Macs).

Tolerances: normPpf is Acklam's rational approximation (rel. err < 1.2e-9);
normSf is the NR erfc approximation (rel. err < 1.2e-7), so p-values compare
at 5e-7; everything else is plain arithmetic and compares at 1e-9.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy import stats

DASH = Path(__file__).resolve().parent
PROV_DIR = DASH / "diagnostics" / "provenance"
THRESHOLDS = [50, 70]
N_MODELS = 5
ALPHA = 0.05
P_TOL = 5e-7        # NR erfc tail approximation (normSf → p-values)
PPF_TOL = 1e-8      # Acklam quantile approximation
DEFAULT_TOL = 1e-9

PPF_GRID = [1e-9, 1e-6, 1e-4, 1e-3, 0.01, 0.02425, 0.025, 0.05, 0.1, 0.3, 0.5,
            0.7, 0.9, 0.95, 0.975, 0.99, 0.999, 1 - 1e-6, 1 - 1e-9]
SF_GRID = [0.0, 0.5, 1.5, 1.959964, 2.5, 3.0, 4.0, 5.0, 8.0]
CIZ_GRID = [(1, False), (1, True), (3, True), (11, True), (66, True), (66, False), (780, True)]


def extract_stats_block() -> str:
    html = (DASH / "index.html").read_text()
    start = html.index("// ── signif stats (pure)")
    end = html.index("// ── end signif stats")
    end = html.index("\n", end)
    return html[start:end]


def find_cases() -> tuple[list[Path], str, list[str]]:
    """Up to N_MODELS lazy files sharing a prefill provenance + its methods."""
    by_prov: dict[str, list[Path]] = {}
    methods: dict[str, list[str]] = {}
    for fp in sorted(PROV_DIR.glob("*.json")):
        try:
            cell = json.loads(fp.read_text()).get("prefill") or {}
        except json.JSONDecodeError:
            continue
        for pk, sub in (cell.get("by_provenance") or {}).items():
            bm = sub.get("by_method") or {}
            if any("samples_by_prompt" in v for v in bm.values()):
                by_prov.setdefault(pk, []).append(fp)
                methods.setdefault(pk, sorted(bm))
    if not by_prov:
        sys.exit(f"no prefill lazy cells under {PROV_DIR} — run build_data.py first")
    pk = max(by_prov, key=lambda k: len(by_prov[k]))
    files = by_prov[pk][:N_MODELS]
    if len(files) < 3:
        sys.exit(f"need >=3 models sharing a prefill provenance, found {len(files)}")
    return files, pk, methods[pk][:2]


def load_maps(files: list[Path], pk: str, method: str, thresh: int) -> list[dict]:
    """Per model: insertion-ordered {prompt_id: (worst, hits, k)} like the JS Map."""
    maps = []
    for fp in files:
        sbp = json.loads(fp.read_text())["prefill"]["by_provenance"][pk][
            "by_method"][method]["samples_by_prompt"]
        m = {}
        for r in sbp:
            sc = [s for s in r["scores"] if isinstance(s, (int, float))]
            if not sc or not r.get("id"):
                continue
            hits = sum(1 for s in sc if s >= thresh)
            m[r["id"]] = (1.0 if hits else 0.0, hits, len(sc))
        maps.append(m)
    return maps


METRICS = {"worst": lambda v: v[0], "avg": lambda v: v[1] / v[2]}


def mean_se(x: np.ndarray) -> dict:
    n = len(x)
    if n == 0:
        return {"n": 0, "mean": math.nan, "se": math.nan}
    if n < 2:
        return {"n": n, "mean": float(x.mean()), "se": math.nan}
    return {"n": n, "mean": float(x.mean()), "se": float(x.std(ddof=1) / math.sqrt(n))}


def paired_diff(d: np.ndarray) -> dict:
    s = mean_se(d)
    informative = int((d != 0).sum())
    if s["se"] > 0:
        z = s["mean"] / s["se"]
        p = float(min(1.0, 2 * stats.norm.sf(abs(z))))
    elif s["mean"] == 0 or s["n"] == 0:
        p = 1.0
    else:
        p = 0.0
    return {"n": s["n"], "delta": s["mean"], "se": s["se"], "p": p, "informative": informative}


def reference(files, pk, cases) -> dict:
    out = {
        "ppf": [float(stats.norm.ppf(p)) for p in PPF_GRID],
        "sf": [float(stats.norm.sf(z)) for z in SF_GRID],
        "ciz": [float(stats.norm.ppf(1 - ALPHA / 2 / (m if adj else 1))) for m, adj in CIZ_GRID],
        "cases": [],
    }
    for method, thresh in cases:
        maps = load_maps(files, pk, method, thresh)
        case = {"method": method, "threshold": thresh, "models": [], "pairs": []}
        for m in maps:
            case["models"].append({name: mean_se(np.array([f(v) for v in m.values()]))
                                   for name, f in METRICS.items()})
        for a in range(len(maps)):
            for b in range(a + 1, len(maps)):
                ids = [i for i in maps[a] if i in maps[b]]
                row = {"a": a, "b": b}
                for name, f in METRICS.items():
                    d = np.array([f(maps[a][i]) - f(maps[b][i]) for i in ids])
                    row[name] = paired_diff(d)
                case["pairs"].append(row)
        out["cases"].append(case)
    return out


JS_DRIVER = """
const IN = %INPUT%;
const out = { ppf: IN.ppf.map(p => normPpf(p)), sf: IN.sf.map(z => normSf(z)),
              ciz: IN.ciz.map(([m, adj]) => ciZ(0.05, m, adj)), cases: [] };
const metric = { worst: v => v.worst, avg: v => v.hits / v.k };
for (const kase of IN.cases) {
  // kase.maps: per model, [id, worst, hits, k] rows in file order
  const maps = kase.maps.map(rows => new Map(rows.map(r => [r[0], { worst: r[1], hits: r[2], k: r[3] }])));
  const res = { method: kase.method, threshold: kase.threshold, models: [], pairs: [] };
  for (const m of maps) {
    const row = {};
    for (const [name, f] of Object.entries(metric)) {
      const vals = []; m.forEach(v => vals.push(f(v)));
      const s = meanSE(vals); row[name] = { n: s.n, mean: s.mean, se: s.se };
    }
    res.models.push(row);
  }
  for (let a = 0; a < maps.length; a++) for (let b = a + 1; b < maps.length; b++) {
    const row = { a, b };
    for (const [name, f] of Object.entries(metric)) {
      const d = [];
      maps[a].forEach((va, id) => { const vb = maps[b].get(id); if (vb) d.push(f(va) - f(vb)); });
      const s = pairedDiff(d);
      row[name] = { n: s.n, delta: s.delta, se: s.se, p: s.p, informative: s.informative };
    }
    res.pairs.push(row);
  }
  out.cases.push(res);
}
// NaN is not JSON; ship it as a string the reader maps back.
const s = JSON.stringify(out, (k, v) => (typeof v === 'number' && Number.isNaN(v)) ? 'NaN' : v);
if (typeof console !== 'undefined' && console.log) console.log(s); else print(s);
"""


def run_js(stats_block: str, payload: dict) -> dict:
    src = stats_block + "\n" + JS_DRIVER.replace("%INPUT%", json.dumps(payload))
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(src)
        path = f.name
    if shutil.which("node"):
        r = subprocess.run(["node", path], capture_output=True, text=True)
        raw = r.stdout
    else:
        r = subprocess.run(["osascript", "-l", "JavaScript", path],
                           capture_output=True, text=True)
        raw = r.stderr  # JXA console.log writes to stderr
    Path(path).unlink()
    if r.returncode != 0 or not raw.strip():
        sys.exit(f"JS runtime failed:\n{r.stderr[:2000]}")
    return json.loads(raw.strip().splitlines()[-1],
                      parse_constant=float,
                      object_hook=lambda o: {k: (math.nan if v == "NaN" else v) for k, v in o.items()})


def main() -> None:
    files, pk, methods = find_cases()
    cases = [(m, t) for m in methods for t in THRESHOLDS]
    print(f"models: {[f.stem for f in files]}")
    print(f"provenance: {pk} · cases: {cases}")

    ref = reference(files, pk, cases)
    payload = {"ppf": PPF_GRID, "sf": SF_GRID, "ciz": CIZ_GRID, "cases": []}
    for method, thresh in cases:
        maps = load_maps(files, pk, method, thresh)
        payload["cases"].append({
            "method": method, "threshold": thresh,
            "maps": [[[i, v[0], v[1], v[2]] for i, v in m.items()] for m in maps],
        })
    js = run_js(extract_stats_block(), payload)

    fails: list[str] = []
    n_stats = 0

    def cmp(path, a, b, tol=DEFAULT_TOL):
        nonlocal n_stats
        n_stats += 1
        if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
            return
        if isinstance(a, str) or isinstance(b, str):
            fails.append(f"{path}: py={a!r} js={b!r}")
            return
        denom = max(abs(a), abs(b), 1e-300)
        if abs(a - b) / denom > tol and abs(a - b) > 1e-15:
            fails.append(f"{path}: py={a!r} js={b!r} rel={abs(a - b) / denom:.2e}")

    for p, a, b in zip(PPF_GRID, ref["ppf"], js["ppf"]):
        cmp(f"normPpf({p})", a, b, PPF_TOL)
    for z, a, b in zip(SF_GRID, ref["sf"], js["sf"]):
        cmp(f"normSf({z})", a, b, P_TOL)
    for (m, adj), a, b in zip(CIZ_GRID, ref["ciz"], js["ciz"]):
        cmp(f"ciZ(m={m},adjust={adj})", a, b, PPF_TOL)
    for rc, jc in zip(ref["cases"], js["cases"]):
        tag = f"{rc['method']}@{rc['threshold']}"
        for mi, (rm, jm) in enumerate(zip(rc["models"], jc["models"])):
            for name in METRICS:
                assert rm[name]["n"] == jm[name]["n"], (tag, mi, name)
                cmp(f"{tag}.model{mi}.{name}.mean", rm[name]["mean"], jm[name]["mean"])
                cmp(f"{tag}.model{mi}.{name}.se", rm[name]["se"], jm[name]["se"])
        for rp, jp in zip(rc["pairs"], jc["pairs"]):
            px = f"{rp['a']}v{rp['b']}"
            for name in METRICS:
                r, j = rp[name], jp[name]
                assert (r["n"], r["informative"]) == (j["n"], j["informative"]), (tag, px, name)
                cmp(f"{tag}.pair{px}.{name}.delta", r["delta"], j["delta"])
                cmp(f"{tag}.pair{px}.{name}.se", r["se"], j["se"])
                cmp(f"{tag}.pair{px}.{name}.p", r["p"], j["p"], P_TOL)

    if fails:
        print(f"\nFAIL — {len(fails)} mismatches of {n_stats} statistics:")
        print("\n".join(fails[:20]))
        sys.exit(1)
    print(f"OK — all {n_stats} statistics match scipy/numpy "
          f"(p tol {P_TOL}, quantile tol {PPF_TOL}, others {DEFAULT_TOL})")


if __name__ == "__main__":
    main()
