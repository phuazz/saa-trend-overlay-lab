# CLAUDE.md — SAA Trend-Overlay Lab

Inherits the vault `C:\dev\CLAUDE.md`. Project-specific rules below.

## What this project is

A backtest of the Faber 10-month trend overlay on a nine-block SAA, on spliced
long-history Norgate total-return series. Context is **Personal**. The
governing spec is `PRE_REGISTRATION.md` — do not redefine variants A–E or the
data policy without owner sign-off; amend the pre-registration, do not drift.

## Hard rules

- **Norgate is personal-use licensed.** Never publish vendor series *values*
  on any public page (this repo may stay private, or a future dashboard shows
  only *derived* overlay states — in/out, weights, curve shapes — not raw
  `$SPXTR`/`%IRX`/etc. levels). See the vault `norgate-breadth-series` note.
- **No proxy is trusted before reconciliation.** Every pre-ETF series is
  chained on returns and validated against the ETF over the overlap window
  (β≈1, α≈0, high corr). Synthetic series are labelled SYNTHETIC everywhere.
- **Dates via libraries only.** pandas resampling (`ME` month-end in pandas
  3.0), never hand-computed offsets. Month indexing stated in comments (Python
  = 1-indexed). Month- and year-boundary + no-look-ahead tests must stay green.
- **No look-ahead.** Signal at month-end *t*, fill first trading day *t+1*,
  position lagged one month. Any headline metric that uses month-*t* return in
  month-*t*'s own signal is invalid.
- **Realistic costs always.** Per-class one-way costs on every switch; report
  the 0/5/10/20 bps sweep. The per-asset-vs-single verdict is cost-sensitive by
  construction — never quote a friction-free comparison as the result.

## Build

```
python scripts/data_layer.py     # WS0 spliced panel + reconciliation
python -m pytest tests/ -q        # must stay green
```

## Commit discipline

Per vault: British/Singapore English, no contractions in code/comments/commits.
This is its own git repo (the vault root gitignores project folders). Separate
approvals for commit and push.
