# Stock Portfolio Dashboard — Design Spec
**Date:** 2026-04-10  
**Status:** Approved

---

## Overview

A personal stock portfolio tracking dashboard built on Google Sheets, backed by a Python tool (WAT layer) that imports Fidelity transaction history CSVs. The transaction history is the single source of truth — current holdings, cost basis, realized gains, and historical performance are all derived from it. Live prices are pulled automatically via `GOOGLEFINANCE()`.

---

## Goals

- Track current holdings with live prices and unrealized P&L
- See historical portfolio value over time
- Track per-stock performance since purchase
- Track realized gains/losses from sold positions
- Track dividend income
- Update the dashboard by downloading a new CSV from Fidelity and running one script

---

## Architecture

### Layer 1: Google Sheets (UI + Data Store)
The dashboard the user views and interacts with. All data lives here. Live prices are pulled via `GOOGLEFINANCE()` formulas — no API key required, ~15-min delayed.

### Layer 2: Python Tool (WAT Execution)
`tools/import_transactions.py` — processes Fidelity CSV exports and pushes data into Sheets via the Google Sheets API. The user drops a downloaded CSV into `.tmp/` and runs the script. It deduplicates against existing data so it can be re-run safely at any time.

### Update Workflow
Defined in `workflows/update_portfolio.md`:
1. Log into Fidelity and download transaction history as CSV
2. Place CSV in `.tmp/`
3. Run `python tools/import_transactions.py`
4. Dashboard updates automatically

---

## Google Sheets Structure

### Tab: Dashboard
Summary view. Auto-calculated from other tabs.
- Total portfolio value (current)
- Total cost basis
- Total unrealized P&L ($ and %)
- Total realized P&L
- Total dividend income received
- Charts:
  - Portfolio value over time (line chart from Historical tab)
  - Current allocation by ticker (pie chart from Holdings tab)

### Tab: Holdings
Current open positions, derived from the Transactions tab.

| Column | Source |
|---|---|
| Ticker | Derived from transactions |
| Shares Held | Sum of buys minus sells |
| Avg Cost Basis (per share) | Weighted average of buy transactions |
| Total Cost Basis | Shares × Avg Cost Basis |
| Current Price | `=GOOGLEFINANCE(ticker, "price")` |
| Current Value | Shares × Current Price |
| Unrealized P&L ($) | Current Value − Total Cost Basis |
| Unrealized P&L (%) | Unrealized P&L / Total Cost Basis |
| Day Change | `=GOOGLEFINANCE(ticker, "changepct")` |

### Tab: Transactions
Raw data imported from Fidelity CSV. One row per transaction event.

| Column | Description |
|---|---|
| Date | Transaction date |
| Ticker | Stock/ETF symbol |
| Action | Buy, Sell, Dividend, Reinvestment |
| Shares | Number of shares (negative for sells) |
| Price Per Share | Price at time of transaction |
| Amount | Total dollar amount (negative = money out) |
| Description | Original description from Fidelity |

### Tab: Historical
Portfolio value snapshots over time, enabling performance charts.

| Column | Description |
|---|---|
| Date | Snapshot date (one row per trading day with activity) |
| Ticker | Stock/ETF symbol |
| Shares Held | Cumulative shares held as of this date |
| Close Price | Historical close price fetched via `yfinance` by the import tool |
| Position Value | Shares × Close Price |

Aggregate by date to get total portfolio value over time.

### Tab: Dividends
Dividend income isolated from the Transactions tab.

| Column | Description |
|---|---|
| Date | Date dividend was received |
| Ticker | Source ticker |
| Amount | Dollar amount received |
| Type | Dividend or Reinvestment |

---

## Python Tool: `tools/import_transactions.py`

### Inputs
- Fidelity transaction history CSV (placed in `.tmp/`)
- Google Sheets credentials (`credentials.json`, `token.json`)
- Sheet ID (stored in `.env` as `GOOGLE_SHEET_ID`)

### Processing Steps
1. Read and parse the Fidelity CSV (handle Fidelity's non-standard header format)
2. Normalize columns to the Transactions schema above
3. Filter to supported action types: Buy, Sell, Dividend, Reinvestment
4. Deduplicate: compare against existing rows in the Transactions tab by (Date, Ticker, Action, Shares, Amount)
5. Append only new rows to the Transactions tab
6. Recompute the Holdings tab: group transactions by ticker, calculate shares held and avg cost basis, write results
7. Append new rows to the Historical tab for dates not yet present
8. Append new rows to the Dividends tab

### Error Handling
- If a ticker is not recognized by GOOGLEFINANCE (e.g., delisted), log a warning and skip price lookup — leave price blank
- If the CSV format changes (Fidelity sometimes updates their export format), surface a clear error with the unexpected column names

### Environment Variables (`.env`)
```
GOOGLE_SHEET_ID=your_sheet_id_here
```

### Dependencies
- `gspread` — Google Sheets API client
- `google-auth` — OAuth credentials
- `pandas` — CSV parsing and transformation
- `yfinance` — historical close prices for the Historical tab

---

## Workflow: `workflows/update_portfolio.md`

SOP for updating the dashboard:
1. Log into Fidelity → Accounts & Trade → Transaction History
2. Set date range (e.g., last 90 days or since last update)
3. Export as CSV → save to `.tmp/fidelity_transactions.csv`
4. Run: `python tools/import_transactions.py`
5. Open the Google Sheet — Dashboard tab reflects new data

---

## Out of Scope

- Real-time (sub-second) price feeds — GOOGLEFINANCE's ~15-min delay is acceptable
- Automatic Fidelity connection or scraping
- Options, futures, or international stocks
- Mobile app or hosted deployment
- Tax lot accounting (FIFO/LIFO) — cost basis uses weighted average
