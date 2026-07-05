"""Date-handling edge-case tests (vault rule: >=1 month boundary, >=1 year
boundary) plus the no-look-ahead guarantee on the overlay signal.

Run:  python -m pytest tests/ -q       (from the repo root)
pandas 3.0: month-end resample alias is 'ME'.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import overlay  # noqa: E402


def _daily(start: str, end: str, value=1.0) -> pd.Series:
    idx = pd.date_range(start, end, freq="D")
    return pd.Series(np.full(len(idx), value, dtype=float), index=idx)


def test_month_boundary_resample_splits_adjacent_months():
    """Days in Jan vs Feb must land in different month-end buckets, the bucket
    takes the LAST trading day in the month, and Feb 2020 labels as 29 (leap)."""
    idx = pd.to_datetime(["2020-01-30", "2020-01-31", "2020-02-27", "2020-02-28"])
    s = pd.Series([1.0, 10.0, 2.0, 20.0], index=idx)
    m = s.resample("ME").last()
    assert list(m.index.strftime("%Y-%m-%d")) == ["2020-01-31", "2020-02-29"]
    assert m.iloc[0] == 10.0                     # last Jan value (Jan 31)
    assert m.iloc[1] == 20.0                     # last Feb value present (Feb 28)


def test_year_boundary_resample_splits_dec_jan():
    """31 Dec and Jan must land in different months AND different years, each
    bucket carrying its own last trading-day value."""
    idx = pd.to_datetime(["2019-12-30", "2019-12-31", "2020-01-30", "2020-01-31"])
    s = pd.Series([1.0, 99.0, 2.0, 111.0], index=idx)
    m = s.resample("ME").last()
    assert list(m.index.strftime("%Y-%m")) == ["2019-12", "2020-01"]
    assert m.iloc[0] == 99.0                      # last Dec value (Dec 31)
    assert m.iloc[1] == 111.0                     # last Jan value (Jan 31)


def test_leap_year_month_end_is_29_feb():
    """2020 is a leap year; 2021 is not — month-end must reflect it."""
    assert _daily("2020-02-01", "2020-02-29").resample("ME").last().index[-1].day == 29
    assert _daily("2021-02-01", "2021-02-28").resample("ME").last().index[-1].day == 28


def test_signal_has_no_lookahead():
    """Perturbing the asset level in month m must NOT change the position
    applied during month m — only the position decided at m (for m+1)."""
    idx = pd.date_range("2000-01-31", periods=24, freq="ME")
    lvl = pd.Series(np.linspace(100, 130, 24), index=idx)  # steady uptrend
    base = overlay.in_market_position(lvl, window=10)

    bumped = lvl.copy()
    m = idx[15]
    bumped.loc[m] *= 1.5                          # shock month 15's level
    pert = overlay.in_market_position(bumped, window=10)

    # position DURING month 15 was decided at month 14 — must be unchanged
    assert base.loc[m] == pert.loc[m] or (np.isnan(base.loc[m]) and np.isnan(pert.loc[m]))
    # the shock may only move the position from month 16 onward
    assert base.loc[:idx[15]].equals(pert.loc[:idx[15]])


def test_position_is_lagged_one_month():
    """A level that first exceeds its SMA at month t goes in-market at t+1."""
    idx = pd.date_range("2000-01-31", periods=15, freq="ME")
    lvl = pd.Series([100]*10 + [80, 80, 80, 130, 130], index=idx, dtype=float)
    pos = overlay.in_market_position(lvl, window=10)
    # month index 13 is the first close above the 10m SMA; position turns on at 14
    assert pos.iloc[13] == 0.0
    assert pos.iloc[14] == 1.0


def test_warmup_months_are_undefined_not_zero():
    """The first `window-1` months have no SMA and must be NaN, never a
    silent in-market/out signal."""
    idx = pd.date_range("2000-01-31", periods=12, freq="ME")
    lvl = pd.Series(np.arange(100, 112), index=idx, dtype=float)
    pos = overlay.in_market_position(lvl, window=10)
    assert pos.iloc[:10].isna().all()            # 9 warm-up + 1 lag = 10 NaN
