# Dashboard Styling & Analytics Design Spec
**Date:** 2026-04-11  
**Status:** Approved

---

## Overview

Redesign the Google Sheets dashboard with a Dark Pro theme and add richer analytics. A new Python tool (`tools/format_dashboard.py`) uses the Google Sheets API to apply formatting, colors, conditional rules, and chart objects after each import run. The data written by `import_transactions.py` stays unchanged — this tool only handles presentation.

---

## Design Decisions

- **Theme:** Dark Pro — dark backgrounds (#0f1117), white text, green/red P&L colors, blue accents
- **Layout:** Two-column Dashboard tab optimized for large monitors
- **Period selector:** 1M, 3M, 6M, YTD, 1Y, 2Y, All — filters the portfolio growth chart and benchmark comparison
- **Benchmark panel:** S&P 500 (SPY) and QQQ returns fetched via yfinance for the selected period, shown alongside portfolio return

---

## Tab-by-Tab Formatting

### Dashboard Tab

**Layout — two columns:**

| Left column | Right column |
|---|---|
| KPI summary row (full width, 5 cards) | — |
| Allocation donut chart | Portfolio value over time (line chart + period buttons) |
| Key metrics panel | Holdings table (formatted) |
| Recent dividends | — |
| vs. Benchmarks | Top/Bottom Performers | Realized Gains |

**KPI row (5 cells across the top):**
- Total Portfolio Value
- Unrealized P&L ($) — green if positive, red if negative
- Cost Basis
- Dividend Income (blue)
- Best Performer ticker + return % (purple)

**Portfolio growth chart:**
- Line chart built from the Historical tab — full history (all dates), always shown
- Chart title shows all-time return % and total gain/loss

**Benchmark comparison panel:**
- Fetches SPY and QQQ historical close prices via yfinance, written to hidden `_Benchmarks` tab
- Shows a multi-row table: one row per period (1M, 3M, 6M, YTD, 1Y, 2Y, All)
- Each row shows indexed return % for Your Portfolio vs S&P 500 vs QQQ for that period
- Green if beating the benchmark, red if trailing — visible at a glance across all timeframes

**Holdings table formatting:**
- Alternating dark row shading
- Return % column: green badge background if positive, red if negative
- Day Change column: green/red text
- Sorted by current value descending

**Key Metrics panel:**
- Progress bars via SPARKLINE formula or conditional formatting
- Rows: Portfolio vs Cost, Winners/Losers count, Dividend Yield, Realized Gains, Total Return

### Holdings Tab

- Frozen header row (bold, dark background, light text)
- Alternating row shading (#131720 / #0f1117)
- Conditional formatting: Unrealized P&L column green if >0, red if <0
- Return % column: color-coded badge style via conditional formatting
- Day Change % column: green/red text
- Columns auto-resized to fit content

### Transactions Tab

- Frozen header row
- Action column: color-coded text (BUY=blue, SELL=orange, DIVIDEND=teal)
- Date column formatted as MM/DD/YYYY
- Amount column: negative values in red, positive in green

### Historical Tab

- Frozen header row
- No complex formatting needed — data-only tab

### Dividends Tab

- Frozen header row
- Amount column formatted as currency
- Type column: DIVIDEND=teal, REINVESTMENT=blue

---

## Python Tool: `tools/format_dashboard.py`

### Responsibilities
- Apply all cell formatting, colors, fonts to all tabs
- Build/update the Portfolio Growth chart on the Dashboard tab
- Build/update the Benchmark comparison chart on the Dashboard tab
- Fetch SPY and QQQ data for the `_Benchmarks` tab
- Add period selector named ranges (slices of Historical data by period)
- Called automatically at the end of `import_transactions.py` main()

### Key APIs used
- `gspread` — cell updates, batch formatting
- `Google Sheets API v4` (via `gspread`) — chart objects, named ranges, conditional formatting rules
- `yfinance` — SPY and QQQ historical prices for benchmark tab

### Period selector implementation
Google Sheets charts cannot dynamically change their data range from a formula, so the period selector works as follows:
- The Portfolio Growth chart always shows the full "All" history (most useful default)
- The Benchmark comparison panel shows return % for all periods (1M / 3M / 6M / YTD / 1Y / 2Y / All) as a table of indexed return badges — one row per period — so the user can see all periods at once without clicking
- The `_Benchmarks` tab contains columns for each period's indexed returns for portfolio, SPY, and QQQ
- This is simpler, more reliable, and more informative than a single-period toggle

### Benchmark tab (`_Benchmarks`)
Hidden tab with columns: date, spy_close, qqq_close, spy_return_pct, qqq_return_pct, portfolio_return_pct
- Fetched fresh on each import run via yfinance
- Indexed to 0% at the start of each period
- The Dashboard benchmark chart reads from this tab

---

## Integration with `import_transactions.py`

Add at the end of `main()` in `import_transactions.py`:

```python
from tools.format_dashboard import apply_formatting
apply_formatting(sheet)
```

This means every import run (manual or scheduled via launchd) also refreshes the formatting and benchmarks.

---

## Out of Scope

- Interactive JS/HTML dashboard outside of Google Sheets
- Real-time websocket price feeds
- Mobile layout
- Custom Google Apps Script
- Charting libraries (Chart.js, D3) — all charts are native Google Sheets chart objects
