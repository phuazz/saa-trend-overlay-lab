"""WS1 charts — white/light theme (vault default). Internal review figures.

Produces:
  fig1_spliced_equity_curves.png  — the 8 spliced block TR series, deep history,
                                     PROXY era dashed / ETF era solid (log scale)
  fig2_portfolio_equity_drawdown.png — B/C/D/E cumulative + underwater (2004→)
  fig3_rolling_sharpe.png         — rolling 36-month Sharpe, B/C/D/E
  fig4_inmarket_shading.png       — per-sleeve level with out-of-market shading
  fig5_variantA_us_equity.png     — variant A (US equity) overlay vs buy&hold,
                                     deep history, equity + drawdown

Norgate personal-use licence: these are INTERNAL review charts (curves are
derived strategy/overlay output). No raw vendor levels are published anywhere.

Run:  python scripts/ws1_charts.py
"""
from __future__ import annotations

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
COST = E.DEFAULT_COST_BPS

# ---- white theme ----
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


def _portfolio_series(levels, cash_ret):
    """Net return + cumulative level for B/C/D/E over the common window @COST."""
    rets = E.monthly_returns(levels[E.RISK_BLOCKS])
    W = {"B": E.weights_B(levels), "C": E.weights_C(levels),
         "D": E.weights_D(levels), "E": E.weights_E(levels)}
    common = W["B"].index
    for k in ("C", "D", "E"):
        common = common.intersection(W[k].index)
    out = {}
    for name, w in W.items():
        a = E.assemble(w.loc[common], rets, cash_ret, COST)
        out[name] = a.net
    return pd.DataFrame(out), common


def fig1_spliced(levels):
    inception = E.etf_inception()
    fig, ax = plt.subplots(figsize=(11, 6.2))
    cmap = plt.get_cmap("tab10")
    for i, b in enumerate(E.RISK_BLOCKS):
        s = levels[b].dropna()
        s = s / s.iloc[0]
        cut = pd.Timestamp(inception[b])
        pre, post = s[s.index < cut], s[s.index >= cut]
        c = cmap(i % 10)
        if len(pre):
            ax.plot(pre.index, pre.values, color=c, lw=1.1, ls="--", alpha=0.9)
            # bridge the dashed→solid join
            join = s[(s.index >= cut)].head(1)
            ax.plot(pd.concat([pre.tail(1), join]).index,
                    pd.concat([pre.tail(1), join]).values, color=c, lw=1.1, ls="--", alpha=0.9)
        ax.plot(post.index, post.values, color=c, lw=1.6, label=f"{b}")
    ax.set_yscale("log")
    ax.set_title("Spliced total-return building blocks — dashed = PROXY era, solid = ETF era")
    ax.set_ylabel("growth of 1 (log, each from its own start)")
    ax.legend(ncol=2, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(ASSETS / "fig1_spliced_equity_curves.png"); plt.close(fig)


def fig2_portfolio(port):
    lvl = (1.0 + port).cumprod()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7.6), height_ratios=[2, 1], sharex=True)
    for name in ("B", "C", "D", "E"):
        ax1.plot(lvl.index, lvl[name], color=VAR_COLOURS[name], lw=1.7, label=_label(name))
    ax1.set_yscale("log"); ax1.set_ylabel("growth of 1 (log)")
    ax1.set_title(f"Portfolio variants — net of {COST:.0f} bps, common window "
                  f"{lvl.index[0].date()} → {lvl.index[-1].date()}")
    ax1.legend(ncol=2, fontsize=9)
    for name in ("B", "C", "D", "E"):
        dd = E.drawdown(lvl[name]) * 100.0
        ax2.plot(dd.index, dd.values, color=VAR_COLOURS[name], lw=1.3)
        ax2.fill_between(dd.index, dd.values, 0, color=VAR_COLOURS[name], alpha=0.08)
    ax2.set_ylabel("drawdown (%)"); ax2.set_title("Underwater", fontsize=10)
    fig.tight_layout()
    fig.savefig(ASSETS / "fig2_portfolio_equity_drawdown.png"); plt.close(fig)


def fig3_rolling_sharpe(port, cash_ret, win=36):
    ex = port.sub(cash_ret.reindex(port.index), axis=0)
    roll = (ex.rolling(win).mean() / ex.rolling(win).std(ddof=1)) * np.sqrt(12)
    fig, ax = plt.subplots(figsize=(11, 5.4))
    for name in ("B", "C", "D", "E"):
        ax.plot(roll.index, roll[name], color=VAR_COLOURS[name], lw=1.6, label=_label(name))
    ax.axhline(0, color="#999999", lw=0.9)
    ax.set_title(f"Rolling {win//12}-year Sharpe (excess of cash, net of {COST:.0f} bps)")
    ax.set_ylabel("annualised Sharpe"); ax.legend(ncol=2, fontsize=9)
    fig.tight_layout()
    fig.savefig(ASSETS / "fig3_rolling_sharpe.png"); plt.close(fig)


def fig4_shading(levels):
    fig, axes = plt.subplots(4, 2, figsize=(12, 11), sharex=False)
    for ax, b in zip(axes.ravel(), E.RISK_BLOCKS):
        s = levels[b].dropna()
        pos = overlay.in_market_position(s, E.SMA_WINDOW).reindex(s.index)
        sma = overlay.sma(s, E.SMA_WINDOW)
        ax.plot(s.index, s.values, color="#1F77B4", lw=1.0)
        ax.plot(sma.index, sma.values, color="#D62728", lw=0.9, alpha=0.7)
        ax.set_yscale("log")
        # shade months the overlay is OUT of the market (position 0)
        out = (pos == 0.0)
        ax.fill_between(s.index, s.min(), s.max(), where=out.values,
                        color="#CCCCCC", alpha=0.55, step="mid", lw=0)
        tim = float(pos.mean()) * 100.0
        ax.set_title(f"{b}  —  in-market {tim:.0f}%", fontsize=10)
    fig.suptitle("Per-asset overlay: price (blue), 10m SMA (red), grey = out-of-market",
                 fontsize=12, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    fig.savefig(ASSETS / "fig4_inmarket_shading.png"); plt.close(fig)


def fig5_variantA(levels, cash_ret):
    b = E.US_EQUITY
    s = levels[b].dropna()
    r = E.monthly_returns(levels[[b]])
    W_ov = E.weights_single_sleeve(levels, b)
    ov = E.assemble(W_ov, r, cash_ret, COST)
    W_bh = E.buy_hold_sleeve(levels, b)
    bh = E.assemble(W_bh, r, cash_ret, 0.0)
    idx = ov.net.index
    ov_lvl = (1 + ov.net).cumprod()
    bh_lvl = (1 + bh.net.reindex(idx)).cumprod()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7.6), height_ratios=[2, 1], sharex=True)
    ax1.plot(ov_lvl.index, ov_lvl, color="#D62728", lw=1.7, label="Variant A — 10m overlay")
    ax1.plot(bh_lvl.index, bh_lvl, color="#888888", lw=1.5, label="US equity buy & hold")
    ax1.set_yscale("log"); ax1.set_ylabel("growth of 1 (log)")
    ax1.set_title(f"Variant A — US equity trend overlay vs buy & hold (net {COST:.0f} bps), "
                  f"{idx[0].date()} → {idx[-1].date()}")
    ax1.legend(fontsize=9)
    ax2.plot(ov_lvl.index, E.drawdown(ov_lvl)*100, color="#D62728", lw=1.2)
    ax2.plot(bh_lvl.index, E.drawdown(bh_lvl)*100, color="#888888", lw=1.2)
    ax2.fill_between(ov_lvl.index, E.drawdown(ov_lvl)*100, 0, color="#D62728", alpha=0.08)
    ax2.set_ylabel("drawdown (%)"); ax2.set_title("Underwater", fontsize=10)
    fig.tight_layout()
    fig.savefig(ASSETS / "fig5_variantA_us_equity.png"); plt.close(fig)


def _label(name):
    return {"B": "B — plain base", "C": "C — single overlay",
            "D": "D — per-asset binary", "E": "E — per-asset graduated"}[name]


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    levels = E.load_panel()
    cash_ret = E.monthly_returns(levels[E.CASH_BLOCK]).dropna()
    port, _ = _portfolio_series(levels, cash_ret)

    fig1_spliced(levels)
    fig2_portfolio(port)
    fig3_rolling_sharpe(port, cash_ret)
    fig4_shading(levels)
    fig5_variantA(levels, cash_ret)
    print(f"wrote 5 figures to {ASSETS.relative_to(ROOT)}/")
    for p in sorted(ASSETS.glob("*.png")):
        print(f"  {p.name}  ({p.stat().st_size//1024} KB)")


if __name__ == "__main__":
    main()
