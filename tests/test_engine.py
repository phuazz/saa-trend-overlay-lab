"""Engine-level tests: no-look-ahead in the portfolio ASSEMBLY, cost accounting,
and the variant weight builders — on synthetic data so they are fast and exact.

The signal primitives are covered in test_dates.py; here we guard the join of
weights × returns × cash and the one-way cost rule. Month-/year-boundary
handling is exercised on a Dec→Jan synthetic panel.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import engine as E  # noqa: E402


def _levels(n_months: int, cols, start="2000-01-31", seed=0) -> pd.DataFrame:
    """Synthetic month-end total-return levels — independent gentle random walks
    with positive drift, month-end ('ME') indexed."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n_months, freq="ME")
    data = {}
    for k, c in enumerate(cols):
        rets = rng.normal(0.006, 0.03, n_months)      # ~7%/yr drift, ~10% vol
        data[c] = 100.0 * np.cumprod(1.0 + rets)
    return pd.DataFrame(data, index=idx)


def _rising(n_months: int, col="X", start="2000-01-31") -> pd.DataFrame:
    idx = pd.date_range(start, periods=n_months, freq="ME")
    return pd.DataFrame({col: np.linspace(100, 200, n_months)}, index=idx)


def test_zero_cost_net_equals_gross():
    lv = _levels(40, ["A", "B", "C"])
    W = E.weights_B(lv, blocks=["A", "B", "C"])
    r = E.monthly_returns(lv)
    cash = pd.Series(0.0, index=lv.index)
    a = E.assemble(W, r, cash, cost_bps=0.0)
    assert np.allclose(a.net.values, a.gross.values)


def test_buy_hold_equal_weight_is_mean_of_block_returns():
    """B with equal weights and zero cash must equal the cross-sectional mean of
    the block returns each month (constant-mix rebalanced base)."""
    cols = ["A", "B", "C"]
    lv = _levels(40, cols)
    W = E.weights_B(lv, blocks=cols)
    r = E.monthly_returns(lv)
    cash = pd.Series(0.0, index=lv.index)
    a = E.assemble(W, r, cash, cost_bps=0.0)
    expected = r[cols].mean(axis=1).reindex(W.index)
    assert np.allclose(a.net.values, expected.values)


def test_always_in_market_returns_the_asset():
    """A steadily rising sleeve is always above its SMA → position 1 → the
    overlaid return (zero cost) must equal the raw asset return."""
    lv = _rising(30, "X")
    W = E.weights_single_sleeve(lv, "X")
    r = E.monthly_returns(lv)
    cash = pd.Series(0.0, index=lv.index)
    a = E.assemble(W, r, cash, cost_bps=0.0)
    assert (W["X"] == 1.0).all()                      # never leaves the market
    assert np.allclose(a.net.values, r["X"].reindex(W.index).values)


def test_out_of_market_earns_the_cash_leg():
    """When the sleeve is out (position 0), the return must be exactly cash."""
    # rise for the warm-up, then a hard sustained fall to force position 0
    idx = pd.date_range("2000-01-31", periods=20, freq="ME")
    lvl = np.concatenate([np.linspace(100, 140, 12), np.linspace(138, 90, 8)])
    lv = pd.DataFrame({"X": lvl}, index=idx)
    W = E.weights_single_sleeve(lv, "X")
    r = E.monthly_returns(lv)
    cash = pd.Series(0.004, index=idx)                # 0.4%/month flat cash
    a = E.assemble(W, r, cash, cost_bps=0.0)
    out_months = W.index[W["X"] == 0.0]
    assert len(out_months) >= 1
    assert np.allclose(a.net.reindex(out_months).values, 0.004)


def test_full_flip_trades_the_whole_book():
    """A single-sleeve 1→0 flip trades notional 1.0 in that month (one-way)."""
    idx = pd.date_range("2000-01-31", periods=20, freq="ME")
    lvl = np.concatenate([np.linspace(100, 140, 12), np.linspace(138, 90, 8)])
    lv = pd.DataFrame({"X": lvl}, index=idx)
    W = E.weights_single_sleeve(lv, "X")
    r = E.monthly_returns(lv)
    a = E.assemble(W, r, pd.Series(0.0, index=idx), cost_bps=0.0)
    assert np.isclose(a.turnover.max(), 1.0)          # a whole-book flip
    assert a.turnover.iloc[0] == 0.0                  # no prior weights on row 0


def test_cost_drag_is_monotonic_in_bps():
    lv = _levels(60, E.RISK_BLOCKS[:4], seed=3)
    W = E.weights_D(lv, blocks=E.RISK_BLOCKS[:4])
    r = E.monthly_returns(lv)
    cash = pd.Series(0.0015, index=lv.index)
    tot = []
    for bps in (0.0, 10.0, 50.0):
        a = E.assemble(W, r, cash, cost_bps=bps)
        tot.append(a.net.sum())
    assert tot[0] >= tot[1] >= tot[2]                 # more cost → less return


def test_engine_assembly_has_no_lookahead():
    """Shocking a level in month m must not change any assembled return before
    month m. (It legitimately changes month m's own return and later weights.)"""
    lv = _levels(48, ["A", "B", "C"], seed=7)
    W = E.weights_D(lv, blocks=["A", "B", "C"])
    r = E.monthly_returns(lv)
    cash = pd.Series(0.001, index=lv.index)
    base = E.assemble(W, r, cash, cost_bps=10.0).net

    shock_date = lv.index[30]
    lv2 = lv.copy()
    lv2.loc[shock_date, "A"] *= 1.4
    W2 = E.weights_D(lv2, blocks=["A", "B", "C"])
    r2 = E.monthly_returns(lv2)
    pert = E.assemble(W2, r2, cash, cost_bps=10.0).net

    before = base.index[base.index < shock_date]
    assert np.allclose(base.reindex(before).values, pert.reindex(before).values)


def test_year_boundary_assembly_labels_months_correctly():
    """Assembly across Dec→Jan keeps December and January as distinct month-end
    rows in the right years (vault date rule: exercise a year boundary)."""
    idx = pd.date_range("2019-11-30", periods=4, freq="ME")   # Nov, Dec, Jan, Feb
    lv = pd.DataFrame({"A": [100, 101, 102, 103], "B": [100, 99, 101, 100]},
                      index=idx, dtype=float)
    W = E.weights_B(lv, blocks=["A", "B"])
    r = E.monthly_returns(lv)
    a = E.assemble(W, r, pd.Series(0.0, index=idx), cost_bps=0.0)
    labels = list(a.net.index.strftime("%Y-%m"))
    assert "2019-12" in labels and "2020-01" in labels
    assert a.net.index.is_month_end.all()
