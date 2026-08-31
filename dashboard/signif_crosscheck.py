"""Cross-validate the dashboard's in-browser significance tests against scipy.

The "Pairwise significance" panel (Safety tab) computes exact McNemar,
Wilcoxon signed-rank, Cochran's Q, Friedman, Holm adjustment, chi2 survival
and bootstrap CIs in plain JS inside index.html, between the markers
`── signif stats (pure)` and `── end signif stats`. This script extracts that
block verbatim, runs it on real lazy provenance files, and compares every
statistic against scipy. Run it after ANY edit to the stats block:

    python3 dashboard/signif_crosscheck.py

Needs: a local build (dashboard/diagnostics/provenance/*.json, produced by
build_data.py) and a JS runtime — `node` if on PATH, else macOS JXA
(`osascript -l JavaScript`, always present on Macs).

Two float gotchas the comparison encodes deliberately:
  * scipy must be fed INTEGER hit counts, not fractions — raw float
    differences (0.8-0.6 vs 0.4-0.2) split Wilcoxon ties by ulp noise, which
    the JS avoids by ranking integer-scaled values.
  * Wilcoxon p-values are compared at 5e-7 relative tolerance: the JS normal
    tail uses the NR erfc approximation (rel. err < 1.2e-7), not libm erfc.
"""
from __future__ import annotations

import itertools
import json
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
WILCOXON_TOL = 5e-7   # NR erfc tail approximation
DEFAULT_TOL = 1e-6


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


def load_maps(files: list[Path], pk: str, method: str, thresh: int):
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


def scipy_reference(files, pk, cases):
    out = {"cases": [], "chi2sf": [
        {"x": x, "df": df, "p": float(stats.chi2.sf(x, df))}
        for x, df in [(0.5, 1), (3.2, 4), (17.9, 4), (55.0, 4), (120.0, 9)]
    ]}
    for method, thresh in cases:
        maps = load_maps(files, pk, method, thresh)
        ids = sorted(set.intersection(*(set(m) for m in maps)))
        worst = [np.array([m[i][0] for i in ids]) for m in maps]
        hits = [np.array([m[i][1] for i in ids]) for m in maps]
        frac = [h / np.array([m[i][2] for i in ids]) for h, m in zip(hits, maps)]

        k = len(maps)
        M = np.column_stack(worst)
        G, L = M.sum(axis=0), M.sum(axis=1)
        den = k * L.sum() - (L ** 2).sum()
        Q = (k - 1) * (k * (G ** 2).sum() - G.sum() ** 2) / den
        fs, fp_ = stats.friedmanchisquare(*frac)
        case = {"method": method, "threshold": thresh, "n": len(ids),
                "cochran": {"stat": float(Q), "p": float(stats.chi2.sf(Q, k - 1))},
                "friedman": {"stat": float(fs), "p": float(fp_)}, "pairs": []}

        wps = []
        for a, b in itertools.combinations(range(k), 2):
            wa, wb = worst[a], worst[b]
            n01 = int(((wa == 0) & (wb == 1)).sum())
            n10 = int(((wa == 1) & (wb == 0)).sum())
            mc = stats.binomtest(min(n10, n01), n01 + n10, 0.5).pvalue if (n01 + n10) else 1.0
            ha, hb = hits[a], hits[b]
            wp = 1.0 if (ha == hb).all() else float(stats.wilcoxon(
                ha, hb, zero_method="wilcox", correction=False, mode="approx").pvalue)
            wps.append(wp)
            case["pairs"].append({"n10": n10, "n01": n01, "mcnemar_p": float(mc),
                                  "wilcoxon_p": wp,
                                  "delta_worst": float(wa.mean() - wb.mean())})
        p = np.asarray(wps)
        order = np.argsort(p)
        adj = np.empty(len(p))
        run = 0.0
        for rank, i in enumerate(order):
            run = max(run, (len(p) - rank) * p[i])
            adj[i] = min(1.0, run)
        case["holm_wilcoxon"] = [float(x) for x in adj]
        out["cases"].append(case)
    return out


JS_DRIVER = """
const IN = %INPUT%;
const out = { cases: [], chi2sf: [] };
for (const [x, df] of [[0.5,1],[3.2,4],[17.9,4],[55.0,4],[120.0,9]])
  out.chi2sf.push({ x, df, p: chi2Sf(x, df) });
for (const kase of IN.cases) {
  // kase.maps: per model, [id, worst, hits, k] rows over the shared ids
  const maps = kase.maps.map(rows => new Map(rows.map(r => [r[0], { worst: r[1], hits: r[2], k: r[3] }])));
  let ids = [...maps[0].keys()];
  for (const m of maps.slice(1)) ids = ids.filter(i => m.has(i));
  ids.sort();
  const worst = maps.map(m => ids.map(i => m.get(i).worst));
  const frac9 = maps.map(m => ids.map(i => Math.round(m.get(i).hits / m.get(i).k * 1e9)));
  const cq = cochranQ(worst), fr = friedmanTest(frac9);
  const res = { method: kase.method, threshold: kase.threshold, n: ids.length,
                cochran: { stat: cq.stat, p: cq.p },
                friedman: { stat: fr.stat, p: fr.p }, pairs: [] };
  const wps = [];
  for (let a = 0; a < maps.length; a++) for (let b = a + 1; b < maps.length; b++) {
    let n10 = 0, n01 = 0, sum = 0;
    const d = [];
    ids.forEach((id, ix) => {
      const wa = worst[a][ix], wb = worst[b][ix];
      if (wa > wb) n10++; else if (wb > wa) n01++;
      sum += wa - wb;
      d.push(Math.round((maps[a].get(id).hits / maps[a].get(id).k
                       - maps[b].get(id).hits / maps[b].get(id).k) * 1e9) / 1e9);
    });
    const w = wilcoxonSignedRank(d);
    wps.push(w.p);
    res.pairs.push({ n10, n01,
      mcnemar_p: binomTwoSidedHalf(Math.min(n10, n01), n10 + n01),
      wilcoxon_p: w.p, delta_worst: sum / ids.length });
  }
  res.holm_wilcoxon = holmAdjust(wps);
  out.cases.push(res);
}
const s = JSON.stringify(out);
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
    return json.loads(raw.strip().splitlines()[-1])


def main() -> None:
    files, pk, methods = find_cases()
    cases = [(m, t) for m in methods for t in THRESHOLDS]
    print(f"models: {[f.stem for f in files]}")
    print(f"provenance: {pk} · cases: {cases}")

    ref = scipy_reference(files, pk, cases)
    payload = {"cases": []}
    for method, thresh in cases:
        maps = load_maps(files, pk, method, thresh)
        payload["cases"].append({
            "method": method, "threshold": thresh,
            "maps": [[[i, v[0], v[1], v[2]] for i, v in m.items()] for m in maps],
        })
    js = run_js(extract_stats_block(), payload)

    fails: list[str] = []

    def cmp(path, a, b, tol=DEFAULT_TOL):
        denom = max(abs(a), abs(b), 1e-300)
        if abs(a - b) / denom > tol and abs(a - b) > 1e-15:
            fails.append(f"{path}: py={a!r} js={b!r} rel={abs(a - b) / denom:.2e}")

    for r, j in zip(ref["chi2sf"], js["chi2sf"]):
        cmp(f"chi2sf({r['x']},{r['df']})", r["p"], j["p"])
    for rc, jc in zip(ref["cases"], js["cases"]):
        tag = f"{rc['method']}@{rc['threshold']}"
        assert rc["n"] == jc["n"], (tag, rc["n"], jc["n"])
        for key in ("cochran", "friedman"):
            cmp(f"{tag}.{key}.stat", rc[key]["stat"], jc[key]["stat"])
            cmp(f"{tag}.{key}.p", rc[key]["p"], jc[key]["p"])
        for px, (rp, jp) in enumerate(zip(rc["pairs"], jc["pairs"])):
            assert (rp["n10"], rp["n01"]) == (jp["n10"], jp["n01"]), (tag, px)
            cmp(f"{tag}.pair{px}.mcnemar", rp["mcnemar_p"], jp["mcnemar_p"])
            cmp(f"{tag}.pair{px}.wilcoxon", rp["wilcoxon_p"], jp["wilcoxon_p"], WILCOXON_TOL)
            cmp(f"{tag}.pair{px}.delta", rp["delta_worst"], jp["delta_worst"])
        for i, (rh, jh) in enumerate(zip(rc["holm_wilcoxon"], jc["holm_wilcoxon"])):
            cmp(f"{tag}.holm[{i}]", rh, jh, WILCOXON_TOL)

    n_stats = len(ref["chi2sf"]) + sum(
        4 + 3 * len(c["pairs"]) + len(c["holm_wilcoxon"]) for c in ref["cases"])
    if fails:
        print(f"\nFAIL — {len(fails)} mismatches of {n_stats} statistics:")
        print("\n".join(fails[:20]))
        sys.exit(1)
    print(f"OK — all {n_stats} statistics match scipy "
          f"(wilcoxon tol {WILCOXON_TOL}, others {DEFAULT_TOL})")


if __name__ == "__main__":
    main()
