"""Faber trend-overlay primitives (uncontested mechanics).

The canonical filter rule, applied identically to a single balanced series
(variant C) or to each sleeve (variants D/E):

  signal at month-end t  :  level_t  ≥  SMA_window(level)_t     (in-market)
  position for month t+1 :  that signal, LAGGED one month

The one-month lag is the no-look-ahead guarantee: the return earned in month m
is scaled by a signal computed only from data through month m-1. This module
holds only the signal maths; the A–E portfolio assembly lives elsewhere and is
gated on owner sign-off.

Python datetime months are 1-indexed; all series are month-end indexed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(level_monthly: pd.Series, window: int = 10) -> pd.Series:
    """Simple moving average of a month-end level over `window` months."""
    return level_monthly.rolling(window, min_periods=window).mean()


def in_market_position(level_monthly: pd.Series, window: int = 10) -> pd.Series:
    """Binary Faber overlay position (1 = hold asset, 0 = to cash), already
    lagged one month so month m's position was decided at the close of m-1."""
    raw = (level_monthly >= sma(level_monthly, window)).astype("float")
    raw[sma(level_monthly, window).isna()] = np.nan   # warm-up: undefined
    return raw.shift(1)


def graduated_position(level_monthly: pd.Series, window: int = 10,
                       band: float = 0.05) -> pd.Series:
    """Graduated overlay: exposure scales linearly from 0 to 1 across a ±band
    fractional distance around the SMA, then lagged one month. band=0.05 means
    full risk-on at +5% above the SMA, full risk-off at −5% below."""
    s = sma(level_monthly, window)
    dist = (level_monthly - s) / s                      # fractional distance
    expo = ((dist + band) / (2 * band)).clip(0.0, 1.0)
    expo[s.isna()] = np.nan
    return expo.shift(1)


def whipsaw_count(position: pd.Series) -> int:
    """Number of round-trip flips (0→1 or 1→0 transitions) in a binary
    position series — the raw switch count, halved elsewhere for round trips."""
    p = position.dropna()
    return int((p.diff().abs() > 0).sum())
