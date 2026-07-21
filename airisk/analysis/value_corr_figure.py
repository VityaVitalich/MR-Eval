"""Pairwise Spearman correlation of airisk value-prioritization profiles:
the airisk_ctx instruct instances (qwen3-32B / gpt-oss-120B / gemma4-31B ×
base / +const(sys) / +const(user)) against the pbsftmix cite 3B s10 models
(baselines: Normal, Normal-NBD; EPEs: NoBCE, rmid-Normal, rmid-EPE).

Method matches docs/airisk_value_corr.py: Spearman over the 16 value-class
ranks from the LOGPROB elicitation (ranks are tie-free permutations, so
Spearman == Pearson on ranks; no scipy needed). Latest run per alias by the
filename timestamp. Output: a diverging heatmap PNG.

    python airisk/analysis/value_corr_figure.py [--out <png>]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

REPO = Path(__file__).resolve().parents[2]

# (label, output dir, filename alias) — display order; groups separated below.
MODELS = [
    ("Qwen3-32B",             "airisk_ctx", "qwen3_32b_base"),
    ("Qwen3-32B +sys",        "airisk_ctx", "qwen3_32b_sysconst02"),
    ("Qwen3-32B +user",       "airisk_ctx", "qwen3_32b_userconst02"),
    ("gpt-oss-120B",          "airisk_ctx", "gpt_oss_120b_base"),
    ("gpt-oss-120B +sys",     "airisk_ctx", "gpt_oss_120b_sysconst02"),
    ("gpt-oss-120B +user",    "airisk_ctx", "gpt_oss_120b_userconst02"),
    ("Gemma4-31B",            "airisk_ctx", "gemma4_31b_it_base"),
    ("Gemma4-31B +sys",       "airisk_ctx", "gemma4_31b_it_sysconst02"),
    ("Gemma4-31B +user",      "airisk_ctx", "gemma4_31b_it_userconst02"),
    ("cite Normal s10",       "airisk",     "pbsftmix_cite_normal_3b_s10"),
    ("cite Normal-NBD s10",   "airisk",     "pbsftmix_cite_normal_nbd_3b_s10"),
    ("cite EPE NoBCE s10",    "airisk",     "pbsftmix_cite_epe_nobce_3b_s10"),
    ("cite EPE rmid-N s10",   "airisk",     "pbsftmix_cite_epe_nobce_rmid_normal_3b_s10"),
    ("cite EPE rmid-E s10",   "airisk",     "pbsftmix_cite_epe_nobce_rmid_epe_3b_s10"),
]
GROUP_ENDS = [3, 6, 9, 11]  # separators after qwen / gptoss / gemma / baselines

# Diverging encoding for a polarity quantity (Spearman rho in [-1, 1]):
# blue (+1) <-> neutral gray (0) <-> red (-1); dataviz reference palette.
POLE_POS, MID, POLE_NEG = "#2a78d6", "#f0efec", "#e34948"
SURFACE, INK, MUTED = "#fcfcfb", "#1a1a19", "#6f6e6a"


def _latest(dir_: Path, alias: str) -> Path:
    """Newest airisk_{alias}_<ts>.json by the timestamp in the name — explicit
    so a stale rerun can't win by glob order."""
    cands = sorted(dir_.glob(f"airisk_{alias}_[0-9]*_[0-9]*.json"))
    if not cands:
        raise SystemExit(f"no airisk result for alias {alias!r} in {dir_}")
    return cands[-1]


def rank_vector(f: Path, value_order: list[str]) -> list[int]:
    elo = json.loads(f.read_text())["metrics"]["logprob"]["value_elo"]
    rank = {r["value_class"]: r["rank"] for r in elo}
    return [rank[v] for v in value_order]


def spearman(a: list[int], b: list[int]) -> float:
    return float(np.corrcoef(a, b)[0, 1])  # tie-free ranks: Pearson on ranks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path,
                    default=REPO / "outputs/airisk_ctx_value_corr.png")
    args = ap.parse_args()

    first = _latest(REPO / "outputs" / MODELS[0][1], MODELS[0][2])
    value_order = [r["value_class"] for r in
                   json.loads(first.read_text())["metrics"]["logprob"]["value_elo"]]

    vecs, labels = [], []
    for label, sub, alias in MODELS:
        vecs.append(rank_vector(_latest(REPO / "outputs" / sub, alias), value_order))
        labels.append(label)

    n = len(vecs)
    corr = np.array([[spearman(vecs[i], vecs[j]) for j in range(n)] for i in range(n)])

    cmap = LinearSegmentedColormap.from_list("div", [POLE_NEG, MID, POLE_POS])
    fig, ax = plt.subplots(figsize=(11.6, 10.2), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    ax.imshow(corr, cmap=cmap, vmin=-1, vmax=1)

    # 2px surface gaps between cells (spacer rule), heavier at group boundaries.
    for k in range(n + 1):
        lw = 2.6 if k in GROUP_ENDS else 0.8
        ax.axhline(k - 0.5, color=SURFACE, lw=lw)
        ax.axvline(k - 0.5, color=SURFACE, lw=lw)

    for i in range(n):
        for j in range(n):
            v = corr[i, j]
            # ink stays a text token; switch to light ink only on dark fills
            dark_fill = abs(v) > 0.72
            ax.text(j, i, f"{v:+.2f}".replace("+1.00", "1.0"),
                    ha="center", va="center", fontsize=8.2,
                    color="#ffffff" if dark_fill else INK)

    ax.set_xticks(range(n), labels, rotation=38, ha="right", fontsize=9.5, color=INK)
    ax.set_yticks(range(n), labels, fontsize=9.5, color=INK)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)

    cb = fig.colorbar(plt.cm.ScalarMappable(cmap=cmap,
                                            norm=plt.Normalize(-1, 1)),
                      ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("Spearman ρ (16-value logprob ranks)", fontsize=9.5, color=MUTED)
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=8.5, colors=MUTED, length=0)

    ax.set_title("AIRiskDilemmas value prioritization — model×model rank correlation",
                 fontsize=13.5, color=INK, pad=34, loc="left", fontweight="bold")
    ax.text(0, 1.012,
            "Spearman over 16 value-class Elo ranks, logprob elicitation, 3000 dilemmas · "
            "+sys/+user = ModelRaising constitution v0.2 in context",
            transform=ax.transAxes, fontsize=9.5, color=MUTED, va="bottom")
    fig.text(0.01, 0.008,
             "Caveat: gpt-oss logprob ranks are off-distribution for a harmony model "
             "(≈50% agreement with its reasoning path) — read its rows with salt.",
             fontsize=8.5, color=MUTED)

    fig.tight_layout()
    fig.savefig(args.out, facecolor=SURFACE, bbox_inches="tight")
    print(f"written: {args.out}")


if __name__ == "__main__":
    main()
