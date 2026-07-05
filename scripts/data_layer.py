"""WS0 — spliced total-return data layer for the nine SAA building blocks.

For each block we build one monthly total-return series: a pre-ETF PROXY
(index / spot / ETF-bridge / SYNTHETIC) chained on RETURNS to the actual ETF
from its inception. Splicing on returns (not price levels) means the join can
never inject a level jump; the remaining risk is a returns BASIS between proxy
and ETF, which we measure directly by regressing ETF monthly returns on proxy
monthly returns over their overlap window (β≈1, α≈0, high correlation = clean).

This is the countermeasure to silent-failure mode #1 (splice basis). Nothing
downstream trusts a proxy whose overlap reconciliation is weak — the flag is
printed and stored so WS1/WS2 can restrict to clean sleeves if needed.

Outputs:
  results/ws0_data_layer.json   — per-block dates, labels, reconciliation stats
  data/panel_monthly.csv        — the spliced monthly TR levels, all 9 blocks
Run:  python scripts/data_layer.py
"""
from __future__ import annotations

import datetime as dt   # Python datetime: months are 1-indexed
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import linregress

import norgate_io as io

ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = ROOT / "results" / "ws0_data_layer.json"
OUT_PANEL = ROOT / "data" / "panel_monthly.csv"


@dataclass(frozen=True)
class Block:
    name: str
    etf: str
    proxy_kind: str          # index | etf_bridge | synth_bond | synth_bill
    proxy_sym: str
    maturity: float = 0.0    # years, synth_bond only
    is_risk: bool = True     # False for the cash leg


# Policy: clean deep proxies where they exist; ETF-bridge for the two
# international blocks (no EAFE/EM index in Norgate); SYNTHETIC for the two
# Treasury blocks (ICE TR indices start later than the ETFs) and for cash.
BLOCKS = [
    Block("US equity",         "SPY", "index",      "$SPXTR"),
    Block("Dev ex-US equity",  "EFA", "etf_only", "EFA"),   # A1: EFA held outright (no VEA splice)
    Block("EM equity",         "EEM", "etf_only", "EEM"),   # A1: EEM held outright (no VWO splice)
    Block("Long Treasuries",   "TLT", "synth_bond", "%30YTCM", maturity=25.0),
    Block("Interm Treasuries", "IEF", "synth_bond", "%10YTCM", maturity=8.5),
    Block("REITs",             "VNQ", "index",      "$DWRTFT"),
    Block("Broad commodity",   "DBC", "index",      "$BCOMTR"),
    Block("Gold",              "GLD", "index",      "XAUUSD"),
    Block("Cash (3m bill)",    "BIL", "synth_bill", "%IRX", is_risk=False),
]

MONTH_END = "ME"  # pandas 3.0 month-end alias ('M' was removed)


def _monthly_returns(level_daily_or_monthly: pd.Series, already_monthly=False):
    lvl = (level_daily_or_monthly if already_monthly
           else level_daily_or_monthly.resample(MONTH_END).last())
    return lvl.pct_change(fill_method=None).dropna()


def _proxy_monthly_returns(b: Block) -> tuple[pd.Series, str]:
    if b.proxy_kind == "index":
        s = io.index_daily(b.proxy_sym)
        return _monthly_returns(s), io_name(b.proxy_sym)
    if b.proxy_kind == "etf_bridge":
        s = io.etf_tr_daily(b.proxy_sym)
        return _monthly_returns(s), io_name(b.proxy_sym)
    if b.proxy_kind == "etf_only":
        # A1: the block IS the ETF; no distinct proxy, no splice, no reconciliation.
        s = io.etf_tr_daily(b.proxy_sym)
        return _monthly_returns(s), f"{b.proxy_sym} (fund itself, no proxy)"
    if b.proxy_kind == "synth_bond":
        lvl = io.synth_bond_tr_monthly(io.yield_daily(b.proxy_sym), b.maturity)
        return _monthly_returns(lvl, already_monthly=True), \
            f"SYNTH par-bond M={b.maturity:g}y from {b.proxy_sym}"
    if b.proxy_kind == "synth_bill":
        lvl = io.bill_tr_from_yield(io.yield_daily(b.proxy_sym))
        return _monthly_returns(lvl), f"SYNTH 3m-bill TR from {b.proxy_sym}"
    raise ValueError(b.proxy_kind)


def io_name(sym: str) -> str:
    import norgatedata as nd
    try:
        return nd.security_name(sym)
    except Exception:  # noqa: BLE001
        return sym


def _flag(kind: str, corr: float, beta: float) -> str:
    if corr >= 0.95 and abs(beta - 1.0) <= 0.15:
        return "clean"
    if corr >= 0.80:
        return "basis"      # correlated but a real construction difference
    return "weak"           # do not trust the pre-ETF segment


def build_block(b: Block) -> dict:
    etf_daily = io.etf_tr_daily(b.etf)
    etf_ret = _monthly_returns(etf_daily)
    proxy_ret, proxy_name = _proxy_monthly_returns(b)

    splice_month = etf_ret.index[0]          # first full ETF return month
    pre = proxy_ret[proxy_ret.index < splice_month]
    spliced_ret = pd.concat([pre, etf_ret]).sort_index()
    spliced_ret = spliced_ret[~spliced_ret.index.duplicated(keep="last")]
    level = (1.0 + spliced_ret).cumprod()

    # overlap reconciliation: ETF vs proxy on the SAME months.
    # etf_only blocks (A1) have no distinct proxy, so reconciliation is n/a.
    if b.proxy_kind == "etf_only":
        ov = pd.DataFrame(columns=["etf", "proxy"])
        beta = alpha_ann = corr = te_ann = float("nan")
    else:
        ov = pd.DataFrame({"etf": etf_ret, "proxy": proxy_ret}).dropna()
        if len(ov) >= 12:
            lr = linregress(ov["proxy"], ov["etf"])
            beta, alpha_ann, corr = float(lr.slope), float(lr.intercept) * 12.0, float(lr.rvalue)
            te_ann = float((ov["etf"] - ov["proxy"]).std() * np.sqrt(12))
        else:
            beta = alpha_ann = corr = te_ann = float("nan")

    labels = pd.Series(np.where(spliced_ret.index < splice_month, "PROXY", "ETF-ERA"),
                       index=spliced_ret.index)
    return {
        "block": b.name, "etf": b.etf, "is_risk": b.is_risk,
        "proxy_sym": b.proxy_sym, "proxy_kind": b.proxy_kind,
        "proxy_name": proxy_name,
        "series_start": str(level.index[0].date()),
        "etf_inception_month": str(splice_month.date()),
        "series_end": str(level.index[-1].date()),
        "n_months": int(len(level)),
        "n_proxy_months": int((labels == "PROXY").sum()),
        "overlap_n": int(len(ov)),
        "recon_beta": round(beta, 3) if beta == beta else None,
        "recon_alpha_ann": round(alpha_ann, 4) if alpha_ann == alpha_ann else None,
        "recon_corr": round(corr, 3) if corr == corr else None,
        "recon_tracking_err_ann": round(te_ann, 4) if te_ann == te_ann else None,
        "recon_flag": _flag(b.proxy_kind, corr, beta) if corr == corr else "n/a",
        "_level": level, "_labels": labels,
        "_last_daily": etf_daily.index[-1],  # popped before JSON
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    io.status_or_die()

    rows = [build_block(b) for b in BLOCKS]

    # Drop any trailing INCOMPLETE month: a monthly bucket is kept only once its
    # month-end has actually elapsed in the data (label <= latest real daily bar).
    # Stops a partial current month carrying a future-dated month-end label into
    # the metrics (vault date rule). pandas Timestamps compared directly.
    cutoff = max(r["_last_daily"] for r in rows)
    for r in rows:
        r["_level"] = r["_level"][r["_level"].index <= cutoff]
        r["_labels"] = r["_labels"][r["_labels"].index <= cutoff]
        r["series_end"] = str(r["_level"].index[-1].date())
        r["n_months"] = int(len(r["_level"]))
        r["n_proxy_months"] = int((r["_labels"] == "PROXY").sum())

    # assemble the monthly TR-level panel
    panel = pd.DataFrame({r["block"]: r["_level"] for r in rows}).sort_index()
    OUT_PANEL.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(OUT_PANEL, float_format="%.10g")

    risk_starts = {r["block"]: r["series_start"] for r in rows if r["is_risk"]}
    common_start = max(risk_starts.values())

    # print splice report
    print(f"{'block':<18}{'ETF':<5}{'proxy':<11}{'kind':<11}"
          f"{'start':<12}{'splice':<12}{'ov':>4}{'β':>7}{'α/yr':>8}{'corr':>7}{'flag':>7}")
    for r in rows:
        print(f"{r['block']:<18}{r['etf']:<5}{r['proxy_sym']:<11}{r['proxy_kind']:<11}"
              f"{r['series_start']:<12}{r['etf_inception_month']:<12}"
              f"{r['overlap_n']:>4}{_fmt(r['recon_beta']):>7}"
              f"{_fmt(r['recon_alpha_ann'], pct=True):>8}{_fmt(r['recon_corr']):>7}"
              f"{r['recon_flag']:>7}")
    print(f"\ncommon full-base start (risk blocks): {common_start}")
    print(f"panel: {panel.shape[0]} months x {panel.shape[1]} blocks -> {OUT_PANEL.relative_to(ROOT)}")

    for r in rows:
        r.pop("_level"); r.pop("_labels"); r.pop("_last_daily")
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "computed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "policy": "clean proxies + ETF-bridge intl + SYNTHETIC treasuries/bill; return-chain splice",
        "common_full_base_start": common_start,
        "blocks": rows,
    }, indent=1), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(ROOT)}")
    return 0


def _fmt(x, pct=False):
    if x is None:
        return "n/a"
    return f"{x*100:+.1f}%" if pct else f"{x:.2f}"


if __name__ == "__main__":
    sys.exit(main())
