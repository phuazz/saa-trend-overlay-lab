"""WS1 — long-history concept validation for the Faber SAA trend overlay.

Two things WS1 must show (PRE_REGISTRATION.md §6):
  1. The overlay concept holds over LONG history, pre-ETF-era — carried by
     variant A (US equity, deep to ~1989) and the eight per-sleeve overlays,
     each over its OWN full history (five reach 1962–1996) with metrics split
     PROXY-era vs ETF-ERA. If the mechanism only "worked" after 2008 it would
     show up as an ETF-era-only edge.
  2. Variants A–E behave as specified. B–E as full nine-block portfolios can
     only start once every risk block exists (EEM warm-up → 2004-03), so they
     are reported over that common window as the base for WS2.

Metrics: CAGR, vol, Sharpe, Sortino, max DD, Ulcer, time-in-market %, whipsaw
round-trips per decade; plus aggregate turnover for the portfolios. Costs swept
0/5/10/20 bps one-way; the frozen decision rule references 10 bps.

Outputs (session-recovery checkpoint):
  results/ws1_metrics.csv     — one tidy row per (group, name, segment, cost)
  results/ws1_results.json    — nested metrics + parameters + windows
Run:  python scripts/run_ws1.py
"""
from __future__ import annotations

import datetime as dt   # Python datetime: months are 1-indexed
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import engine as E
import overlay

ROOT = Path(__file__).resolve().parent.parent
OUT_CSV = ROOT / "results" / "ws1_metrics.csv"
OUT_JSON = ROOT / "results" / "ws1_results.json"


def _agg_whipsaw_per_decade(binary_positions: list[pd.Series], idx: pd.Index) -> float:
    """Total binary round-trips per decade summed across several sleeves."""
    total = 0
    for p in binary_positions:
        p = p.reindex(idx).dropna()
        total += int((p.diff().abs() > 1e-9).sum())
    decades = len(idx) / (E.MONTHS_PER_YEAR * 10)
    return float((total / 2.0) / decades) if decades > 0 else float("nan")


def sleeve_block(levels: pd.DataFrame, cash_ret: pd.Series, block: str,
                 inception: str, cost_bps: float) -> dict:
    """Overlay-vs-buy&hold for one block over its full history, plus the
    PROXY/ETF-ERA split that answers 'does it hold pre-ETF?'."""
    rets = E.monthly_returns(levels[[block]])

    W_ov = E.weights_single_sleeve(levels, block)          # binary, lagged
    ov = E.assemble(W_ov, rets, cash_ret, cost_bps)
    pos = W_ov[block]

    W_bh = E.buy_hold_sleeve(levels, block)
    bh = E.assemble(W_bh, rets, cash_ret, 0.0)

    def _split(series: pd.Series, pos_for_wh: pd.Series | None, invested):
        # metrics() reindexes invested/pos to each segment internally, so we can
        # pass the full series and just cut the return stream at ETF inception.
        cut = pd.Timestamp(inception)
        pre = series[series.index < cut]
        post = series[series.index >= cut]
        res = {}
        if len(pre) >= 24:      # need a couple of years to be worth quoting
            res["proxy"] = E.metrics(pre, cash_ret, invested, pos_for_wh)
        if len(post) >= 24:
            res["etf"] = E.metrics(post, cash_ret, invested, pos_for_wh)
        return res

    return {
        "block": block,
        "etf_inception": inception,
        "overlay": E.metrics(ov.net, cash_ret, ov.invested, pos),
        "buy_hold": E.metrics(bh.net, cash_ret, bh.invested, None),
        "overlay_split": _split(ov.net, pos, ov.invested),
        "buy_hold_split": _split(bh.net, None, bh.invested),
    }


def portfolios(levels: pd.DataFrame, cash_ret: pd.Series) -> dict:
    """B, C, D, E over the common post-warm-up window, at each cost point."""
    rets = E.monthly_returns(levels[E.RISK_BLOCKS])

    W = {
        "B": E.weights_B(levels),
        "C": E.weights_C(levels),
        "D": E.weights_D(levels),
        "E": E.weights_E(levels),
    }
    common = W["B"].index
    for k in ("C", "D", "E"):
        common = common.intersection(W[k].index)
    W = {k: v.loc[common] for k, v in W.items()}

    # per-block binary positions for the aggregate-whipsaw diagnostic
    binpos = {b: overlay.in_market_position(levels[b].dropna(), E.SMA_WINDOW)
              for b in E.RISK_BLOCKS}
    base = E.base_index_from_B(levels)
    pos_base = overlay.in_market_position(base, E.SMA_WINDOW)

    out = {"common_window": [str(common[0].date()), str(common[-1].date())],
           "by_cost": {}}
    for bps in E.COST_SWEEP_BPS:
        block_res = {}
        for name, w in W.items():
            a = E.assemble(w, rets, cash_ret, bps)
            m = E.metrics(a.net, cash_ret, a.invested, None)
            m["gross_cagr"] = E.metrics(a.gross, cash_ret)["cagr"]
            m["ann_turnover"] = float(a.turnover.mean() * E.MONTHS_PER_YEAR)
            if name == "B":
                m["whipsaw_roundtrips_per_decade"] = 0.0
            elif name == "C":
                m["whipsaw_roundtrips_per_decade"] = \
                    _agg_whipsaw_per_decade([pos_base], common)
            elif name == "D":
                m["whipsaw_roundtrips_per_decade"] = \
                    _agg_whipsaw_per_decade(list(binpos.values()), common)
            else:  # E — binarise the graduated exposure at 0.5 for a flip count
                bins = [(binpos[b] > 0.5).astype(float) for b in E.RISK_BLOCKS]
                m["whipsaw_roundtrips_per_decade"] = _agg_whipsaw_per_decade(bins, common)
            block_res[name] = m
        out["by_cost"][str(int(bps))] = block_res
    return out


def _flatten(results: dict) -> pd.DataFrame:
    rows = []

    def push(group, name, segment, cost_bps, m):
        rows.append({"group": group, "name": name, "segment": segment,
                     "cost_bps": cost_bps, **m})

    a = results["variant_A"]
    push("A", "US equity overlay", "full", E.DEFAULT_COST_BPS, a["overlay"])
    push("A", "US equity buy&hold", "full", 0, a["buy_hold"])
    for seg, mm in a["overlay_split"].items():
        push("A", "US equity overlay", seg, E.DEFAULT_COST_BPS, mm)

    for block, s in results["sleeves"].items():
        push("sleeve", f"{block} overlay", "full", E.DEFAULT_COST_BPS, s["overlay"])
        push("sleeve", f"{block} buy&hold", "full", 0, s["buy_hold"])
        for seg, mm in s["overlay_split"].items():
            push("sleeve", f"{block} overlay", seg, E.DEFAULT_COST_BPS, mm)

    for bps, blocks in results["portfolios"]["by_cost"].items():
        for name, m in blocks.items():
            push("portfolio", name, "common", int(bps), m)

    df = pd.DataFrame(rows)
    front = ["group", "name", "segment", "cost_bps", "start", "end", "n_months",
             "cagr", "vol", "sharpe", "sortino", "max_dd", "ulcer",
             "time_in_market", "whipsaw_roundtrips_per_decade",
             "ann_turnover", "gross_cagr"]
    cols = [c for c in front if c in df.columns] + \
           [c for c in df.columns if c not in front]
    return df[cols]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    levels = E.load_panel()
    cash_ret = E.monthly_returns(levels[E.CASH_BLOCK]).dropna()
    inception = E.etf_inception()

    # variant A == the US-equity sleeve overlay (deep), highlighted separately
    variant_A = sleeve_block(levels, cash_ret, E.US_EQUITY,
                             inception[E.US_EQUITY], E.DEFAULT_COST_BPS)

    sleeves = {}
    for b in E.RISK_BLOCKS:
        sleeves[b] = sleeve_block(levels, cash_ret, b, inception[b], E.DEFAULT_COST_BPS)

    ports = portfolios(levels, cash_ret)

    results = {
        "computed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "params": {
            "sma_window_months": E.SMA_WINDOW,
            "graduated_band": E.GRAD_BAND,
            "cost_sweep_bps": list(E.COST_SWEEP_BPS),
            "reference_cost_bps": E.DEFAULT_COST_BPS,
            "strategic_weight": "equal-weight 8 risk blocks (12.5% each)",
            "cash_leg": "spliced BIL / 3m T-bill total return",
            "signal_timing": "signal through month-end t, position lagged one month (earns t+1)",
        },
        "variant_A": variant_A,
        "sleeves": sleeves,
        "portfolios": ports,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(results, indent=1, default=float), encoding="utf-8")
    df = _flatten(results)
    df.to_csv(OUT_CSV, index=False, float_format="%.4f")

    # ---- console summary ----
    print("=" * 78)
    print("WS1 — deep per-sleeve concept (overlay @10bps vs buy&hold, full history)")
    print("=" * 78)
    hdr = f"{'sleeve':<18}{'start':<9}{'CAGR':>7}{'vol':>7}{'Shrp':>6}{'MaxDD':>7}{'Ulcer':>7}{'TIM':>6}{'wh/dec':>7}"
    print(hdr)
    for b in [E.US_EQUITY] + [x for x in E.RISK_BLOCKS if x != E.US_EQUITY]:
        for tag, m in (("ov", sleeves.get(b, variant_A)["overlay"] if b != E.US_EQUITY else variant_A["overlay"]),
                       ("bh", sleeves.get(b, variant_A)["buy_hold"] if b != E.US_EQUITY else variant_A["buy_hold"])):
            label = f"{b[:15]} {tag}"
            print(f"{label:<18}{m['start'][:7]:<9}{m['cagr']*100:>6.1f}%{m['vol']*100:>6.1f}%"
                  f"{m['sharpe']:>6.2f}{m['max_dd']*100:>6.1f}%{m['ulcer']:>7.1f}"
                  f"{m.get('time_in_market', 1.0)*100:>5.0f}%"
                  f"{m.get('whipsaw_roundtrips_per_decade', float('nan')):>7.1f}")

    print("\nPROXY-era vs ETF-era (overlay), does the edge predate the ETF?")
    print(f"{'sleeve':<18}{'era':<7}{'CAGR':>7}{'Shrp':>6}{'MaxDD':>7}")
    for b in ([E.US_EQUITY] + [x for x in E.RISK_BLOCKS if x != E.US_EQUITY]):
        s = variant_A if b == E.US_EQUITY else sleeves[b]
        for era in ("proxy", "etf"):
            if era in s["overlay_split"]:
                m = s["overlay_split"][era]
                print(f"{b[:15]:<18}{era:<7}{m['cagr']*100:>6.1f}%{m['sharpe']:>6.2f}{m['max_dd']*100:>6.1f}%")

    print("\n" + "=" * 78)
    print(f"Portfolios B/C/D/E — common window {ports['common_window'][0]} → {ports['common_window'][1]}")
    print("=" * 78)
    for bps in ("0", "10"):
        print(f"\n-- cost {bps} bps --")
        print(f"{'var':<4}{'CAGR':>7}{'vol':>7}{'Shrp':>6}{'Sort':>6}{'MaxDD':>7}{'Ulcer':>7}{'TIM':>6}{'turn':>7}{'wh/dec':>7}")
        for name in ("B", "C", "D", "E"):
            m = ports["by_cost"][bps][name]
            print(f"{name:<4}{m['cagr']*100:>6.1f}%{m['vol']*100:>6.1f}%{m['sharpe']:>6.2f}"
                  f"{m['sortino']:>6.2f}{m['max_dd']*100:>6.1f}%{m['ulcer']:>7.1f}"
                  f"{m['time_in_market']*100:>5.0f}%{m['ann_turnover']*100:>6.0f}%"
                  f"{m['whipsaw_roundtrips_per_decade']:>7.1f}")

    print(f"\nwrote {OUT_CSV.relative_to(ROOT)}")
    print(f"wrote {OUT_JSON.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
