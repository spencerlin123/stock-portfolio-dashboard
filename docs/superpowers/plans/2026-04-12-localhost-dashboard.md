# Localhost Web Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Flask localhost dashboard at `http://localhost:5000` that reads from Google Sheets and renders a full Dark Pro single-page app with 8 analytics panels.

**Architecture:** Flask serves `static/index.html` at `GET /` and a JSON data payload at `GET /api/data`. The frontend is a single HTML file with vanilla JS + Chart.js (CDN). No npm, no build step. Google Sheets remains the data layer, unchanged.

**Tech Stack:** Flask, gspread (existing `get_sheet()` + `read_tab_as_df()`), Chart.js 4.x (CDN), vanilla JS, Dark Pro CSS variables.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `app.py` | **Create** | Flask server: `GET /`, `GET /api/data`, Sheets reading, JSON serialization |
| `static/index.html` | **Create** | SPA: Dark Pro layout, Chart.js charts, all 8 panels |
| `requirements.txt` | **Modify** | Add `flask` |

**Unchanged:** `tools/sheets_client.py`, `tools/import_transactions.py`, `tools/format_dashboard.py`, all tests.

---

## Task 1: Flask Backend — `app.py` + `requirements.txt`

**Files:**
- Create: `app.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Add Flask to requirements.txt**

Open `requirements.txt` and append:

```
flask==3.0.3
```

- [ ] **Step 2: Write a failing test for the `/api/data` endpoint structure**

Create `tests/test_app.py`:

```python
import json
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _make_holdings_df():
    return pd.DataFrame([{
        "Ticker": "AAPL",
        "Shares Held": "10.0",
        "Avg Cost Basis": "150.0",
        "Total Cost Basis": "1500.0",
        "Current Price": "175.0",
        "Current Value": "1750.0",
        "Unrealized P&L": "250.0",
        "Unrealized P&L %": "0.1667",
        "Day Change %": "0.012",
    }])


def _make_transactions_df():
    return pd.DataFrame([{
        "Date": "2023-01-15",
        "Ticker": "AAPL",
        "Action": "BUY",
        "Shares": "10.0",
        "Price": "150.0",
        "Amount": "-1500.0",
        "Description": "Buy AAPL",
    }])


def _make_dividends_df():
    return pd.DataFrame([{
        "Date": "2024-03-15",
        "Ticker": "AAPL",
        "Amount": "23.50",
        "Type": "DIVIDEND",
    }])


def _make_history_df():
    return pd.DataFrame([{"Date": "2023-07-01", "Total Value": "45000.0"}])


def _make_benchmarks_df():
    return pd.DataFrame([{
        "Period": "1M",
        "Portfolio %": "4.79",
        "SPY %": "2.29",
        "QQQ %": "2.44",
    }])


def _mock_ws(df):
    ws = MagicMock()
    ws.get_all_records.return_value = df.to_dict("records")
    return ws


@patch("app.get_sheet")
def test_api_data_keys(mock_get_sheet, client):
    sheet = MagicMock()
    mock_get_sheet.return_value = sheet

    def worksheet_side_effect(name):
        mapping = {
            "Holdings": _mock_ws(_make_holdings_df()),
            "Transactions": _mock_ws(_make_transactions_df()),
            "Dividends": _mock_ws(_make_dividends_df()),
            "_PortfolioHistory": _mock_ws(_make_history_df()),
            "_Benchmarks": _mock_ws(_make_benchmarks_df()),
        }
        if name not in mapping:
            import gspread
            raise gspread.WorksheetNotFound(name)
        return mapping[name]

    sheet.worksheet.side_effect = worksheet_side_effect

    resp = client.get("/api/data")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    for key in ("holdings", "transactions", "dividends", "portfolio_history", "benchmarks", "as_of"):
        assert key in data, f"Missing key: {key}"


@patch("app.get_sheet")
def test_api_data_holdings_numeric(mock_get_sheet, client):
    sheet = MagicMock()
    mock_get_sheet.return_value = sheet

    def worksheet_side_effect(name):
        mapping = {
            "Holdings": _mock_ws(_make_holdings_df()),
            "Transactions": _mock_ws(_make_transactions_df()),
            "Dividends": _mock_ws(_make_dividends_df()),
            "_PortfolioHistory": _mock_ws(_make_history_df()),
            "_Benchmarks": _mock_ws(_make_benchmarks_df()),
        }
        if name not in mapping:
            import gspread
            raise gspread.WorksheetNotFound(name)
        return mapping[name]

    sheet.worksheet.side_effect = worksheet_side_effect

    resp = client.get("/api/data")
    data = json.loads(resp.data)
    h = data["holdings"][0]
    assert h["ticker"] == "AAPL"
    assert isinstance(h["shares_held"], float)
    assert isinstance(h["current_value"], float)
    assert isinstance(h["unrealized_pnl_pct"], float)


@patch("app.get_sheet")
def test_api_data_missing_hidden_tabs(mock_get_sheet, client):
    """If _PortfolioHistory/_Benchmarks don't exist yet, return empty lists."""
    sheet = MagicMock()
    mock_get_sheet.return_value = sheet

    def worksheet_side_effect(name):
        if name in ("_PortfolioHistory", "_Benchmarks"):
            import gspread
            raise gspread.WorksheetNotFound(name)
        mapping = {
            "Holdings": _mock_ws(_make_holdings_df()),
            "Transactions": _mock_ws(_make_transactions_df()),
            "Dividends": _mock_ws(_make_dividends_df()),
        }
        return mapping[name]

    sheet.worksheet.side_effect = worksheet_side_effect

    resp = client.get("/api/data")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["portfolio_history"] == []
    assert data["benchmarks"] == []


@patch("app.get_sheet")
def test_api_data_sheets_unavailable(mock_get_sheet, client):
    """503 + error JSON if Sheets is unreachable."""
    mock_get_sheet.side_effect = Exception("network error")
    resp = client.get("/api/data")
    assert resp.status_code == 503
    data = json.loads(resp.data)
    assert "error" in data


def test_index_route(client):
    """GET / returns 200 and HTML content."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"<!DOCTYPE html>" in resp.data or b"<html" in resp.data
```

- [ ] **Step 3: Run test to confirm it fails (app.py doesn't exist yet)**

```bash
cd "/Users/spencerlin/Desktop/Claude Code Projects/Stock Portfolio Dashboard"
pytest tests/test_app.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 4: Create `app.py`**

```python
#!/usr/bin/env python3
"""
Flask server for the Stock Portfolio Dashboard.

Routes:
  GET /          — serve static/index.html
  GET /api/data  — return full data payload as JSON
"""

import os
from datetime import datetime, timezone
from pathlib import Path

import gspread
import pandas as pd
from dotenv import load_dotenv
from flask import Flask, jsonify, send_from_directory

from tools.sheets_client import get_sheet, read_tab_as_df

load_dotenv()

app = Flask(__name__, static_folder="static")

# ---------------------------------------------------------------------------
# Column name maps: Sheets tab column → JSON field
# ---------------------------------------------------------------------------

_HOLDINGS_COLS = {
    "Ticker": "ticker",
    "Shares Held": "shares_held",
    "Avg Cost Basis": "avg_cost_basis",
    "Total Cost Basis": "total_cost_basis",
    "Current Price": "current_price",
    "Current Value": "current_value",
    "Unrealized P&L": "unrealized_pnl",
    "Unrealized P&L %": "unrealized_pnl_pct",
    "Day Change %": "day_change_pct",
}

_HOLDINGS_NUMERIC = [
    "shares_held", "avg_cost_basis", "total_cost_basis",
    "current_price", "current_value", "unrealized_pnl",
    "unrealized_pnl_pct", "day_change_pct",
]

_TRANSACTIONS_COLS = {
    "Date": "date",
    "Ticker": "ticker",
    "Action": "action",
    "Shares": "shares",
    "Price": "price",
    "Amount": "amount",
    "Description": "description",
}

_TRANSACTIONS_NUMERIC = ["shares", "price", "amount"]

_DIVIDENDS_COLS = {
    "Date": "date",
    "Ticker": "ticker",
    "Amount": "amount",
    "Type": "type",
}

_DIVIDENDS_NUMERIC = ["amount"]

_HISTORY_COLS = {
    "Date": "date",
    "Total Value": "total_value",
}

_HISTORY_NUMERIC = ["total_value"]

_BENCHMARKS_COLS = {
    "Period": "period",
    "Portfolio %": "portfolio_pct",
    "SPY %": "spy_pct",
    "QQQ %": "qqq_pct",
}

_BENCHMARKS_NUMERIC = ["portfolio_pct", "spy_pct", "qqq_pct"]


def _cast_numeric(records: list[dict], numeric_fields: list[str]) -> list[dict]:
    """Cast string values to float for known numeric fields."""
    result = []
    for row in records:
        r = dict(row)
        for field in numeric_fields:
            if field in r:
                try:
                    r[field] = float(str(r[field]).replace(",", "").replace("%", "") or 0)
                except (ValueError, TypeError):
                    r[field] = 0.0
        result.append(r)
    return result


def _df_to_records(df: pd.DataFrame, col_map: dict, numeric_fields: list[str]) -> list[dict]:
    """Rename columns per col_map, cast numerics, return list of dicts."""
    if df.empty:
        return []
    # Keep only columns that exist in the DataFrame
    existing = {k: v for k, v in col_map.items() if k in df.columns}
    df = df[list(existing.keys())].rename(columns=existing)
    records = df.to_dict("records")
    return _cast_numeric(records, numeric_fields)


def _read_tab(sheet, tab_name: str, col_map: dict, numeric_fields: list[str]) -> list[dict]:
    """Read a worksheet tab and return cleaned records. Returns [] if tab missing."""
    try:
        ws = sheet.worksheet(tab_name)
        df = read_tab_as_df(ws)
        return _df_to_records(df, col_map, numeric_fields)
    except gspread.WorksheetNotFound:
        return []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/data")
def api_data():
    try:
        sheet = get_sheet()
    except Exception as exc:
        return jsonify({"error": "Sheets unavailable", "details": str(exc)}), 503

    try:
        holdings = _read_tab(sheet, "Holdings", _HOLDINGS_COLS, _HOLDINGS_NUMERIC)
        transactions = _read_tab(sheet, "Transactions", _TRANSACTIONS_COLS, _TRANSACTIONS_NUMERIC)
        dividends = _read_tab(sheet, "Dividends", _DIVIDENDS_COLS, _DIVIDENDS_NUMERIC)
        portfolio_history = _read_tab(sheet, "_PortfolioHistory", _HISTORY_COLS, _HISTORY_NUMERIC)
        benchmarks = _read_tab(sheet, "_Benchmarks", _BENCHMARKS_COLS, _BENCHMARKS_NUMERIC)
    except Exception as exc:
        return jsonify({"error": "Data read error", "details": str(exc)}), 503

    return jsonify({
        "holdings": holdings,
        "transactions": transactions,
        "dividends": dividends,
        "portfolio_history": portfolio_history,
        "benchmarks": benchmarks,
        "as_of": datetime.now(timezone.utc).isoformat(),
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
cd "/Users/spencerlin/Desktop/Claude Code Projects/Stock Portfolio Dashboard"
pip install flask==3.0.3 -q
pytest tests/test_app.py -v
```

Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
cd "/Users/spencerlin/Desktop/Claude Code Projects/Stock Portfolio Dashboard"
git add app.py requirements.txt tests/test_app.py
git commit -m "feat: add Flask backend app.py with /api/data endpoint"
```

---

## Task 2: Frontend Skeleton — HTML Structure + CSS + KPI Row

**Files:**
- Create: `static/index.html`

- [ ] **Step 1: Create `static/` directory and `static/index.html` with Dark Pro skeleton**

```bash
mkdir -p "/Users/spencerlin/Desktop/Claude Code Projects/Stock Portfolio Dashboard/static"
```

Create `static/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Portfolio Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
  <style>
    /* ── CSS Variables ── */
    :root {
      --bg:        #0f1117;
      --card:      #1a1d27;
      --row-alt:   #131720;
      --text:      #ffffff;
      --muted:     #555555;
      --green:     #00c805;
      --green-bg:  #003810;
      --red:       #ff4d4d;
      --red-bg:    #400000;
      --blue:      #4f8ef7;
      --purple:    #a78bfa;
      --teal:      #00c0c0;
      --orange:    #ff9900;
      --border:    #252836;
    }

    /* ── Reset & Base ── */
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 14px;
      line-height: 1.5;
      min-height: 100vh;
    }

    /* ── Layout ── */
    #app { max-width: 1600px; margin: 0 auto; padding: 24px; }

    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
    }
    header h1 { font-size: 20px; font-weight: 700; letter-spacing: 0.05em; color: var(--text); }
    #as-of { color: var(--muted); font-size: 12px; }

    /* ── Error Banner ── */
    #error-banner {
      display: none;
      background: var(--red-bg);
      border: 1px solid var(--red);
      color: var(--red);
      padding: 12px 16px;
      border-radius: 6px;
      margin-bottom: 20px;
    }

    /* ── Card ── */
    .card {
      background: var(--card);
      border-radius: 8px;
      padding: 20px;
      border: 1px solid var(--border);
    }
    .card-title {
      color: var(--muted);
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 14px;
    }

    /* ── KPI Row ── */
    #kpi-row {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 12px;
      margin-bottom: 16px;
    }
    .kpi-card { text-align: left; }
    .kpi-label {
      color: var(--muted);
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 6px;
    }
    .kpi-value {
      font-size: 24px;
      font-weight: 700;
      line-height: 1.2;
    }
    .kpi-sub { font-size: 12px; color: var(--muted); margin-top: 4px; }

    /* ── Two-column chart row ── */
    #chart-row {
      display: grid;
      grid-template-columns: 1fr 420px;
      gap: 12px;
      margin-bottom: 16px;
    }
    .chart-wrap { position: relative; height: 280px; }

    /* ── Holdings Table ── */
    #holdings-section { margin-bottom: 16px; }
    .table-wrap { overflow-x: auto; }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th {
      color: var(--muted);
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 10px 12px;
      text-align: right;
      border-bottom: 1px solid var(--border);
      cursor: pointer;
      white-space: nowrap;
      user-select: none;
    }
    th:first-child { text-align: left; }
    th:hover { color: var(--text); }
    th.sorted-asc::after  { content: " ▲"; }
    th.sorted-desc::after { content: " ▼"; }
    td {
      padding: 9px 12px;
      text-align: right;
      border-bottom: 1px solid var(--border);
    }
    td:first-child { text-align: left; font-weight: 600; }
    tr:nth-child(even) td { background: var(--row-alt); }
    tr:hover td { background: #1e2232; }
    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 4px;
      font-weight: 600;
      font-size: 12px;
    }
    .badge-green { background: var(--green-bg); color: var(--green); }
    .badge-red   { background: var(--red-bg);   color: var(--red); }
    .pos { color: var(--green); }
    .neg { color: var(--red); }
    .muted { color: var(--muted); }

    /* ── Bottom row: 2 columns ── */
    #bottom-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-bottom: 16px;
    }

    /* ── Performers ── */
    .performer-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 0;
      border-bottom: 1px solid var(--border);
    }
    .performer-item:last-child { border-bottom: none; }
    .performer-ticker { font-weight: 700; font-size: 14px; }
    .performer-right { text-align: right; }
    .performer-pnl { font-size: 12px; color: var(--muted); }

    /* ── Benchmarks ── */
    .bench-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .bench-table th {
      color: var(--muted);
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 8px 12px;
      text-align: right;
      border-bottom: 1px solid var(--border);
      cursor: default;
    }
    .bench-table th:first-child { text-align: left; }
    .bench-table td {
      padding: 8px 12px;
      text-align: right;
      border-bottom: 1px solid var(--border);
    }
    .bench-table td:first-child { text-align: left; color: var(--muted); font-size: 12px; }
    .bench-portfolio-win { background: #003810; color: var(--green); font-weight: 700; }
    .bench-portfolio-lose { background: #400000; color: var(--red); font-weight: 700; }

    /* ── Dividends & Gains tables ── */
    #dividends-gains-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-bottom: 16px;
    }

    /* ── Loading overlay ── */
    #loading {
      display: flex;
      align-items: center;
      justify-content: center;
      height: 200px;
      color: var(--muted);
      font-size: 14px;
    }
  </style>
</head>
<body>
<div id="app">

  <header>
    <h1>PORTFOLIO DASHBOARD</h1>
    <span id="as-of"></span>
  </header>

  <div id="error-banner"></div>

  <!-- KPI Row -->
  <div id="kpi-row">
    <div class="card kpi-card" id="kpi-value">
      <div class="kpi-label">Total Value</div>
      <div class="kpi-value" id="kpi-total-value">—</div>
    </div>
    <div class="card kpi-card">
      <div class="kpi-label">Unrealized P&amp;L</div>
      <div class="kpi-value" id="kpi-pnl">—</div>
    </div>
    <div class="card kpi-card">
      <div class="kpi-label">Cost Basis</div>
      <div class="kpi-value" id="kpi-cost" style="color:var(--muted)">—</div>
    </div>
    <div class="card kpi-card">
      <div class="kpi-label">Dividends YTD</div>
      <div class="kpi-value" id="kpi-dividends" style="color:var(--blue)">—</div>
    </div>
    <div class="card kpi-card">
      <div class="kpi-label">Best Performer</div>
      <div class="kpi-value" id="kpi-best" style="color:var(--purple)">—</div>
      <div class="kpi-sub" id="kpi-best-sub"></div>
    </div>
  </div>

  <!-- Chart Row -->
  <div id="chart-row">
    <div class="card">
      <div class="card-title">Portfolio Growth</div>
      <div class="chart-wrap"><canvas id="growth-chart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">Allocation</div>
      <div class="chart-wrap"><canvas id="donut-chart"></canvas></div>
    </div>
  </div>

  <!-- Holdings Table -->
  <div class="card" id="holdings-section" style="margin-bottom:16px">
    <div class="card-title">Holdings</div>
    <div class="table-wrap">
      <table id="holdings-table">
        <thead>
          <tr>
            <th data-col="ticker" data-type="str">Ticker</th>
            <th data-col="shares_held" data-type="num">Shares</th>
            <th data-col="avg_cost_basis" data-type="num">Avg Cost</th>
            <th data-col="total_cost_basis" data-type="num">Total Cost</th>
            <th data-col="current_price" data-type="num">Price</th>
            <th data-col="current_value" data-type="num">Value</th>
            <th data-col="unrealized_pnl" data-type="num">Unrealized P&amp;L</th>
            <th data-col="unrealized_pnl_pct" data-type="num">Return %</th>
            <th data-col="day_change_pct" data-type="num">Day Chg %</th>
          </tr>
        </thead>
        <tbody id="holdings-tbody"></tbody>
      </table>
    </div>
  </div>

  <!-- Benchmarks + Top/Bottom Performers -->
  <div id="bottom-row">
    <div class="card">
      <div class="card-title">vs. Benchmarks</div>
      <table class="bench-table" id="bench-table">
        <thead>
          <tr>
            <th>Period</th>
            <th>Your Portfolio</th>
            <th>S&amp;P 500</th>
            <th>QQQ</th>
          </tr>
        </thead>
        <tbody id="bench-tbody"></tbody>
      </table>
    </div>
    <div class="card">
      <div class="card-title">Top &amp; Bottom Performers</div>
      <div id="performers-list"></div>
    </div>
  </div>

  <!-- Recent Dividends + Realized Gains -->
  <div id="dividends-gains-row">
    <div class="card">
      <div class="card-title">Recent Dividends</div>
      <div class="table-wrap">
        <table id="dividends-table">
          <thead>
            <tr>
              <th style="text-align:left">Date</th>
              <th style="text-align:left">Ticker</th>
              <th>Amount</th>
              <th style="text-align:left">Type</th>
            </tr>
          </thead>
          <tbody id="dividends-tbody"></tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <div class="card-title">Realized Gains</div>
      <div class="table-wrap">
        <table id="gains-table">
          <thead>
            <tr>
              <th style="text-align:left">Date</th>
              <th style="text-align:left">Ticker</th>
              <th>Shares Sold</th>
              <th>Proceeds</th>
              <th>Cost Basis</th>
              <th>Gain / Loss</th>
            </tr>
          </thead>
          <tbody id="gains-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

</div><!-- /#app -->

<script>
// ============================================================
//  Utilities
// ============================================================
const fmt = {
  usd: v => '$' + Math.abs(v).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2}),
  pct: v => (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%',
  pct_raw: v => (v >= 0 ? '+' : '') + v.toFixed(2) + '%',
  shares: v => v.toLocaleString('en-US', {minimumFractionDigits:0, maximumFractionDigits:4}),
};

function colorClass(v) { return v >= 0 ? 'pos' : 'neg'; }
function badge(v, formatted) {
  const cls = v >= 0 ? 'badge-green' : 'badge-red';
  return `<span class="badge ${cls}">${formatted}</span>`;
}

// ============================================================
//  KPI Row
// ============================================================
function renderKPIs(data) {
  const holdings = data.holdings;
  const totalValue = holdings.reduce((s, h) => s + h.current_value, 0);
  const totalPnl   = holdings.reduce((s, h) => s + h.unrealized_pnl, 0);
  const totalCost  = holdings.reduce((s, h) => s + h.total_cost_basis, 0);

  const now = new Date();
  const ytdDivs = data.dividends
    .filter(d => new Date(d.date).getFullYear() === now.getFullYear())
    .reduce((s, d) => s + d.amount, 0);

  const best = holdings.slice().sort((a,b) => b.unrealized_pnl_pct - a.unrealized_pnl_pct)[0];

  document.getElementById('kpi-total-value').textContent = fmt.usd(totalValue);
  const pnlEl = document.getElementById('kpi-pnl');
  pnlEl.textContent = (totalPnl >= 0 ? '+' : '-') + fmt.usd(totalPnl);
  pnlEl.style.color = totalPnl >= 0 ? 'var(--green)' : 'var(--red)';
  document.getElementById('kpi-cost').textContent = fmt.usd(totalCost);
  document.getElementById('kpi-dividends').textContent = fmt.usd(ytdDivs);

  if (best) {
    document.getElementById('kpi-best').textContent = best.ticker;
    document.getElementById('kpi-best-sub').textContent = fmt.pct(best.unrealized_pnl_pct);
  }

  const asOf = new Date(data.as_of);
  document.getElementById('as-of').textContent =
    'as of ' + asOf.toLocaleString('en-US', {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'});
}

// ============================================================
//  Portfolio Growth Chart
// ============================================================
let growthChart = null;
function renderGrowthChart(portfolioHistory) {
  const labels = portfolioHistory.map(r => r.date);
  const values = portfolioHistory.map(r => r.total_value);

  if (growthChart) growthChart.destroy();
  const ctx = document.getElementById('growth-chart').getContext('2d');
  growthChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: values,
        borderColor: '#4f8ef7',
        backgroundColor: 'rgba(79,142,247,0.08)',
        borderWidth: 2,
        pointRadius: 0,
        fill: true,
        tension: 0.3,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          ticks: { color: '#555', maxTicksLimit: 8, font: { size: 11 } },
          grid:  { color: 'rgba(255,255,255,0.04)' },
        },
        y: {
          ticks: {
            color: '#555',
            font: { size: 11 },
            callback: v => '$' + (v/1000).toFixed(0) + 'k',
          },
          grid: { color: 'rgba(255,255,255,0.04)' },
        }
      }
    }
  });
}

// ============================================================
//  Allocation Donut
// ============================================================
const DONUT_COLORS = ['#4f8ef7','#00c805','#a78bfa','#ff9900','#00c0c0','#f59e0b','#ec4899','#6b7280'];
let donutChart = null;
function renderDonutChart(holdings) {
  const totalValue = holdings.reduce((s,h) => s + h.current_value, 0);
  const sorted = holdings.slice().sort((a,b) => b.current_value - a.current_value);
  const top7 = sorted.slice(0, 7);
  const rest = sorted.slice(7);
  const items = top7.map(h => ({ label: h.ticker, value: h.current_value }));
  if (rest.length > 0) {
    items.push({ label: 'Other', value: rest.reduce((s,h) => s + h.current_value, 0) });
  }

  if (donutChart) donutChart.destroy();
  const ctx = document.getElementById('donut-chart').getContext('2d');
  donutChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: items.map(i => i.label),
      datasets: [{
        data: items.map(i => i.value),
        backgroundColor: DONUT_COLORS.slice(0, items.length),
        borderWidth: 1,
        borderColor: '#0f1117',
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            color: '#aaa',
            font: { size: 11 },
            boxWidth: 12,
            padding: 10,
          }
        },
        tooltip: {
          callbacks: {
            label: ctx => {
              const pct = ((ctx.parsed / totalValue) * 100).toFixed(1);
              return ` ${ctx.label}: ${pct}% (${fmt.usd(ctx.parsed)})`;
            }
          }
        }
      }
    }
  });
}

// ============================================================
//  Holdings Table (sortable)
// ============================================================
let holdingsSortCol = 'current_value';
let holdingsSortDir = 'desc';

function renderHoldings(holdings) {
  const sorted = sortHoldings(holdings, holdingsSortCol, holdingsSortDir);
  const tbody = document.getElementById('holdings-tbody');
  tbody.innerHTML = sorted.map(h => `
    <tr>
      <td>${h.ticker}</td>
      <td>${fmt.shares(h.shares_held)}</td>
      <td>${fmt.usd(h.avg_cost_basis)}</td>
      <td>${fmt.usd(h.total_cost_basis)}</td>
      <td>${fmt.usd(h.current_price)}</td>
      <td>${fmt.usd(h.current_value)}</td>
      <td class="${colorClass(h.unrealized_pnl)}">${(h.unrealized_pnl>=0?'+':'-')}${fmt.usd(h.unrealized_pnl)}</td>
      <td>${badge(h.unrealized_pnl_pct, fmt.pct(h.unrealized_pnl_pct))}</td>
      <td class="${colorClass(h.day_change_pct)}">${fmt.pct(h.day_change_pct)}</td>
    </tr>`).join('');

  // Update sort indicators
  document.querySelectorAll('#holdings-table th').forEach(th => {
    th.classList.remove('sorted-asc','sorted-desc');
    if (th.dataset.col === holdingsSortCol) {
      th.classList.add(holdingsSortDir === 'asc' ? 'sorted-asc' : 'sorted-desc');
    }
  });
}

function sortHoldings(holdings, col, dir) {
  return holdings.slice().sort((a, b) => {
    const av = a[col], bv = b[col];
    const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
    return dir === 'asc' ? cmp : -cmp;
  });
}

function initHoldingsSortHeaders(holdings) {
  document.querySelectorAll('#holdings-table th').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.col;
      if (holdingsSortCol === col) {
        holdingsSortDir = holdingsSortDir === 'asc' ? 'desc' : 'asc';
      } else {
        holdingsSortCol = col;
        holdingsSortDir = th.dataset.type === 'str' ? 'asc' : 'desc';
      }
      renderHoldings(window._lastHoldings);
    });
  });
}

// ============================================================
//  Benchmarks Table
// ============================================================
const PERIOD_ORDER = ['1M','3M','6M','YTD','1Y','2Y','All'];

function renderBenchmarks(benchmarks) {
  const byPeriod = Object.fromEntries(benchmarks.map(r => [r.period, r]));
  const tbody = document.getElementById('bench-tbody');
  tbody.innerHTML = PERIOD_ORDER.map(p => {
    const r = byPeriod[p];
    if (!r) return `<tr><td>${p}</td><td>—</td><td>—</td><td>—</td></tr>`;
    const portClass = r.portfolio_pct >= r.spy_pct ? 'bench-portfolio-win' : 'bench-portfolio-lose';
    return `<tr>
      <td>${p}</td>
      <td class="${portClass}">${fmt.pct_raw(r.portfolio_pct)}</td>
      <td class="${colorClass(r.spy_pct)}">${fmt.pct_raw(r.spy_pct)}</td>
      <td class="${colorClass(r.qqq_pct)}">${fmt.pct_raw(r.qqq_pct)}</td>
    </tr>`;
  }).join('');
}

// ============================================================
//  Top / Bottom Performers
// ============================================================
function renderPerformers(holdings) {
  const sorted = holdings.slice().sort((a,b) => b.unrealized_pnl_pct - a.unrealized_pnl_pct);
  const top3 = sorted.slice(0, 3);
  const bot3 = sorted.slice(-3).reverse();
  const container = document.getElementById('performers-list');

  function item(h, color) {
    return `<div class="performer-item">
      <span class="performer-ticker" style="color:${color}">${h.ticker}</span>
      <div class="performer-right">
        <div style="color:${color};font-weight:700">${fmt.pct(h.unrealized_pnl_pct)}</div>
        <div class="performer-pnl">${(h.unrealized_pnl>=0?'+':'-')}${fmt.usd(h.unrealized_pnl)}</div>
      </div>
    </div>`;
  }

  container.innerHTML =
    '<div style="color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:8px">Top 3</div>' +
    top3.map(h => item(h, 'var(--green)')).join('') +
    '<div style="color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:0.06em;margin:14px 0 8px">Bottom 3</div>' +
    bot3.map(h => item(h, 'var(--red)')).join('');
}

// ============================================================
//  Recent Dividends
// ============================================================
function renderDividends(dividends) {
  const recent = dividends.slice().sort((a,b) => b.date.localeCompare(a.date)).slice(0,10);
  const tbody = document.getElementById('dividends-tbody');
  tbody.innerHTML = recent.map(d => {
    const typeColor = d.type === 'DIVIDEND' ? 'var(--teal)' : 'var(--blue)';
    return `<tr>
      <td style="text-align:left">${d.date}</td>
      <td style="text-align:left;font-weight:600">${d.ticker}</td>
      <td>${fmt.usd(d.amount)}</td>
      <td style="text-align:left;color:${typeColor}">${d.type}</td>
    </tr>`;
  }).join('');
}

// ============================================================
//  Realized Gains (FIFO)
// ============================================================
function computeRealizedGains(transactions) {
  // Build FIFO buy queues per ticker
  const buyQueues = {};
  const sells = [];

  const sorted = transactions.slice().sort((a,b) => a.date.localeCompare(b.date));

  for (const tx of sorted) {
    if (tx.action === 'BUY' && tx.shares > 0) {
      if (!buyQueues[tx.ticker]) buyQueues[tx.ticker] = [];
      buyQueues[tx.ticker].push({ shares: tx.shares, price: tx.price, date: tx.date });
    } else if (tx.action === 'SELL' && tx.shares > 0) {
      sells.push(tx);
    }
  }

  const results = [];
  for (const sell of sells) {
    const ticker = sell.ticker;
    const queue = buyQueues[ticker] ? buyQueues[ticker].slice() : [];
    let sharesLeft = sell.shares;
    let costConsumed = 0;

    while (sharesLeft > 0 && queue.length > 0) {
      const lot = queue[0];
      const take = Math.min(sharesLeft, lot.shares);
      costConsumed += take * lot.price;
      lot.shares -= take;
      sharesLeft -= take;
      if (lot.shares <= 0) queue.shift();
    }
    // Update the buy queue (shares consumed)
    if (buyQueues[ticker]) {
      buyQueues[ticker] = queue;
    }

    const proceeds = sell.shares * sell.price;
    const gain = proceeds - costConsumed;
    results.push({
      date: sell.date,
      ticker,
      shares_sold: sell.shares,
      proceeds,
      cost_basis: costConsumed,
      gain,
    });
  }

  return results.sort((a,b) => b.date.localeCompare(a.date));
}

function renderRealizedGains(transactions) {
  const gains = computeRealizedGains(transactions);
  const tbody = document.getElementById('gains-tbody');
  if (gains.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted)">No realized sales</td></tr>';
    return;
  }
  tbody.innerHTML = gains.map(g => `<tr>
    <td style="text-align:left">${g.date}</td>
    <td style="text-align:left;font-weight:600">${g.ticker}</td>
    <td>${fmt.shares(g.shares_sold)}</td>
    <td>${fmt.usd(g.proceeds)}</td>
    <td>${fmt.usd(g.cost_basis)}</td>
    <td class="${colorClass(g.gain)}">${(g.gain>=0?'+':'-')}${fmt.usd(g.gain)}</td>
  </tr>`).join('');
}

// ============================================================
//  Boot
// ============================================================
async function loadData() {
  try {
    const resp = await fetch('/api/data');
    if (!resp.ok) {
      const err = await resp.json();
      showError(err.error + (err.details ? ': ' + err.details : ''));
      return;
    }
    const data = await resp.json();

    window._lastHoldings = data.holdings;

    renderKPIs(data);
    renderGrowthChart(data.portfolio_history);
    renderDonutChart(data.holdings);
    renderHoldings(data.holdings);
    initHoldingsSortHeaders(data.holdings);
    renderBenchmarks(data.benchmarks);
    renderPerformers(data.holdings);
    renderDividends(data.dividends);
    renderRealizedGains(data.transactions);

  } catch (e) {
    showError('Failed to load data: ' + e.message);
  }
}

function showError(msg) {
  const el = document.getElementById('error-banner');
  el.textContent = msg;
  el.style.display = 'block';
}

loadData();
</script>
</body>
</html>
```

- [ ] **Step 2: Verify the file was created**

```bash
ls -lh "/Users/spencerlin/Desktop/Claude Code Projects/Stock Portfolio Dashboard/static/"
```

Expected: `index.html` listed

- [ ] **Step 3: Start the Flask server and verify it loads without crashing**

```bash
cd "/Users/spencerlin/Desktop/Claude Code Projects/Stock Portfolio Dashboard"
python -c "from app import app; print('Flask import OK')"
```

Expected: `Flask import OK`

- [ ] **Step 4: Commit**

```bash
cd "/Users/spencerlin/Desktop/Claude Code Projects/Stock Portfolio Dashboard"
git add static/index.html
git commit -m "feat: add Dark Pro single-page dashboard (static/index.html)"
```

---

## Task 3: End-to-End Smoke Test + Final Polish

**Files:**
- No new files — verify the full stack works

- [ ] **Step 1: Run the full test suite**

```bash
cd "/Users/spencerlin/Desktop/Claude Code Projects/Stock Portfolio Dashboard"
pytest -v
```

Expected: All tests pass (test_app.py + existing tests)

- [ ] **Step 2: Manual smoke test — start the server**

```bash
cd "/Users/spencerlin/Desktop/Claude Code Projects/Stock Portfolio Dashboard"
python app.py
```

Open `http://localhost:5000` in a browser.

Verify:
- [ ] Page loads with Dark Pro theme (black background)
- [ ] KPI row shows 5 cards
- [ ] Portfolio Growth line chart renders
- [ ] Allocation Donut renders with legend
- [ ] Holdings table shows all positions, sorted by Value descending
- [ ] Clicking column headers re-sorts the table
- [ ] Benchmarks table shows 7 rows (1M / 3M / 6M / YTD / 1Y / 2Y / All)
- [ ] Top & Bottom Performers shows 3 green + 3 red items
- [ ] Recent Dividends table shows up to 10 rows
- [ ] Realized Gains table shows sells with FIFO gains/losses

- [ ] **Step 3: Commit final state**

```bash
cd "/Users/spencerlin/Desktop/Claude Code Projects/Stock Portfolio Dashboard"
git add -A
git commit -m "feat: complete localhost web dashboard (app.py + static/index.html)"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] `GET /` serves `static/index.html` — Task 1, app.py
- [x] `GET /api/data` returns JSON with all 6 keys — Task 1, app.py
- [x] Numeric casting from Sheets strings — `_cast_numeric()` in app.py
- [x] 503 + JSON error on Sheets unreachable — `api_data()` in app.py
- [x] Empty list for missing hidden tabs — `_read_tab()` gspread.WorksheetNotFound handler
- [x] KPI row: 5 cards (total value, unrealized P&L, cost basis, dividends YTD, best performer) — Task 2
- [x] Portfolio Growth line chart — Task 2
- [x] Allocation Donut (top 7 + Other) — Task 2
- [x] Holdings table: all columns, sortable, return % badge, day change color — Task 2
- [x] Benchmarks: 7 periods, portfolio vs SPY/QQQ, green/red highlighting — Task 2
- [x] Top 3 / Bottom 3 performers — Task 2
- [x] Recent Dividends: last 10, DIVIDEND=teal / REINVESTMENT=blue — Task 2
- [x] Realized Gains: FIFO from transactions, proceeds/cost/gain columns — Task 2
- [x] Dark Pro color palette via CSS variables — Task 2
- [x] Flask added to requirements.txt — Task 1
- [x] No new credentials — reuses existing `get_sheet()` — Task 1

**No placeholders found.**

**Type consistency:** `_HOLDINGS_COLS` maps match field names used throughout JS and app.py.
