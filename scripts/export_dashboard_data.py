"""Export DERIVED dashboard series to data/dashboard.json.

Norgate personal-use licence: this file (and the dashboard) carry only DERIVED
overlay outputs — strategy growth-of-1 curves (shapes), drawdowns, overlay
in/out states, and metrics. No raw vendor series values ($SPXTR / XAUUSD /
%IRX levels) are ever exported or shown. Tables are read back from the committed
WS1/WS2 result JSONs so the page cannot drift from the filed record.

Run:  python scripts/export_dashboard_data.py
"""
from __future__ import annotations

import datetime as dt   # Python datetime: months are 1-indexed
import json
from pathlib import Path

import numpy as np
import pandas as pd

import engine as E
import overlay

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "dashboard.json"
WS1 = json.loads((ROOT / "results" / "ws1_results.json").read_text(encoding="utf-8"))
WS2 = json.loads((ROOT / "results" / "ws2_results.json").read_text(encoding="utf-8"))

COST = E.DEFAULT_COST_BPS


def _dates(idx) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in idx]


def _growth(net: pd.Series) -> list[float]:
    return [round(float(x), 4) for x in (1.0 + net).cumprod()]


def _dd(net: pd.Series) -> list[float]:
    lvl = (1.0 + net).cumprod()
    return [round(float(x) * 100.0, 2) for x in E.drawdown(lvl)]


def _assemble_scheme(levels, cash_ret, base_fn, blocks=E.RISK_BLOCKS):
    rets = E.monthly_returns(levels[blocks])
    base = base_fn(levels)
    W = {v: E.build_variant(levels, base, v) for v in ("B", "C", "D", "E")}
    common = W["B"].index
    for v in ("C", "D", "E"):
        common = common.intersection(W[v].index)
    W = {v: w.loc[common] for v, w in W.items()}
    nets = {v: E.assemble(W[v], rets, cash_ret, COST).net for v in W}
    return common, nets


def _metrics_row(m: dict) -> dict:
    return {k: round(float(m[k]), 4) for k in
            ("cagr", "vol", "sharpe", "sortino", "max_dd", "ulcer",
             "time_in_market", "ann_turnover", "whipsaw_roundtrips_per_decade")
            if k in m}


def main() -> int:
    levels = E.load_panel()
    cash_ret = E.monthly_returns(levels[E.CASH_BLOCK]).dropna()

    # ---- CONCEPT (WS1): variant A deep curve + per-sleeve table ----
    rA = E.monthly_returns(levels[[E.US_EQUITY]])
    ovA = E.assemble(E.weights_single_sleeve(levels, E.US_EQUITY), rA, cash_ret, COST)
    bhA = E.assemble(E.buy_hold_sleeve(levels, E.US_EQUITY), rA, cash_ret, 0.0)
    idxA = ovA.net.index
    variant_A = {
        # licence: publish the DERIVED overlay strategy curve + drawdowns only.
        # The raw buy-&-hold growth curve is the rebased vendor TR series, so it
        # is NOT exported — buy-&-hold appears only as a drawdown (a derived %).
        "dates": _dates(idxA),
        "overlay": _growth(ovA.net),
        "overlay_dd": _dd(ovA.net),
        "bh_dd": _dd(bhA.net.reindex(idxA)),
        "metrics": {"overlay": _metrics_row(WS1["variant_A"]["overlay"]),
                    "buy_hold": _metrics_row(WS1["variant_A"]["buy_hold"])},
    }
    sleeves = []
    for b, s in WS1["sleeves"].items():
        proxy = s["overlay_split"].get("proxy")
        sleeves.append({
            "block": b,
            "ov_sharpe": round(s["overlay"]["sharpe"], 2),
            "ov_maxdd": round(s["overlay"]["max_dd"] * 100, 1),
            "ov_tim": round(s["overlay"]["time_in_market"] * 100, 0),
            "bh_sharpe": round(s["buy_hold"]["sharpe"], 2),
            "bh_maxdd": round(s["buy_hold"]["max_dd"] * 100, 1),
            "proxy_sharpe": (round(proxy["sharpe"], 2) if proxy else None),
            "proxy_window": (f"{proxy['start'][:4]}–{proxy['end'][:4]}" if proxy else None),
            "start": s["overlay"]["start"][:4],
        })

    # ---- QUESTION (WS2 equal-weight): curves, drawdowns, metrics, decision ----
    common_eq, nets_eq = _assemble_scheme(levels, cash_ret, E.base_weights_equal)
    question = {
        "dates": _dates(common_eq),
        "curves": {v: _growth(nets_eq[v]) for v in ("B", "C", "D", "E")},
        "drawdowns": {v: _dd(nets_eq[v]) for v in ("B", "C", "D", "E")},
        "metrics": {v: _metrics_row(WS2["schemes"]["equal_weight"]["by_cost"]["10"][v])
                    for v in ("B", "C", "D", "E")},
        "window": WS2["schemes"]["equal_weight"]["common_window"],
        "decision": WS2["verdicts"]["equal_weight"],
        "cost_sweep": {bps: {v: round(WS2["schemes"]["equal_weight"]["by_cost"][bps][v]["sharpe"], 3)
                             for v in ("C", "D", "E")}
                       for bps in ("0", "5", "10", "20")},
    }
    # passive 60/40 benchmark (60% US equity / 40% interm Treasuries), monthly
    # rebalanced, gross — the "do nothing clever" reference an allocator asks for
    bench_blocks = ["US equity", "Interm Treasuries"]
    W6040 = pd.DataFrame({b: (0.6 if b == "US equity" else 0.4) for b in bench_blocks},
                         index=common_eq)
    a6040 = E.assemble(W6040, E.monthly_returns(levels[bench_blocks]), cash_ret, 0.0)
    question["benchmark"] = {
        "label": "60/40 (SPY/IEF)",
        "curve": _growth(a6040.net),
        "drawdown": _dd(a6040.net),
        "metrics": _metrics_row(E.metrics(a6040.net, cash_ret, a6040.invested)),
    }

    # ---- FINDING (inverse-vol): matched bars + ivol metrics + C curves ----
    common_iv, nets_iv = _assemble_scheme(levels, cash_ret, E.base_weights_inverse_vol)
    # C on equal vs C on inverse-vol over the IV window, to show the weighting lift
    rets = E.monthly_returns(levels[E.RISK_BLOCKS])
    C_eq_iv_win = E.assemble(E.build_variant(levels, E.base_weights_equal(levels), "C")
                             .reindex(common_iv).dropna(how="any"), rets, cash_ret, COST).net
    finding = {
        "metrics_ivol": {v: _metrics_row(WS2["schemes"]["inverse_vol"]["by_cost"]["10"][v])
                         for v in ("B", "C", "D", "E")},
        "matched": WS2["weighting_vs_window_matched"],
        "decision_ivol": WS2["verdicts"]["inverse_vol"],
        "curves": {
            "dates": _dates(common_iv),
            "C_equal": _growth(C_eq_iv_win.reindex(common_iv)),
            "C_ivol": _growth(nets_iv["C"]),
            "B_ivol": _growth(nets_iv["B"]),
        },
    }

    # ---- clustered-exit fraction-out series (derived overlay state) ----
    binpos = pd.DataFrame(
        {b: overlay.in_market_position(levels[b].dropna(), E.SMA_WINDOW) for b in E.RISK_BLOCKS}
    ).reindex(common_eq)
    frac_out = (binpos == 0.0).sum(axis=1) / len(E.RISK_BLOCKS) * 100.0
    clustered = {
        "dates": _dates(common_eq),
        "frac_out": [round(float(x), 1) for x in frac_out],
        "summary": WS2["clustered_exit"],
    }

    data = {
        "meta": {
            "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "params": WS1["params"],
            "decision_rule": WS2["decision_rule"],
            "caveats": [
                "Educational research, not investment advice.",
                "Per-asset-vs-single window 2004–2026 (EEM-bound): one GFC, one COVID, one 2022.",
                "Costs one-way, swept 0/5/10/20 bps; headline at 10 bps.",
                "Derived overlay outputs only; no vendor series values shown (Norgate personal-use licence).",
            ],
        },
        "concept": {"variant_A": variant_A, "sleeves": sleeves},
        "question": question,
        "finding": finding,
        "clustered_exit": clustered,
        "robustness": {
            "sma": WS2["sma_robustness"],
            "bootstrap": WS2["bootstrap_sharpe_diff"],
            "narrowed": WS2["verdicts"]["narrowed_trend_strong"],
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}  ({OUT.stat().st_size // 1024} KB)")
    print(f"  concept: variant A {len(idxA)} months, {len(sleeves)} sleeves")
    print(f"  question: equal-weight {question['window'][0]} -> {question['window'][1]}, {len(common_eq)} months")
    print(f"  finding: inverse-vol matched window {finding['matched']['window']}")
    print(f"  clustered-exit: {clustered['summary']['n_cluster_months']} cluster months")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
