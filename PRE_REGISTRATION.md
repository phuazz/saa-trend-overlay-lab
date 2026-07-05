# SAA Trend-Overlay Lab — pre-registration

**Context:** Personal. **Status:** WS0 (data layer) complete; owner sign-off
RECORDED (§7); amendment A1 applied (§8); A–E engine + WS1 building. **Frozen:**
2026-07-04. **Amended:** 2026-07-04.

## 1. Question

Extend the Faber trend-overlay concept to a nine-block strategic asset
allocation (SAA). Two goals:

1. **Concept over long history** — show what a Faber 10-month trend overlay
   does to SAA building blocks well before the ETF era, not just post-2008.
2. **Per-asset vs single-overlay** — test whether applying the overlay to each
   building block individually (D/E) beats one overlay on the balanced base
   (C, the operational-ease choice Jirong selected) and the plain diversified
   base (B).

## 2. Provenance (what this builds on; not a repeat)

No coded A–E / SAA overlay existed in the vault (Step-0 finding, 2026-07-04);
this is a **new build**. It reuses execution conventions from
`Global-ETF-Trend-Scanner` (Faber 10-month regime gate, first-day-*t+1* fill,
per-class costs, SHY/BIL cash leg), the coverage-gate discipline of
`em-rotation-lab` (no `start_date`, cross-check `first_quoted_date`), and is
adjacent to `momentum-rotation` (a 4-asset cross-sectional rotation — a
different construction). It does **not** re-open those studies' conclusions.

## 3. Universe and data policy (WS0 — verified 2026-07-04, NDU live)

Each block is one monthly total-return series: a pre-ETF **PROXY** chained on
**returns** (never price levels) to the actual **ETF** from inception. Policy:
clean deep index proxies where they exist; **ETF-bridge** for the two
international blocks (no MSCI EAFE/EM index exists in Norgate); **SYNTHETIC**
constant-maturity par-bond series for the two Treasury blocks (the ICE Treasury
TR indices start 2004–2006, later than TLT/IEF themselves) and a compounded
T-bill TR for cash. Continuous Futures is empty in this Platinum tier — no
futures proxies. Every synthetic is validated by overlap reconciliation before
any pre-ETF use.

Overlap reconciliation (ETF monthly returns regressed on proxy; β≈1, α≈0,
high corr = clean). Measured:

| Block | ETF | Proxy | Kind | Series start | β | α/yr | corr | flag |
|---|---|---|---|---|---|---|---|---|
| US equity | SPY | `$SPXTR` | index | 1988 | 0.99 | −0.1% | 1.00 | clean |
| Dev ex-US | EFA | — (fund itself) | etf-only (A1) | 2001 | — | — | — | n/a |
| EM equity | EEM | — (fund itself) | etf-only (A1) | 2003 | — | — | — | n/a |
| Long Treasuries | TLT | `%30YTCM` par-bond M=25y | **synthetic** | 1977 | 1.01 | −0.2% | 0.99 | clean |
| Interm Treasuries | IEF | `%10YTCM` par-bond M=8.5y | **synthetic** | 1962 | 0.99 | +0.4% | 0.99 | clean |
| REITs | VNQ | `$DWRTFT` | index | 1996 | 0.96 | +0.1% | 0.99 | clean |
| Broad commodity | DBC | `$BCOMTR` | index | 1991 | 1.07 | +1.8% | 0.93 | **basis** |
| Gold | GLD | `XAUUSD` | index/spot | 1982 | 1.00 | −0.4% | 1.00 | clean |
| Cash (3m bill) | BIL | `%IRX` bill-TR | synthetic | 1960 | 1.01 | −0.1% | 0.95 | basis |

Reads: the α column recovers known fee drag (gold −0.4% = GLD's expense ratio;
US equity −0.1% = SPY's), a sanity check that the splice measures the fund, not
an artefact. **The two synthetic Treasury series reconcile clean (corr 0.99,
β≈1)** — empirical justification for using them. Two "basis" flags are
understood construction differences: DBC's optimised-roll DBIQ ≠ front-month
BCOM (+1.8%/yr, corr 0.93); the 13-week bill yield ≠ BIL's 1–3m basket (minor).
Both are labelled and will not be over-read pre-ETF.

**Binding constraint:** the clean full nine-block base starts **2003-05**
(EM/EEM is the shortest). So the study splits: deep **per-sleeve** concept
validation (five blocks reach 1962–1996) for goal 1, and the full nine-block
per-asset-vs-single test over 2003–2026 (spans GFC, 2015-16, COVID, 2022) for
goal 2. ETF inceptions are Norgate first-quoted dates; two-source verification
at build.

## 4. Variants A–E and the canonical filter rule

**Filter rule (Faber, applied identically single or per-asset):** at month-end
*t*, in-market iff `level_t ≥ SMA_10(level)_t`; the position is **lagged one
month** (decided at *t*, earns month *t+1*); out-of-market capital earns the
spliced BIL/T-bill leg; a switch pays a per-class one-way cost. 10-month is the
Faber base; 12-month carried as robustness.

| Var | Definition | Role |
|---|---|---|
| **A** | Single-asset (US equity) 10-month overlay vs its buy-&-hold | Concept in isolation, deep history |
| **B** | Plain diversified base — buy-&-hold 8 risk blocks at strategic weight, no overlay | WS2 baseline |
| **C** | Single overlay on balanced — one 10-month SMA on B's own TR index; whole book → BIL below | WS2 comparator (operational ease) |
| **D** | Per-asset overlay (binary) — each block vs its own SMA; below-trend block → BIL; recombine at strategic weight (freed weight parks in BIL) | WS2 protagonist |
| **E** | Per-asset overlay (graduated) — exposure scales across a ±5% band around each block's SMA | Whipsaw-smoothing sibling of D |

Defaults (locked unless overridden): strategic weight = **equal-weight the 8
risk blocks (12.5% each)**, BIL is the out-of-market destination only; monthly
rebalance; per-class one-way costs on every flip with a 0/5/10/20 bps sweep.

## 5. The three ways this backtest could be silently wrong

1. **Splice basis** — proxy vs ETF differ in fees/tracking/construction, so a
   naive join injects a phantom jump or drift. → return-chain splice; overlap
   reconciliation (§3); PROXY/ETF-ERA/SYNTHETIC labels; metrics split by era.
2. **Look-ahead / boundary leakage** — same-close signal-and-fill, or an
   off-by-one at the month/year boundary (worse across a splice). → signal
   through *t*, fill *t+1*, one-month position lag; month- and year-boundary
   and no-look-ahead unit tests (`tests/test_dates.py`, 6 passing).
3. **Cash-leg realism + cost asymmetry** — 0% out-of-market overstates the
   overlay in the high-rate 1980s–90s; omitting per-switch cost flatters the
   many-switch per-asset variants (D/E) against the few-switch single overlay
   (C) — the exact WS2 comparison. → out-of-market earns the spliced T-bill;
   realistic per-class costs with the bps sweep; turnover and whipsaw reported.

## 6. Workstreams, metrics, and the pre-registered decision rule

**WS1 (long-history concept):** A–E (and per-sleeve overlays) on the spliced
series; confirm the mechanism holds pre-ETF-era. Metrics: CAGR, vol, Sharpe,
Sortino, max DD, Ulcer index, time-in-market %, whipsaw round-trips per decade.
Checkpoint before WS2.

**WS2 (per-asset vs single):** combined per-asset-overlaid portfolio (D, E) vs
B and C over 2003–2026. Same metrics **plus** aggregate turnover and a
**clustered-exit** diagnostic (months where >60% of blocks are simultaneously
to cash, and portfolio behaviour then).

**Decision rule (frozen):** prefer per-asset (D/E) over single-overlay (C) only
if net-of-cost Sharpe(D or E) ≥ Sharpe(C) + 0.10 **and** max DD is not worse
than C by more than 2 ppt, and the verdict survives at 10 bps. If the
full-universe per-asset overlay disappoints, **narrow to the trend-strongest
blocks (equities, long Treasuries, commodities)** and re-test the same bar
before discarding (vault rule). A negative result is a valid outcome.

## 7. Owner sign-off — RECORDED 2026-07-04

1. **Data policy: ADOPTED** — clean proxies + reconciled SYNTHETIC
   Treasuries/bill; full deep history is used for goal 1 (the synthetics
   reconcile clean, §3: corr 0.99, β≈1). Not "clean-only".
2. **Filter: CONFIRMED** — 10-month SMA base, 12-month carried as robustness.
3. **Weighting: CONFIRMED** — equal-weight the 8 risk blocks (12.5%) is the
   headline base; an **inverse-vol (risk-parity-lite) weighting is added as a
   WS2 robustness cut** (test: does the per-asset verdict survive
   risk-balancing?). Full vol-targeting stays out of scope — that is
   `risk-overlay-lab`'s remit; importing it here would confound the overlay test.
4. **Dashboard: APPROVED**, built after WS1+WS2 — standard architecture
   (`template.html` <200KB + `data/` JSON + `scripts/pipeline.py` → `docs/`);
   **derived overlay states only** on any public surface (Norgate personal-use
   licence), never raw vendor series values.

## 8. Amendments

**A1 (2026-07-04) — international blocks use EFA/EEM outright.** Owner elected to
drop the VEA/VWO splice tail and hold **EFA** (Dev ex-US) and **EEM** (EM) as the
blocks for the whole series. These two are therefore ETF-only: no pre-ETF EAFE/EM
index exists in Norgate, so there is nothing deeper to splice, and the series
starts are unchanged (EFA 2001-09, EEM 2003-05) — the full nine-block base still
begins 2003-05. Definitional note carried into the record: EFA = MSCI EAFE (dev
ex-US, **ex-Canada**); EEM = MSCI EM — versus the FTSE families the removed funds
tracked (VEA includes Canada + Korea; VWO excludes Korea). Panel rebuilt under A1.

## 9. Post-hoc robustness review and verdict re-labelling (2026-07-05)

Three independent adversarial reviews (Quant PM, CIO, CPM), each verified by
recomputation, stress-tested the WS2 verdict. They agree the engineering is sound
and KEEP-C is the right call, but that the filed REASONING was overclaimed. The
record is re-labelled:

- **The decisive gaps are statistically indistinguishable from zero.** Circular
  block bootstrap (10-month, equal-weight, 10 bps, 10k draws): E−C observed +0.107,
  95% CI [−0.13, +0.36], P(clear +0.10) = 0.51, P(≤0) = 0.20; C−B similar. The
  +0.10 bar is ≈ one standard error on 22y of monthly data. KEEP C is a **parsimony
  default under statistical indistinguishability**, not a measured win.
- **Frozen-rule override disclosed.** Under §6, E's equal-weight result PASSES
  (+0.106 at 10 bps, drawdown better; `ws2_results.json` records
  `PASSES_RULE=true`). It is set aside on the indistinguishability + robustness
  grounds above. The earlier framing ("the rule kept C") is corrected.
- **The promised SMA-12 robustness was run** (§6 carried it, unrun): E−C = +0.055
  (SMA-8) / +0.106 (SMA-10) / +0.049 (SMA-12). The deployed 10-month pass is a
  1-of-3-window spike — reinforces KEEP C, exposes the earlier compliance gap.
- **The inverse-vol "lever" is demoted** from conclusion to follow-up hypothesis:
  single 36-month vol window, period-concentrated (2008–14 bond bull), lift
  significant only at p≈0.035 pre-multiplicity. A vol-window/ERC sweep + bootstrap
  is required before it informs any weighting decision.
- **WS1 softened:** the robust finding is drawdown/Ulcer truncation on nearly every
  sleeve (pre-ETF included); the Sharpe "skill" is small, sleeve-dependent and not
  significant (aligned-window US-equity proxy skill is negative). The headline no
  longer reads asset-era beta as overlay skill.
- **Benchmark added:** a passive 60/40 (SPY/IEF) matches the overlays on Sharpe and
  beats them on CAGR; the proposition is a priced insurance trade (~1–2.4%/yr for a
  ~two-thirds-shallower drawdown), stated as such.
- **CIO deployment view:** SHELVE for a fund book (no Sharpe case vs 60/40);
  tightly-gated PILOT for the personal context only, conditional on the vol-window
  sweep and the bootstrap passing first.
- **Corrections applied:** partial-month date truncation (metrics stop at the last
  completed month); the public dashboard shows the overlay strategy curve +
  drawdowns only (no rebased vendor level curve); uniform-vs-per-class cost noted.

Bootstrap and SMA sweeps are filed in `results/ws2_results.json`
(`bootstrap_sharpe_diff`, `sma_robustness`).
