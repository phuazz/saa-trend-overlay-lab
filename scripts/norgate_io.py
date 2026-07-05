"""Norgate loaders and pre-ETF proxy constructors for the SAA overlay study.

All series are returned as pandas Series indexed by a DatetimeIndex. Total
return everywhere: ETFs via Norgate's TOTALRETURN adjustment, indices that are
already TR by construction ($SPXTR, $DWRTFT, $BCOMTR), gold spot (≈TR for a
zero-yield asset), and two MODELLED series clearly flagged as SYNTHETIC:
  - a 3-month T-bill total-return index compounded from the 13-week bill yield;
  - a constant-maturity par-bond total-return index from a CMT yield.

Both synthetics are validated by return-chain reconciliation against the actual
ETF over the overlap window in data_layer.py — they are never trusted blind.

Norgate symbol conventions: '$' index, '%' yield, plain = US equity/ETF.
Python datetime months are 1-indexed (pandas handles the resampling).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import norgatedata as nd


def status_or_die() -> None:
    if not nd.status():
        raise RuntimeError("NDU is not running — data layer cannot be built")


def _close(sym: str, *, total_return: bool) -> pd.Series:
    """Daily close for a symbol. total_return applies the stock TR adjustment
    (ETFs only); indices/yields/forex are pulled unadjusted. No start_date is
    passed, so the full available history is returned (avoids the API
    default-start truncation documented in em-rotation-lab step 0)."""
    kwargs = dict(padding_setting=nd.PaddingType.NONE,
                  timeseriesformat="pandas-dataframe")
    if total_return:
        kwargs["stock_price_adjustment_setting"] = \
            nd.StockPriceAdjustmentType.TOTALRETURN
    df = nd.price_timeseries(sym, **kwargs)
    if df is None or len(df) == 0:
        raise ValueError(f"empty series for {sym}")
    s = df["Close"].copy()
    s.index = pd.DatetimeIndex(df.index).normalize()
    s.name = sym
    return s


def etf_tr_daily(sym: str) -> pd.Series:
    """Total-return daily level for an ETF."""
    return _close(sym, total_return=True)


def index_daily(sym: str) -> pd.Series:
    """Daily level for an index / spot rate (already TR or price as noted)."""
    return _close(sym, total_return=False)


def yield_daily(sym: str) -> pd.Series:
    """Daily yield in PERCENT for a '%'-prefixed Norgate yield series."""
    return _close(sym, total_return=False)


def bill_tr_from_yield(yld_pct: pd.Series) -> pd.Series:
    """3m T-bill total-return level from an annualised bill yield (percent).

    TR_t = TR_{t-1} × (1 + y_{t-1} × Δdays/365). Actual/365 accrual on the
    prior day's quoted yield. Level normalised to 1.0 at the first date. This
    is the standard cash-proxy construction; reconciled to BIL in the overlap.
    """
    y = (yld_pct / 100.0).astype(float)
    idx = y.index
    dt_days = idx.to_series().diff().dt.days.fillna(1.0).clip(lower=1.0)
    accrual = 1.0 + y.shift(1).fillna(0.0).to_numpy() * (dt_days.to_numpy() / 365.0)
    level = pd.Series(np.cumprod(accrual), index=idx, name="bill_tr")
    return level / level.iloc[0]


def _par_bond_dur_conv(y: float, maturity_years: float) -> tuple[float, float]:
    """Modified duration and convexity of a par bond at yield y (decimal),
    semiannual coupons, computed numerically by ±1bp repricing. At par the
    coupon equals the yield, so this is the constant-maturity par-bond point."""
    n = max(1, int(round(maturity_years * 2)))
    cpn = 100.0 * (y / 2.0)  # par coupon per semiannual period

    def price(yld: float) -> float:
        j = yld / 2.0
        t = np.arange(1, n + 1)
        return float(np.sum(cpn / (1 + j) ** t) + 100.0 / (1 + j) ** n)

    d = 1e-4
    p0, pu, pd_ = price(y), price(y + d), price(y - d)
    mod_dur = -(pu - pd_) / (2 * d * p0)
    convexity = (pu + pd_ - 2 * p0) / (p0 * d * d)
    return mod_dur, convexity


def synth_bond_tr_monthly(cmt_yield_pct_daily: pd.Series,
                          maturity_years: float) -> pd.Series:
    """Constant-maturity par-bond total-return level, MONTHLY.

    r_t ≈ y_{t-1}/12  (carry)  − D·Δy  + ½·C·Δy²   (price)
    with D, C the modified duration and convexity of a par bond of the given
    maturity at the prevailing yield, Δy the month-on-month yield change in
    decimal. A documented approximation to a constant-maturity bond return,
    used to extend TLT/IEF before 2002. Labelled SYNTHETIC; validated against
    the ETF in the overlap window before any pre-ETF use.
    """
    ym = (cmt_yield_pct_daily.resample("ME").last() / 100.0).astype(float)
    ym = ym.dropna()
    rets = []
    dates = []
    prev_y = None
    for date, y in ym.items():
        if prev_y is not None:
            dy = y - prev_y
            mod_dur, convexity = _par_bond_dur_conv(prev_y, maturity_years)
            r = prev_y / 12.0 - mod_dur * dy + 0.5 * convexity * dy * dy
            rets.append(r)
            dates.append(date)
        prev_y = y
    monthly_ret = pd.Series(rets, index=pd.DatetimeIndex(dates), name="synth_bond_ret")
    level = (1.0 + monthly_ret).cumprod()
    return level / level.iloc[0]
