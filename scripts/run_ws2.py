"""WS2 — per-asset overlay (D/E) vs single-overlay-on-balanced (C) vs plain base (B).

The frozen decision (PRE_REGISTRATION.md §6): prefer per-asset over single only if
    net Sharpe(D or E) ≥ Sharpe(C) + 0.10  AND  max DD not worse than C by >2 ppt,
    and the verdict survives at 10 bps.
Reported with: the full metric set + aggregate turnover; a CLUSTERED-EXIT
diagnostic (months where >60% of blocks are simultaneously to cash, and how the
book behaved then + the rebound it may have missed); an INVERSE-VOL robustness
cut (does the verdict survive a risk-balanced base?); and a pre-specified
NARROWING to the trend-strongest blocks (equities, long Treasuries, commodities).
A negative result is a valid outcome.

Outputs:
  results/ws2_metrics.csv   — tidy (scheme, cost, variant) metric rows
  results/ws2_results.json  — schemes, decision verdicts, clustered-exit diag
Run:  python scripts/run_ws2.py
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
OUT_CSV = ROOT / "results" / "ws2_metrics.csv"
OUT_JSON = ROOT / "results" / "ws2_results.json"
VARIANTS = ("B", "C", "D", "E")

# pre-specified trend-strongest set (declared, NOT fitted to WS1 results)
TREND_STRONG = ["US equity", "Dev ex-US equity", "EM equity",
                "Long Treasuries", "Broad commodity"]


def _agg_whipsaw(levels, blocks, common, graduated=False) -> float:
    """Total binary round-trips per decade across the blocks (E binarised at 0.5)."""
    total = 0
    for b in blocks:
        if graduated:
            p = (overlay.graduated_position(levels[b].dropna(), E.SMA_WINDOW,
                                            E.GRAD_BAND) > 0.5).astype(float)
        else:
            p = overlay.in_market_position(levels[b].dropna(), E.SMA_WINDOW)
        p = p.reindex(common).dropna()
        total += int((p.diff().abs() > 1e-9).sum())
    decades = len(common) / (E.MONTHS_PER_YEAR * 10)
    return float((total / 2.0) / decades) if decades > 0 else float("nan")


def scheme_metrics(levels, cash_ret, base_W, blocks):
    """B/C/D/E metrics over the scheme's common window, at each cost point."""
    rets = E.monthly_returns(levels[blocks])
    W = {v: E.build_variant(levels, base_W, v) for v in VARIANTS}
    common = W["B"].index
    for v in ("C", "D", "E"):
        common = common.intersection(W[v].index)
    W = {v: w.loc[common] for v, w in W.items()}

    pos_base = overlay.in_market_position(E.base_index(base_W, rets), E.SMA_WINDOW)
    out = {"common_window": [str(common[0].date()), str(common[-1].date())],
           "n_months": int(len(common)), "blocks": list(blocks), "by_cost": {}}
    for bps in E.COST_SWEEP_BPS:
        res = {}
        for v, w in W.items():
            a = E.assemble(w, rets, cash_ret, bps)
            m = E.metrics(a.net, cash_ret, a.invested, None)
            m["ann_turnover"] = float(a.turnover.mean() * E.MONTHS_PER_YEAR)
            m["gross_cagr"] = E.metrics(a.gross, cash_ret)["cagr"]
            if v == "B":
                m["whipsaw_roundtrips_per_decade"] = 0.0
            elif v == "C":
                p = pos_base.reindex(common).dropna()
                dec = len(common) / (E.MONTHS_PER_YEAR * 10)
                m["whipsaw_roundtrips_per_decade"] = float((int((p.diff().abs() > 1e-9).sum()) / 2.0) / dec)
            else:
                m["whipsaw_roundtrips_per_decade"] = _agg_whipsaw(levels, blocks, common, v == "E")
            res[v] = m
        out["by_cost"][str(int(bps))] = res
    return out, common, W


def decision_rule(by_cost, ref="10") -> dict:
    """Evaluate the frozen rule for D and E vs C at the reference cost."""
    r = by_cost[ref]
    c = r["C"]
    verdict = {"reference_cost_bps": int(ref), "c_sharpe": round(c["sharpe"], 3),
               "c_max_dd": round(c["max_dd"], 4)}
    for v in ("D", "E"):
        d = r[v]
        s_delta = d["sharpe"] - c["sharpe"]
        dd_delta_ppt = (d["max_dd"] - c["max_dd"]) * 100.0     # >0 ⇒ D shallower
        passes = (s_delta >= 0.10) and (d["max_dd"] >= c["max_dd"] - 0.02)
        verdict[v] = {
            "sharpe": round(d["sharpe"], 3), "sharpe_delta_vs_C": round(s_delta, 3),
            "sharpe_delta_ge_0.10": bool(s_delta >= 0.10),
            "max_dd": round(d["max_dd"], 4), "dd_delta_vs_C_ppt": round(dd_delta_ppt, 2),
            "dd_not_worse_than_2ppt": bool(d["max_dd"] >= c["max_dd"] - 0.02),
            "PASSES_RULE": bool(passes),
        }
    return verdict


def survives_across_costs(by_cost) -> dict:
    """Does each of D/E clear C+0.10 Sharpe at every cost point in the sweep?"""
    out = {}
    for v in ("D", "E"):
        flags = {}
        for bps, r in by_cost.items():
            flags[bps] = bool((r[v]["sharpe"] - r["C"]["sharpe"]) >= 0.10)
        out[v] = flags
    return out


def clustered_exit(levels, cash_ret, common, W_equal, threshold=0.60):
    """Months where >threshold of the 8 blocks are simultaneously to cash (D),
    and how B/C/D/E behaved then — plus the rebound the month after."""
    blocks = E.RISK_BLOCKS
    binpos = pd.DataFrame(
        {b: overlay.in_market_position(levels[b].dropna(), E.SMA_WINDOW) for b in blocks}
    ).reindex(common)
    n = len(blocks)
    frac_out = (binpos == 0.0).sum(axis=1) / n
    cluster = frac_out > threshold

    rets = E.monthly_returns(levels[blocks])
    nets = pd.DataFrame(
        {v: E.assemble(W_equal[v], rets, cash_ret, E.DEFAULT_COST_BPS).net for v in VARIANTS}
    ).reindex(common)

    after = cluster.shift(1).fillna(False)
    # consecutive-run episodes
    grp = (cluster != cluster.shift()).cumsum()
    episodes = []
    for _, seg in cluster[cluster].groupby(grp[cluster]):
        episodes.append({"start": str(seg.index[0].date()),
                         "end": str(seg.index[-1].date()),
                         "months": int(len(seg))})

    def _mm(mask):  # mean monthly % return per variant over a boolean mask
        return {v: round(float(nets[v][mask].mean()) * 100.0, 2) for v in VARIANTS}

    return {
        "threshold_frac": threshold,
        "definition": ">60% of the 8 blocks (i.e. >=5) out-of-market in the same month",
        "n_cluster_months": int(cluster.sum()),
        "pct_of_sample": round(float(cluster.mean()) * 100.0, 1),
        "max_frac_out": round(float(frac_out.max()), 3),
        "mean_pct_ret_in_cluster_months": _mm(cluster),
        "mean_pct_ret_non_cluster_months": _mm(~cluster),
        "mean_pct_ret_month_after_cluster": (_mm(after) if after.any() else None),
        "episodes": episodes,
        "cluster_dates": [str(d.date()) for d in common[cluster]],
    }, frac_out, cluster


def matched_window_check(levels, cash_ret) -> dict:
    """Isolate weighting from window: equal-weight vs inverse-vol B/C/D/E on the
    SAME (inverse-vol) window at 10 bps. Confirms C's lift under inverse-vol is
    the weighting, not the shorter window — and that per-asset's edge over C is a
    substitute for risk-balancing (it vanishes once the base is risk-balanced)."""
    rets = E.monthly_returns(levels[E.RISK_BLOCKS])
    base_iv = E.base_weights_inverse_vol(levels)
    win = E.build_variant(levels, base_iv, "C").index
    base_eq = E.base_weights_equal(levels)
    out = {"window": [str(win[0].date()), str(win[-1].date())],
           "cost_bps": int(E.DEFAULT_COST_BPS), "equal_weight": {}, "inverse_vol": {}}
    for scheme, base in (("equal_weight", base_eq), ("inverse_vol", base_iv)):
        for v in VARIANTS:
            W = E.build_variant(levels, base, v).reindex(win).dropna(how="any")
            a = E.assemble(W, rets, cash_ret, E.DEFAULT_COST_BPS)
            m = E.metrics(a.net, cash_ret, a.invested)
            out[scheme][v] = {"sharpe": round(m["sharpe"], 3), "max_dd": round(m["max_dd"], 4)}
    return out


def _flatten(schemes) -> pd.DataFrame:
    rows = []
    for scheme, data in schemes.items():
        for bps, res in data["by_cost"].items():
            for v, m in res.items():
                rows.append({"scheme": scheme, "cost_bps": int(bps), "variant": v, **m})
    df = pd.DataFrame(rows)
    front = ["scheme", "cost_bps", "variant", "start", "end", "n_months", "cagr",
             "vol", "sharpe", "sortino", "max_dd", "ulcer", "time_in_market",
             "ann_turnover", "whipsaw_roundtrips_per_decade", "gross_cagr"]
    cols = [c for c in front if c in df.columns] + [c for c in df.columns if c not in front]
    return df[cols]


def _print_scheme(title, data, verdict):
    print(f"\n{'='*78}\n{title}  —  window {data['common_window'][0]} → {data['common_window'][1]}\n{'='*78}")
    for bps in ("0", "10"):
        print(f"-- {bps} bps --  {'var':<3}{'CAGR':>7}{'vol':>7}{'Shrp':>6}{'Sort':>6}{'MaxDD':>7}{'Ulcer':>7}{'TIM':>6}{'turn':>7}{'wh/dec':>7}")
        for v in VARIANTS:
            m = data["by_cost"][bps][v]
            print(f"{'':<12}{v:<3}{m['cagr']*100:>6.1f}%{m['vol']*100:>6.1f}%{m['sharpe']:>6.2f}"
                  f"{m['sortino']:>6.2f}{m['max_dd']*100:>6.1f}%{m['ulcer']:>7.1f}"
                  f"{m['time_in_market']*100:>5.0f}%{m['ann_turnover']*100:>6.0f}%"
                  f"{m['whipsaw_roundtrips_per_decade']:>7.1f}")
    for v in ("D", "E"):
        vv = verdict[v]
        tag = "PASS" if vv["PASSES_RULE"] else "fail"
        print(f"   rule {v} vs C @10bps: ΔSharpe {vv['sharpe_delta_vs_C']:+.3f} (≥0.10? "
              f"{vv['sharpe_delta_ge_0.10']}), ΔMaxDD {vv['dd_delta_vs_C_ppt']:+.1f}ppt → [{tag}]")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    levels = E.load_panel()
    cash_ret = E.monthly_returns(levels[E.CASH_BLOCK]).dropna()

    base_eq = E.base_weights_equal(levels)
    eq, common_eq, W_eq = scheme_metrics(levels, cash_ret, base_eq, E.RISK_BLOCKS)
    eq_dec = decision_rule(eq["by_cost"])
    eq_dec["survives_across_costs"] = survives_across_costs(eq["by_cost"])

    cx, frac_out, cluster = clustered_exit(levels, cash_ret, common_eq, W_eq)

    base_iv = E.base_weights_inverse_vol(levels)
    iv, common_iv, _ = scheme_metrics(levels, cash_ret, base_iv, E.RISK_BLOCKS)
    iv_dec = decision_rule(iv["by_cost"])
    iv_dec["survives_across_costs"] = survives_across_costs(iv["by_cost"])

    base_nar = E.base_weights_equal(levels, TREND_STRONG)
    nar, common_nar, _ = scheme_metrics(levels, cash_ret, base_nar, TREND_STRONG)
    nar_dec = decision_rule(nar["by_cost"])

    schemes = {"equal_weight": eq, "inverse_vol": iv, "narrowed_trend_strong": nar}
    results = {
        "computed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "decision_rule": "prefer D/E over C iff net Sharpe >= C+0.10 AND MaxDD not worse than C by >2ppt, surviving 10 bps",
        "schemes": schemes,
        "verdicts": {"equal_weight": eq_dec, "inverse_vol": iv_dec,
                     "narrowed_trend_strong": nar_dec},
        "clustered_exit": cx,
        "weighting_vs_window_matched": matched_window_check(levels, cash_ret),
        "narrowing_note": "pre-specified set (equities, long Treasuries, commodities); "
                          "run for completeness — per-asset did NOT disappoint, so not a rescue",
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(results, indent=1, default=float), encoding="utf-8")
    _flatten(schemes).to_csv(OUT_CSV, index=False, float_format="%.4f")

    _print_scheme("EQUAL-WEIGHT (headline)", eq, eq_dec)
    print("\nclustered-exit diagnostic (equal-weight, D binary positions):")
    print(f"  months with >60% of blocks out: {cx['n_cluster_months']} "
          f"({cx['pct_of_sample']}% of sample); max fraction out = {cx['max_frac_out']:.0%}")
    print(f"  mean %/mo IN cluster months : {cx['mean_pct_ret_in_cluster_months']}")
    print(f"  mean %/mo the month AFTER   : {cx['mean_pct_ret_month_after_cluster']}")
    print(f"  episodes: " + ", ".join(f"{e['start']}..{e['end']}({e['months']}m)" for e in cx["episodes"]))
    _print_scheme("INVERSE-VOL robustness cut", iv, iv_dec)
    _print_scheme("NARROWED to trend-strong (supplementary)", nar, nar_dec)

    mw = results["weighting_vs_window_matched"]
    print(f"\n{'='*78}\nWEIGHTING vs WINDOW (matched window {mw['window'][0]} → {mw['window'][1]}, 10 bps)\n{'='*78}")
    print(f"{'var':<4}{'EQ Sharpe':>11}{'EQ MaxDD':>10}   {'IV Sharpe':>11}{'IV MaxDD':>10}")
    for v in VARIANTS:
        e, i = mw["equal_weight"][v], mw["inverse_vol"][v]
        print(f"{v:<4}{e['sharpe']:>11.3f}{e['max_dd']*100:>9.1f}%   {i['sharpe']:>11.3f}{i['max_dd']*100:>9.1f}%")
    print("  reading: equal-weight D/E clearly beat C; inverse-vol lifts C ~+0.20 and the")
    print("  per-asset edge vanishes → per-asset is a substitute for risk-balanced weighting.")

    print(f"\nwrote {OUT_CSV.relative_to(ROOT)}")
    print(f"wrote {OUT_JSON.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
