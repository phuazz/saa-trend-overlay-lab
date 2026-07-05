"""A–E portfolio-assembly engine for the SAA trend-overlay study.

Every variant is expressed as a monthly matrix of RISK weights `W` (T×8, one
column per risk block); whatever is not in risk (1 − row sum) earns the spliced
cash leg. This single representation makes the variants differ in exactly one
thing — how `W` is built — and makes costs and turnover identical in treatment:

    gross_t = Σ_j W[j,t]·r[j,t]  +  (1 − Σ_j W[j,t])·cash_t
    cost_t  = bps × Σ_j |W[j,t] − W[j,t−1]|          (one-way, risk legs only;
                                                      the offsetting leg is cash)
    net_t   = gross_t − cost_t

Weight builders (all use the one-month-lagged Faber positions from overlay.py,
so W[·,t] was decided at the close of month t−1 → no look-ahead):

    B  buy-&-hold      W[j,t] = w_j                         (constant, no flips)
    C  single-overlay  W[j,t] = pos_base_t · w_j            (one signal on B's index)
    D  per-asset binary W[j,t] = pos_j_t · w_j              (each block its own signal)
    E  per-asset graded W[j,t] = expo_j_t · w_j             (±band graduated)
    A  single asset     W[us,t] = pos_us_t (w=1), deep history, vs its buy-&-hold

The cost rule `Σ_j |ΔW_j|` over RISK columns is exactly the notional traded when
the counter-leg is (costless) cash: a full C flip trades 1.0 (whole book); a D/E
adjustment trades Σ_i w_i·|Δexpo_i|; B trades nothing. One-way, per the spec.

Python `datetime` months are 1-indexed; every series here is month-end indexed
(pandas 'ME'). No return in month t uses any information dated ≥ t.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import overlay  # tested Faber primitives (one-month-lagged)

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / "data" / "panel_monthly.csv"
WS0_JSON = ROOT / "results" / "ws0_data_layer.json"

CASH_BLOCK = "Cash (3m bill)"
RISK_BLOCKS = [
    "US equity", "Dev ex-US equity", "EM equity", "Long Treasuries",
    "Interm Treasuries", "REITs", "Broad commodity", "Gold",
]
US_EQUITY = "US equity"
MONTHS_PER_YEAR = 12          # month-end panel; annualisation factor
SMA_WINDOW = 10               # Faber base (12-month carried as robustness)
GRAD_BAND = 0.05              # ±5% band for the graduated variant E
DEFAULT_COST_BPS = 10.0       # reference cost for the frozen decision rule
COST_SWEEP_BPS = (0.0, 5.0, 10.0, 20.0)


# --------------------------------------------------------------------------- #
# Data access
# --------------------------------------------------------------------------- #
def load_panel() -> pd.DataFrame:
    """Monthly total-return LEVELS, month-end indexed, one column per block."""
    df = pd.read_csv(PANEL, index_col=0, parse_dates=True)
    df.index = pd.DatetimeIndex(df.index)
    return df


def monthly_returns(levels: pd.DataFrame | pd.Series):
    """Simple monthly total returns from levels (fill_method=None: never carry
    a stale level across a gap — a missing month stays NaN, not a fake 0%)."""
    return levels.pct_change(fill_method=None)


def etf_inception() -> dict[str, str]:
    """Block -> 'YYYY-MM-DD' ETF inception month (the PROXY/ETF-ERA boundary)."""
    data = json.loads(WS0_JSON.read_text(encoding="utf-8"))
    return {b["block"]: b["etf_inception_month"] for b in data["blocks"]}


# --------------------------------------------------------------------------- #
# Core assembly — one function, driven by a risk-weight matrix
# --------------------------------------------------------------------------- #
@dataclass
class Assembled:
    net: pd.Series           # net-of-cost monthly return
    gross: pd.Series         # gross monthly return
    cost: pd.Series          # monthly cost drag (>= 0)
    invested: pd.Series      # Σ risk weight = fraction in risk (time-in-market)
    turnover: pd.Series      # Σ|ΔW| over risk legs (one-way notional traded)
    weights: pd.DataFrame    # the risk-weight matrix actually applied


def assemble(weights: pd.DataFrame, rets: pd.DataFrame,
             cash_ret: pd.Series, cost_bps: float) -> Assembled:
    """Combine a risk-weight matrix with block returns + the cash leg.

    `weights` and `rets` share columns (risk blocks) and index (months). The
    weight row for month t is applied to the return of month t; since the weight
    rows are the already-lagged Faber positions, this is the no-look-ahead join.
    """
    w = weights.copy()
    idx = w.index
    r = rets.reindex(index=idx, columns=w.columns)

    invested = w.sum(axis=1)
    cash_w = 1.0 - invested
    gross = (w * r).sum(axis=1) + cash_w * cash_ret.reindex(idx)

    # one-way cost on the risk notional traded; first row has no prior weights
    dW = w.diff().abs().sum(axis=1)
    dW.iloc[0] = 0.0
    cost = (cost_bps / 1e4) * dW
    net = gross - cost
    return Assembled(net=net, gross=gross, cost=cost, invested=invested,
                     turnover=dW, weights=w)


# --------------------------------------------------------------------------- #
# Variant weight-matrix builders
# --------------------------------------------------------------------------- #
def _equal_weights(blocks: list[str]) -> dict[str, float]:
    w = 1.0 / len(blocks)
    return {b: w for b in blocks}


def weights_B(levels: pd.DataFrame, blocks=RISK_BLOCKS) -> pd.DataFrame:
    """B — buy-&-hold, constant strategic (equal) weight, no overlay."""
    ew = _equal_weights(blocks)
    r = monthly_returns(levels[blocks])
    valid = r.dropna(how="any")                       # all blocks present
    W = pd.DataFrame({b: ew[b] for b in blocks}, index=valid.index)
    return W


def base_index_from_B(levels: pd.DataFrame, blocks=RISK_BLOCKS) -> pd.Series:
    """B's own total-return index (needed as C's single signal input)."""
    W = weights_B(levels, blocks)
    r = monthly_returns(levels[blocks]).loc[W.index]
    b_ret = (W * r).sum(axis=1)
    return (1.0 + b_ret).cumprod()


def weights_C(levels: pd.DataFrame, window=SMA_WINDOW, blocks=RISK_BLOCKS) -> pd.DataFrame:
    """C — single 10m overlay on B's balanced index; whole book on/off."""
    ew = _equal_weights(blocks)
    base = base_index_from_B(levels, blocks)
    pos = overlay.in_market_position(base, window)     # lagged, warm-up = NaN
    pos = pos.dropna()
    W = pd.DataFrame({b: pos * ew[b] for b in blocks})
    return W


def weights_D(levels: pd.DataFrame, window=SMA_WINDOW, blocks=RISK_BLOCKS) -> pd.DataFrame:
    """D — per-asset binary overlay; each block on/off vs its own SMA."""
    ew = _equal_weights(blocks)
    cols = {}
    for b in blocks:
        pos = overlay.in_market_position(levels[b].dropna(), window)
        cols[b] = pos * ew[b]
    W = pd.DataFrame(cols).dropna(how="any")           # common post-warm-up span
    return W


def weights_E(levels: pd.DataFrame, window=SMA_WINDOW, band=GRAD_BAND,
              blocks=RISK_BLOCKS) -> pd.DataFrame:
    """E — per-asset graduated overlay; exposure scales across a ±band."""
    ew = _equal_weights(blocks)
    cols = {}
    for b in blocks:
        expo = overlay.graduated_position(levels[b].dropna(), window, band)
        cols[b] = expo * ew[b]
    W = pd.DataFrame(cols).dropna(how="any")
    return W


def weights_single_sleeve(levels: pd.DataFrame, block: str,
                          window=SMA_WINDOW, graduated=False,
                          band=GRAD_BAND) -> pd.DataFrame:
    """One-block overlay at full weight (variant A on US equity, or any sleeve
    for the deep per-sleeve concept panel). Returns a 1-column risk matrix."""
    lvl = levels[block].dropna()
    pos = (overlay.graduated_position(lvl, window, band) if graduated
           else overlay.in_market_position(lvl, window))
    return pd.DataFrame({block: pos.dropna()})


def buy_hold_sleeve(levels: pd.DataFrame, block: str) -> pd.DataFrame:
    """Fully-invested single block (the buy-&-hold comparator for a sleeve)."""
    lvl = levels[block].dropna()
    r = monthly_returns(lvl).dropna()
    return pd.DataFrame({block: 1.0}, index=r.index)


# --------------------------------------------------------------------------- #
# Generalised base-weight → variant machinery (WS2: any strategic base, so the
# equal-weight verdict can be re-tested under an inverse-vol / risk-parity base)
# --------------------------------------------------------------------------- #
def base_weights_equal(levels: pd.DataFrame, blocks=RISK_BLOCKS) -> pd.DataFrame:
    """Constant equal strategic weights over the all-blocks-present window."""
    r = monthly_returns(levels[list(blocks)]).dropna(how="any")
    return pd.DataFrame(1.0 / len(blocks), index=r.index, columns=list(blocks))


def base_weights_inverse_vol(levels: pd.DataFrame, blocks=RISK_BLOCKS,
                             vol_window: int = 36, lag: int = 1) -> pd.DataFrame:
    """Risk-parity-lite base: target weight ∝ 1/trailing-vol, rows summed to 1.

    Vol is a `vol_window`-month rolling std of monthly returns, LAGGED `lag`
    month(s), so the weight applied in month t uses only information through
    t−1 — no look-ahead. Rows are dropped until every block has a defined
    weight (≈ vol_window months after the last block starts)."""
    r = monthly_returns(levels[list(blocks)])
    vol = r.rolling(vol_window).std(ddof=1).shift(lag)
    inv = 1.0 / vol
    W = inv.div(inv.sum(axis=1), axis=0)
    return W.dropna(how="any")


def base_index(base_W: pd.DataFrame, rets: pd.DataFrame) -> pd.Series:
    """Total-return index of a base-weight book (C's single-signal input)."""
    r = rets.reindex(index=base_W.index, columns=base_W.columns)
    return (1.0 + (base_W * r).sum(axis=1)).cumprod()


def build_variant(levels: pd.DataFrame, base_W: pd.DataFrame, which: str,
                  window: int = SMA_WINDOW, band: float = GRAD_BAND) -> pd.DataFrame:
    """Risk-weight matrix for B/C/D/E given ANY base-weight matrix `base_W`.

    B = base; C = base × single overlay on the base's own index; D = base ×
    per-block binary overlay; E = base × per-block graduated overlay. For an
    equal-weight base this reproduces weights_B/C/D/E exactly."""
    blocks = list(base_W.columns)
    rets = monthly_returns(levels[blocks])
    if which == "B":
        return base_W.copy()
    if which == "C":
        pos = overlay.in_market_position(base_index(base_W, rets), window)
        return base_W.mul(pos, axis=0).dropna(how="any")
    if which in ("D", "E"):
        cols = {}
        for b in blocks:
            cols[b] = (overlay.in_market_position(levels[b].dropna(), window)
                       if which == "D"
                       else overlay.graduated_position(levels[b].dropna(), window, band))
        P = pd.DataFrame(cols)
        return (base_W * P.reindex(base_W.index)).dropna(how="any")
    raise ValueError(which)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def drawdown(level: pd.Series) -> pd.Series:
    """Fractional drawdown from the running peak (<= 0)."""
    return level / level.cummax() - 1.0


def _cagr(net: pd.Series) -> float:
    lvl = (1.0 + net).cumprod()
    yrs = len(net) / MONTHS_PER_YEAR
    return float(lvl.iloc[-1] ** (1.0 / yrs) - 1.0) if yrs > 0 else float("nan")


def metrics(net: pd.Series, cash_ret: pd.Series,
            invested: pd.Series | None = None,
            position_for_whipsaw: pd.Series | None = None) -> dict:
    """Full WS1 metric set on a net monthly-return series.

    Sharpe/Sortino are excess of the actual spliced cash leg (not a hard-coded
    rf), so the high-rate 1980s–90s are charged correctly. Whipsaw is round
    trips per decade on the supplied binary position (halved raw switches).
    """
    net = net.dropna()
    cash = cash_ret.reindex(net.index)
    excess = net - cash
    ann = np.sqrt(MONTHS_PER_YEAR)

    vol = float(net.std(ddof=1) * ann)
    downside = excess.copy()
    downside[downside > 0] = 0.0
    dd_dev = float(np.sqrt((downside ** 2).mean()) * ann)
    sharpe = float(excess.mean() * MONTHS_PER_YEAR / vol) if vol > 0 else float("nan")
    sortino = float(excess.mean() * MONTHS_PER_YEAR / dd_dev) if dd_dev > 0 else float("nan")

    lvl = (1.0 + net).cumprod()
    dd = drawdown(lvl)
    ulcer = float(np.sqrt((dd.mul(100.0) ** 2).mean()))   # % units, RMS drawdown

    out = {
        "cagr": _cagr(net),
        "vol": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd": float(dd.min()),
        "ulcer": ulcer,
        "n_months": int(len(net)),
        "start": str(net.index[0].date()),
        "end": str(net.index[-1].date()),
    }
    if invested is not None:
        out["time_in_market"] = float(invested.reindex(net.index).mean())
    if position_for_whipsaw is not None:
        p = position_for_whipsaw.reindex(net.index).dropna()
        raw_switches = int((p.diff().abs() > 1e-9).sum())
        decades = len(net) / (MONTHS_PER_YEAR * 10)
        out["whipsaw_roundtrips_per_decade"] = float((raw_switches / 2.0) / decades) if decades > 0 else float("nan")
    return out
