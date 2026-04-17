# Stock Portfolio Dashboard

A personal investment tracking dashboard built with Flask and Google Sheets. Imports Fidelity brokerage and Roth IRA transaction CSVs, computes time-weighted and money-weighted returns, and serves a live Dark Pro UI accessible at `localhost:5000`.

---

## Features

- **Live portfolio value** — Holdings tab uses `GOOGLEFINANCE()` formulas for real-time prices
- **TWR & MWR returns** — Time-Weighted Return strips out deposits so performance is comparable to benchmarks; Money-Weighted Return reflects your actual investor experience
- **Benchmark comparison** — Portfolio returns vs. S&P 500 (SPY) and QQQ across MTD, 1M, 3M, 6M, YTD, 1Y, 2Y, 3Y, All
- **Deposit-aware calculations** — EFT deposits and IRA cash contributions are parsed from CSVs and excluded from return calculations so new capital doesn't inflate performance
- **Auto-refresh** — Dashboard refreshes every 15 minutes; cache TTL matches Yahoo Finance's data delay (15 min during market hours, 1 hr otherwise)
- **Portfolio growth chart** — Interactive line chart with hover tooltips showing exact dollar value; period buttons (1W, MTD, YTD, 1Y, 3Y, All) show TWR return inline
- **Allocation chart** — Donut chart by ticker or sector
- **Dividends tracking** — Full dividend and reinvestment history
- **Risk metrics** — Annualized volatility and beta vs. SPY for 1Y and all-time windows
- **Dark Pro UI** — Dark theme with green/red conditional formatting throughout

---

## Architecture

```
app.py                  Flask server — serves dashboard and /api/data endpoint
tools/
  fidelity_parser.py    Parses Fidelity brokerage and 401k/IRA CSV formats
  import_transactions.py Imports CSVs into Google Sheets tabs
  portfolio_calculator.py Computes holdings, realized gains, dividends
  format_dashboard.py   TWR/MWR calculations, benchmark returns, Sheets formatting
  sheets_client.py      Google Sheets auth and helpers
static/
  index.html            Single-page dashboard (Chart.js, vanilla JS)
tests/                  pytest test suite (45 tests)
workflows/              Markdown SOPs for common operations
```

Google Sheets acts as the database. Key tabs:

| Tab | Contents |
|-----|----------|
| Holdings / IRA_Holdings | Live positions with GOOGLEFINANCE formulas |
| Transactions / IRA_Transactions | Full trade history |
| Dividends / IRA_Dividends | Dividend and reinvestment history |
| Historical / IRA_Historical | Daily position values for chart |
| _PortfolioHistory | Daily total portfolio value (hidden) |
| _Benchmarks | Pre-computed period returns (hidden) |
| _Analytics | Realized gains, risk metrics (hidden) |

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/spencerlin123/stock-portfolio-dashboard.git
cd stock-portfolio-dashboard
pip install -r requirements.txt
```

### 2. Google Sheets credentials

1. Create a Google Cloud project and enable the Sheets and Drive APIs
2. Create a Service Account and download `credentials.json` to the project root
3. Share your Google Sheet with the service account email

### 3. Environment variables

Create a `.env` file in the project root:

```
GOOGLE_SHEET_ID=your_sheet_id_here
BROKERAGE_CASH=0.00       # uninvested cash balance from Fidelity (update after each import)
IRA_CASH=0.00             # uninvested IRA cash balance from Fidelity
```

### 4. Import transactions

Place Fidelity CSV exports in:
- `.tmp/` — Individual brokerage account
- `.tmp/ira/` — Roth IRA / 401k account

Then run:

```bash
python tools/import_transactions.py
```

This parses all CSVs, updates Google Sheets, and recomputes all analytics tabs.

### 5. Start the dashboard

```bash
python app.py
```

Open `http://localhost:5000` in your browser.

---

## Return Calculations

**Time-Weighted Return (TWR)** chains daily sub-period returns and adjusts each day's denominator for external capital (deposits). This isolates investment performance from the effect of when you added money — directly comparable to SPY/QQQ benchmarks.

**Money-Weighted Return (MWR)** uses XIRR to compute an IRR across all cash flows. This reflects your actual experience as an investor — higher if you deposited more before good periods, lower if you deposited before downturns.

Deposits (Electronic Funds Transfer, Cash Contributions) are detected automatically from CSV rows. 401k-style contributions that arrive as direct fund purchases are handled via a fallback that detects BUYs not covered by available cash.

---

## Running Tests

```bash
pytest tests/ -v
```

45 tests covering the parser, return calculations, holdings logic, and API endpoints.

---

## Updating Cash Balances

After each import, update `BROKERAGE_CASH` and `IRA_CASH` in `.env` to match the cash balance shown in Fidelity. These are used to display uninvested cash in the Holdings tab. The return calculations derive deposit amounts directly from CSV rows, so these env vars only affect the display.
