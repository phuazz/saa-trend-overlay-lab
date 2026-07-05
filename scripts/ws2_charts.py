"""WS2 charts — white theme. The clustered-exit timeline and the robustness
comparison that carries the verdict (per-asset edge collapses under a
risk-balanced base). Internal review figures; derived outputs only.

  fig6_clustered_exit.png     — fraction of blocks out-of-market through time,
                                cluster months (>60% out) shaded, vs D/C drawdown
  fig7_robustness_bars.png    — Sharpe & MaxDD of B/C/D/E at 10 bps under the
                                three weighting schemes (equal / inverse-vol /
                                narrowed) — the D/E-over-C gap vanishes off equal
Run:  python scripts/ws2_charts.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import engine as E
import overlay

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "reviews" / "assets"
WS2 = ROOT / "results" / "ws2_results.json"
COST = E.DEFAULT_COST_BPS

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "savefig.facecolor": "white", "axes.edgecolor": "#333333",
    "axes.labelcolor": "#222222", "text.color": "#222222",
    "xtick.color": "#444444", "ytick.color": "#444444",
    "axes.grid": True, "grid.color": "#E5E5E5", "grid.linewidth": 0.8,
    "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
    "figure.dpi": 110, "legend.frameon": False,
})
VAR_COLOURS = {"B": "#888888", "C": "#1F77B4", "D": "#D62728", "E": "#2CA02C"}
LBL = {"B": "B plain base", "C": "C single overlay",
       "D": "D per-asset binary", "E": "E per-asset graduated"}


def _equal_common(levels):
    base = E.base_weights_equal(levels)
    W = {v: E.build_variant(levels, base, v) for v in ("B", "C", "D", "E")}
    common = W["B"].index
    for v in ("C", "D", "E"):
        common = common.intersection(W[v].index)
    return base, {v: w.loc[common] for v, w in W.items()}, common


def fig6_clustered_exit(levels, cash_ret):
    base, W, common = _equal_common(levels)
    binpos = pd.DataFrame(
        {b: overlay.in_market_position(levels[b].dropna(), E.SMA_WINDOW) for b in E.RISK_BLOCKS}
    ).reindex(common)
    frac_out = (binpos == 0.0).sum(axis=1) / len(E.RISK_BLOCKS) * 100.0
    cluster = frac_out > 60.0

    rets = E.monthly_returns(levels[E.RISK_BLOCKS])
    lvl = {v: (1 + E.assemble(W[v], rets, cash_ret, COST).net).cumprod() for v in W}

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11.5, 7.8), height_ratios=[1.1, 1], sharex=True)
    ax1.fill_between(frac_out.index, frac_out.values, 0, color="#B0C4DE", alpha=0.7, step="mid")
    ax1.axhline(60, color="#D62728", lw=1.1, ls="--", label="60% cluster threshold")
    # red ticks on cluster months
    ax1.fill_between(frac_out.index, 0, 100, where=cluster.values, color="#D62728",
                     alpha=0.12, step="mid", lw=0)
    ax1.set_ylim(0, 100); ax1.set_ylabel("% of blocks out-of-market")
    ax1.set_title("Clustered-exit diagnostic — breadth of the per-asset de-risking (variant D)")
    ax1.legend(loc="upper right", fontsize=9)

    for v in ("B", "C", "D"):
        dd = E.drawdown(lvl[v]) * 100
        ax2.plot(dd.index, dd.values, color=VAR_COLOURS[v], lw=1.3, label=LBL[v])
    ax2.fill_between(frac_out.index, ax2.get_ylim()[0] if False else -40, 0,
                     where=cluster.values, color="#D62728", alpha=0.10, step="mid", lw=0)
    ax2.set_ylabel("drawdown (%)"); ax2.set_ylim(-40, 2)
    ax2.set_title("Book drawdown — red bands = clustered-exit months (mostly GFC 2008-09, 2015-16, 2020, 2022)", fontsize=10)
    ax2.legend(loc="lower left", fontsize=9, ncol=3)
    fig.tight_layout()
    fig.savefig(ASSETS / "fig6_clustered_exit.png"); plt.close(fig)


def fig7_robustness(ref="10"):
    r = json.loads(WS2.read_text(encoding="utf-8"))
    schemes = [("equal_weight", "Equal-weight"),
               ("inverse_vol", "Inverse-vol"),
               ("narrowed_trend_strong", "Narrowed")]
    variants = ["B", "C", "D", "E"]
    sharpe = {s: [r["schemes"][s]["by_cost"][ref][v]["sharpe"] for v in variants] for s, _ in schemes}
    maxdd = {s: [r["schemes"][s]["by_cost"][ref][v]["max_dd"] * 100 for v in variants] for s, _ in schemes}

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 5.6))
    x = np.arange(len(schemes)); w = 0.2
    for i, v in enumerate(variants):
        vals = [sharpe[s][i] for s, _ in schemes]
        ax1.bar(x + (i - 1.5) * w, vals, w, color=VAR_COLOURS[v], label=LBL[v])
    ax1.set_xticks(x); ax1.set_xticklabels([lbl for _, lbl in schemes])
    ax1.set_ylabel("Sharpe (net 10 bps)"); ax1.set_title("Sharpe — per-asset edge over C collapses off equal-weight")
    ax1.legend(fontsize=8, ncol=2)
    for i, v in enumerate(variants):
        vals = [maxdd[s][i] for s, _ in schemes]
        ax2.bar(x + (i - 1.5) * w, vals, w, color=VAR_COLOURS[v])
    ax2.set_xticks(x); ax2.set_xticklabels([lbl for _, lbl in schemes])
    ax2.set_ylabel("max drawdown (%)"); ax2.set_title("Max drawdown by scheme")
    fig.tight_layout()
    fig.savefig(ASSETS / "fig7_robustness_bars.png"); plt.close(fig)


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    levels = E.load_panel()
    cash_ret = E.monthly_returns(levels[E.CASH_BLOCK]).dropna()
    fig6_clustered_exit(levels, cash_ret)
    fig7_robustness()
    print("wrote fig6_clustered_exit.png, fig7_robustness_bars.png")


if __name__ == "__main__":
    main()
