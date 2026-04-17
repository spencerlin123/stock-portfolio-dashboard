# Localhost Web Dashboard Design Spec
**Date:** 2026-04-12
**Status:** Approved

---

## Overview

Replace the Google Sheets Dashboard tab as the primary view with a localhost web dashboard. Google Sheets continues to serve as the data layer (updated by the existing `import_transactions.py` launchd job). A Flask server reads from Sheets via gspread on every page load and serves a single-page Dark Pro dashboard at `http://localhost:5000`.

The Google Sheets formatting (`tools/format_dashboard.py`) is **not removed** — it stays as a fallback view — but the web dashboard is the primary interface going forward.

---

## Architecture

```
Fidelity CSV → import_transactions.py → Google Sheets (all tabs)
                                                ↓
                                         app.py (Flask, port 5000)
                                                ↓  GET /api/data
                                         static/index.html (SPA)
```

**New files:**
- `app.py` — Flask server at project root
- `static/index.html` — full single-page app (HTML + CSS + JS, no build step)

**Unchanged:** all existing tools, `import_transactions.py`, `format_dashboard.py`, launchd job.

---

## Backend: `app.py`

### Routes

| Route | Description |
|---|---|
| `GET /` | Serve `static/index.html` |
| `GET /api/data` | Return full data payload as JSON |

### `/api/data` response shape

```json
{
  "holdings": [
    {
      "ticker": "AAPL",
      "shares_held": 10.0,
      "avg_cost_basis": 150.0,
      "total_cost_basis": 1500.0,
      "current_price": 175.0,
      "current_value": 1750.0,
      "unrealized_pnl": 250.0,
      "unrealized_pnl_pct": 0.1667,
      "day_change_pct": 0.012
    }
  ],
  "transactions": [
    {
      "date": "2023-01-15",
      "ticker": "AAPL",
      "action": "BUY",
      "shares": 10.0,
      "price": 150.0,
      "amount": -1500.0,
      "description": "..."
    }
  ],
  "dividends": [
    { "date": "2024-03-15", "ticker": "AAPL", "amount": 23.50, "type": "DIVIDEND" }
  ],
  "portfolio_history": [
    { "date": "2023-07-01", "total_value": 45000.0 }
  ],
  "benchmarks": [
    { "period": "1M", "portfolio_pct": 4.79, "spy_pct": 2.29, "qqq_pct": 2.44 }
  ],
  "as_of": "2026-04-12T15:00:00"
}
```

### Data sourcing

- `holdings`, `transactions`, `dividends` — read directly from corresponding Sheets tabs via `read_tab_as_df()`
- `portfolio_history` — read from `_PortfolioHistory` hidden tab (daily aggregated totals)
- `benchmarks` — read from `_Benchmarks` hidden tab
- Numeric columns cast from strings (Sheets stores everything as strings via `get_all_records()`)
- If a hidden tab is missing (first run before import), return empty list for that key — frontend handles gracefully

### Auth

Uses the existing `get_sheet()` function from `tools/sheets_client.py` — same OAuth token, no new credentials needed.

### Error handling

- If Sheets is unreachable: return `{"error": "Sheets unavailable", "details": "..."}` with HTTP 503
- Frontend shows an error banner rather than a blank page

---

## Frontend: `static/index.html`

Single file — HTML + CSS + JS. Chart.js loaded from CDN. No npm, no build step.

### Layout

Two-column layout on wide screens, single column on narrow. Dark Pro theme throughout.

```
┌─────────────────────────────────────────────────────┐
│  PORTFOLIO DASHBOARD                  as of 3:00 PM │
├──────┬──────┬──────┬──────┬──────────────────────────┤
│ KPI  │ KPI  │ KPI  │ KPI  │ KPI                      │
├──────────────────────────┬──────────────────────────┤
│  Portfolio Growth        │  Allocation Donut         │
│  (line chart)            │  (pie chart)              │
├──────────────────────────┴──────────────────────────┤
│  Holdings Table (sortable by column)                │
├──────────────────────────┬──────────────────────────┤
│  vs. Benchmarks          │  Top / Bottom Performers  │
├──────────────────────────┼──────────────────────────┤
│  Recent Dividends        │  Realized Gains           │
└──────────────────────────┴──────────────────────────┘
```

### Panels

#### KPI Row (5 cards)
- **Total Portfolio Value** — `SUM(holdings.current_value)`, white, large
- **Unrealized P&L ($)** — `SUM(holdings.unrealized_pnl)`, green if positive, red if negative
- **Cost Basis** — `SUM(holdings.total_cost_basis)`, gray
- **Dividends YTD** — sum of dividends where year == current year, blue
- **Best Performer** — ticker + return % with highest `unrealized_pnl_pct`, purple

#### Portfolio Growth (line chart)
- Source: `portfolio_history` array
- X axis: dates, Y axis: portfolio value in $
- Blue line (`#4f8ef7`), dark card background
- Chart.js LINE chart, no legend

#### Allocation Donut (pie chart)
- Each slice = `current_value / total_value` per holding
- Top 7 tickers shown individually; remainder grouped as "Other"
- Chart.js DOUGHNUT chart, legend below

#### Holdings Table
- All columns: Ticker, Shares, Avg Cost, Total Cost, Price, Value, Unrealized P&L, Return %, Day Change %
- Sortable by clicking column headers (client-side sort)
- Return % column: green badge if positive, red badge if negative
- Day Change: green/red text
- Sorted by current value descending by default

#### vs. Benchmarks
- Source: `benchmarks` array
- 7 rows: 1M, 3M, 6M, YTD, 1Y, 2Y, All
- Columns: Period, Your Portfolio, S&P 500, QQQ
- Portfolio cell: green bg if beating S&P 500, red if trailing
- SPY/QQQ: green text if positive, red if negative

#### Top / Bottom Performers
- Top 3 holdings by `unrealized_pnl_pct` (green)
- Bottom 3 holdings by `unrealized_pnl_pct` (red)
- Shows: ticker, return %, unrealized P&L $

#### Recent Dividends
- Last 10 dividend/reinvestment transactions from `dividends` array
- Columns: Date, Ticker, Amount, Type
- DIVIDEND = teal, REINVESTMENT = blue

#### Realized Gains
- Computed from `transactions`: for each SELL row, find matching BUY transactions (FIFO), compute realized gain/loss
- Columns: Date, Ticker, Shares Sold, Proceeds, Cost Basis, Gain/Loss
- Gain: green, Loss: red
- Sorted by date descending

---

## Color Palette

| Token | Hex | Usage |
|---|---|---|
| `--bg` | `#0f1117` | Page background |
| `--card` | `#1a1d27` | Card backgrounds |
| `--row-alt` | `#131720` | Alternating table rows |
| `--text` | `#ffffff` | Primary text |
| `--muted` | `#555555` | Labels, secondary text |
| `--green` | `#00c805` | Positive P&L, gains |
| `--green-bg` | `#003810` | Positive badge background |
| `--red` | `#ff4d4d` | Negative P&L, losses |
| `--red-bg` | `#400000` | Negative badge background |
| `--blue` | `#4f8ef7` | Charts, dividends, accents |
| `--purple` | `#a78bfa` | Best performer |
| `--teal` | `#00c0c0` | Dividend type labels |
| `--orange` | `#ff9900` | SELL action labels |

---

## Realized Gains Calculation

FIFO cost basis per ticker:
1. For each SELL transaction (sorted by date ascending):
   - Walk through BUY transactions for the same ticker in chronological order
   - Consume shares from oldest buys first
   - `realized_gain = proceeds - (shares_sold × weighted_avg_cost_of_consumed_lots)`
2. Display each realized sale as one row

---

## How to Run

```bash
# Install Flask (one-time)
pip install flask

# Start the server
python app.py
# Dashboard available at http://localhost:5000
```

The server fetches fresh data from Sheets on every `/api/data` request — no caching, always current.

---

## Out of Scope

- Authentication / login (local-only, no auth needed)
- Real-time price websocket feeds
- Mobile responsive layout (wide monitor only, same as Sheets dashboard)
- Saving/editing data through the web UI
- Deployment to any remote server
