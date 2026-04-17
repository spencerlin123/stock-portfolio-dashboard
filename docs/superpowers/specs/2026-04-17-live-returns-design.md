# Live Returns Design

**Date:** 2026-04-17  
**Status:** Approved

## Overview

Two bundled changes to make MTD, YTD, and all period returns reflect live prices without requiring a manual script run:

1. **Live return computation in `app.py`** — compute returns on-the-fly instead of reading static `_Benchmarks` from Sheets
2. **Incremental Historical fetch in `import_transactions.py`** — only fetch Yahoo Finance prices for dates missing from the Historical tab, not all-time history

---

## Change 1: Live Returns in `app.py`

### Problem
`/api/data` currently reads pre-computed return numbers from the `_Benchmarks` hidden tab in Google Sheets. Those numbers are only refreshed when `import_transactions.py` is run. Intra-day price moves are never reflected.

### Solution
Replace the `_Benchmarks` read with a `_compute_live_returns(sheet)` function that computes returns fresh on each (cache-miss) request.

### Data Flow

```
_PortfolioHistory (Sheets)  ──┐
                               ├──► compute_period_returns() ──► JSON response
Holdings current_value (sum) ──┤         (existing logic, reused)
SPY + QQQ prices (YF, 2 calls)─┘
```

Same flow repeated independently for:
- **Brokerage**: `_PortfolioHistory` + `Holdings`
- **IRA**: `_IRA_PortfolioHistory` + `IRA_Holdings`
- **Overall**: sum of both portfolio histories + sum of both Holdings

### Implementation Details

- Add `_compute_live_returns(sheet)` to `app.py`
  - Reads `_PortfolioHistory` from Sheets → historical daily totals
  - Reads `Holdings.current_value` column → sums to get today's live portfolio value
  - Appends today's `{date, total_value}` row to the historical series in-memory (does not write to Sheets)
  - Fetches SPY and QQQ current prices from Yahoo Finance (2 API calls)
  - Calls existing `compute_period_returns()` from `format_dashboard.py`
  - Returns a list of dicts matching the existing `_Benchmarks` schema: `[{period, twr_pct, mwr_pct, spy_pct, qqq_pct}, ...]`
- Repeat for IRA and Overall accounts
- Replace all three `_read_tab(..., "_Benchmarks", ...)` calls in `/api/data` with calls to `_compute_live_returns()`
- `_Benchmarks` tabs in Sheets become unused (still written by `import_transactions.py` but no longer read by `app.py`)

### Caching

Smart cache on `_compute_live_returns()` results:
- **During market hours** (9:30am–4pm ET, weekdays): 5-minute TTL
- **Outside market hours**: 1-hour TTL
- Cache key: account name (`"brokerage"`, `"ira"`, `"overall"`)
- Cache stored in-process (Python dict + timestamp) — no external cache needed
- On cache miss: recompute and store with fresh timestamp
- All three accounts computed together on a single cache miss to avoid redundant SPY/QQQ fetches

### Accuracy Notes

- TWR accuracy depends on `_PortfolioHistory` having a data point at or near the start of each benchmark period (e.g. April 1 for MTD). As long as `import_transactions.py` was run at least once during each period, accuracy is maintained.
- If cash deposits occurred in a gap between the last script run and today, TWR cannot adjust for those intra-gap daily flows. Running the script after any deposit/trade eliminates this.
- MWR (XIRR) is unaffected — it only needs start value, end value, and cash flow dates from the Transactions tab, all of which are available.

---

## Change 2: Incremental Historical Fetch in `import_transactions.py`

### Problem
`write_historical()` fetches Yahoo Finance close prices for every ticker from the first-ever trade date to today, even when most of those dates are already in the Historical tab. This makes `import_transactions.py` slow on every run.

### Solution
Before fetching prices, read the maximum date already present in the Historical tab and use it as `start_date` for `_fetch_all_closes()`.

### Implementation Details

- In `write_historical()`, after reading `existing_dates`, compute `max_existing_date`
- If `existing_dates` is non-empty: `start_date = max_existing_date - timedelta(days=5)` (small buffer to catch any weekend/holiday edge cases)
- If `existing_dates` is empty (first run): `start_date = buys_sells["date"].min().date()` (unchanged behavior)
- Pass the new `start_date` to `_fetch_all_closes()` instead of the all-time start
- Same fix applied to `write_historical()` in the IRA pipeline

### Impact
On subsequent runs after the first, Yahoo Finance fetches drop from years of daily data to ~5 days per ticker. With 10–20 tickers, this reduces fetch time from ~30–60s to ~2–5s.

---

## Files Changed

| File | Change |
|------|--------|
| `app.py` | Add `_compute_live_returns()`, smart cache, replace `_Benchmarks` reads |
| `tools/import_transactions.py` | Incremental `start_date` in `write_historical()` for both brokerage and IRA pipelines |

No frontend changes. No schema changes. `_Benchmarks` tabs remain in Sheets but are no longer read.

---

## Out of Scope

- Adding a `__main__` entry point to `format_dashboard.py` (deferred — less useful once `app.py` computes live)
- Handling split/dividend-adjusted price retroactive corrections in Historical
- Persisting today's computed value back to `_PortfolioHistory` (read-only computation is sufficient)
