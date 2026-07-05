# SAA Trend-Overlay Lab

A backtest of the Faber 10-month trend overlay applied to a nine-block
strategic asset allocation, on spliced long-history total-return series from
Norgate. Two questions: (1) does the overlay concept hold over long history,
pre-ETF-era; (2) does a **per-asset** overlay across the SAA building blocks
beat a **single overlay on the balanced base** (the operational-ease choice)
and the plain diversified base.

**Educational research, not investment advice.** Personal context.

## Status — WS0→WS2 complete; dashboard built

- **WS0 data layer, WS1 (long-history concept), WS2 (per-asset vs single): done.**
  14 pytest green. Deep sleeves reach 1962–1996; per-asset-vs-single spans 2004–2026.
- **Verdict: KEEP the single overlay (C).** The overlay concept is real and
  predates the ETF era (WS1 — drawdown roughly halved on every sleeve; proxy-era
  Sharpe 0.74 REIT / 0.55 commodity / 0.43 Long Treasuries). Per-asset (D/E) does
  NOT robustly beat C (WS2): E clears the frozen +0.10 Sharpe bar only at ≤10 bps
  under equal weight; under an inverse-vol base C rises to 0.71 and the per-asset
  edge vanishes — per-asset is a substitute for risk-balanced weighting. The
  bigger, robust lever is inverse-vol weighting of the base.
- **Dashboard:** `template.html` → `docs/index.html` (educational; derived
  overlay states only, per the Norgate personal-use licence).

## Universe (9 SAA building blocks)

US equity (SPY), Dev ex-US (VEA), EM (VWO), Long Treasuries (TLT), Interm
Treasuries (IEF), REITs (VNQ), Broad commodity (DBC), Gold (GLD), Cash/3m-bill
(BIL). Each is a pre-ETF proxy chained on returns to the ETF. See the
reconciliation table in `PRE_REGISTRATION.md`.

## Data

Norgate Data (`norgatedata`, local NDU). **Personal-use licence: never publish
vendor series values on any public page — only derived overlay states.**
Proxies: `$SPXTR`, `$DWRTFT`, `$BCOMTR` (TR indices), `XAUUSD` (gold spot),
EFA/EEM (ETF bridges), and two clearly-labelled SYNTHETIC series — a
constant-maturity par-bond TR from `%30YTCM`/`%10YTCM` and a T-bill TR from
`%IRX`. No proxy is trusted before its overlap reconciliation to the ETF.

## Layout

```
scripts/norgate_io.py        # loaders + synthetic proxy constructors
scripts/data_layer.py        # WS0: build & reconcile the spliced panel
scripts/overlay.py           # Faber signal primitives (one-month-lagged)
scripts/engine.py            # A–E assembly (risk-weight matrix) + metrics
scripts/run_ws1.py           # WS1 long-history concept + per-sleeve PROXY/ETF split
scripts/run_ws2.py           # WS2 per-asset vs single + inverse-vol + clustered-exit
scripts/ws1_charts.py ws2_charts.py    # white-theme review figures (reviews/assets)
scripts/export_dashboard_data.py       # derived series -> data/dashboard.json
scripts/pipeline.py          # inject data -> docs/index.html
template.html / docs/index.html        # dashboard (source / built)
tests/                       # 14 passing (dates + engine no-look-ahead/costs)
data/panel_monthly.csv       # spliced monthly TR levels (regenerable, gitignored)
data/dashboard.json          # derived dashboard series (regenerable, gitignored)
results/ws{0,1,2}_*.json + *.csv       # checkpoints (derived metrics)
reviews/assets/fig1–7.png              # review charts
PRE_REGISTRATION.md          # the frozen spec (§7 owner sign-off, §8 amendment A1)
```

## Run

```bash
python scripts/data_layer.py            # WS0: rebuild spliced panel + reconciliation
python scripts/run_ws1.py               # WS1 metrics  -> results/ws1_*
python scripts/run_ws2.py               # WS2 decision -> results/ws2_*
python scripts/ws1_charts.py && python scripts/ws2_charts.py           # figures
python scripts/export_dashboard_data.py && python scripts/pipeline.py  # dashboard
python -m pytest tests/ -q              # 14 tests, must stay green
```

## Last updated

2026-07-05 — WS0→WS2 complete, dashboard built (verdict: keep C; inverse-vol is the lever).
