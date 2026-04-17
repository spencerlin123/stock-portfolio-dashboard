# Dashboard Styling & Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `tools/format_dashboard.py` to apply a Dark Pro theme and rich analytics (KPI row, portfolio growth chart, benchmark comparison) across all Google Sheets tabs, called automatically at the end of `import_transactions.py`.

**Architecture:** A single `apply_formatting(sheet)` entry point calls tab-specific formatters and hidden-tab writers in sequence. Pure computational logic (`compute_period_returns`) is isolated for testability. All formatting uses Google Sheets API v4 batch requests. Transactions/Holdings/Historical/Dividends data is never mutated — only presentation. The Dashboard tab is fully rewritten by this tool (replacing the old metric-table with a proper KPI layout).

**Tech Stack:** Python 3.10+, gspread 6.1.2 (Google Sheets API v4 via `batch_update`), yfinance 1.2.1 (always returns MultiIndex for multi-ticker downloads), pandas, pytest

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `tools/format_dashboard.py` | **Create** | All formatting logic + analytics; `apply_formatting(sheet)` entry point |
| `tests/test_format_dashboard.py` | **Create** | Unit tests for pure functions; smoke tests for formatters with mocked sheet |
| `tools/import_transactions.py` | **Modify** | Remove `write_dashboard()` call; add `apply_formatting(sheet)` at end of `main()` |

---

### Task 1: Scaffold `tools/format_dashboard.py` — constants, helpers, `apply_formatting` skeleton

**Files:**
- Create: `tools/format_dashboard.py`
- Create: `tests/test_format_dashboard.py`

- [ ] **Step 1: Write a failing import test**

```python
# tests/test_format_dashboard.py
def test_import():
    from tools.format_dashboard import apply_formatting, compute_period_returns
    assert callable(apply_formatting)
    assert callable(compute_period_returns)
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
pytest tests/test_format_dashboard.py::test_import -v
```
Expected: `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Create `tools/format_dashboard.py` with constants and helpers**

```python
# tools/format_dashboard.py
"""
Apply Dark Pro formatting and analytics to all Google Sheets tabs.

Entry point:
    from tools.format_dashboard import apply_formatting
    apply_formatting(sheet)   # sheet is a gspread.Spreadsheet object
"""
import os
import sys
import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ── Dark Pro color palette ──────────────────────────────────────────────────
_BG_DARK    = {"red": 0.059, "green": 0.067, "blue": 0.090}  # #0f1117
_BG_CARD    = {"red": 0.102, "green": 0.114, "blue": 0.153}  # #1a1d27
_BG_ROW_ALT = {"red": 0.075, "green": 0.090, "blue": 0.125}  # #131720
_WHITE      = {"red": 1.0,   "green": 1.0,   "blue": 1.0  }
_GRAY       = {"red": 0.333, "green": 0.333, "blue": 0.333}
_GREEN      = {"red": 0.0,   "green": 0.784, "blue": 0.020}  # #00c805
_GREEN_BG   = {"red": 0.0,   "green": 0.220, "blue": 0.060}
_RED        = {"red": 1.0,   "green": 0.302, "blue": 0.302}  # #ff4d4d
_RED_BG     = {"red": 0.250, "green": 0.050, "blue": 0.050}
_BLUE       = {"red": 0.310, "green": 0.557, "blue": 0.969}  # #4f8ef7
_PURPLE     = {"red": 0.655, "green": 0.545, "blue": 0.980}  # #a78bfa
_TEAL       = {"red": 0.0,   "green": 0.753, "blue": 0.753}  # #00c0c0
_ORANGE     = {"red": 1.0,   "green": 0.600, "blue": 0.0  }  # #ff9900


def _ws_id(ws) -> int:
    """Return the numeric sheet ID for a gspread Worksheet."""
    return ws._properties["sheetId"]


def _batch_update(sheet, requests: list):
    """Send a batch of Sheets API v4 requests. No-ops if requests list is empty."""
    if requests:
        sheet.batch_update({"requests": requests})


def _range(ws_id: int, start_row: int, end_row: int, start_col: int, end_col: int) -> dict:
    """Build a GridRange dict (all indices 0-based, end exclusive)."""
    return {
        "sheetId": ws_id,
        "startRowIndex": start_row,
        "endRowIndex": end_row,
        "startColumnIndex": start_col,
        "endColumnIndex": end_col,
    }


def _clear_tab_formatting(sheet, ws):
    """
    Delete all conditional format rules and banding ranges from a tab.
    Call this before re-applying rules to prevent duplicates on subsequent runs.
    """
    ws_id = _ws_id(ws)
    meta = sheet.fetch_sheet_metadata()
    for s in meta.get("sheets", []):
        if s["properties"]["sheetId"] != ws_id:
            continue
        requests = []
        for br in reversed(s.get("bandedRanges", [])):
            requests.append({"deleteBanding": {"bandedRangeId": br["bandedRangeId"]}})
        cf_rules = s.get("conditionalFormats", [])
        for i in range(len(cf_rules) - 1, -1, -1):
            requests.append({"deleteConditionalFormatRule": {"sheetId": ws_id, "index": i}})
        if requests:
            _batch_update(sheet, requests)
        break


def _hide_tab(sheet, ws):
    """Hide a worksheet tab from view."""
    _batch_update(sheet, [{
        "updateSheetProperties": {
            "properties": {"sheetId": _ws_id(ws), "hidden": True},
            "fields": "hidden",
        }
    }])


def apply_formatting(sheet):
    """
    Apply all Dark Pro formatting and analytics to the spreadsheet.
    Called automatically at the end of import_transactions.py main().
    """
    from tools.sheets_client import get_or_create_tab

    print("  [fmt] Writing hidden analytics tabs...")
    write_hidden_tabs(sheet)

    print("  [fmt] Dashboard tab...")
    dashboard_ws = get_or_create_tab(sheet, "Dashboard", ["metric", "value"])
    write_dashboard_sections(sheet, dashboard_ws)
    add_portfolio_chart(sheet, dashboard_ws)

    print("  [fmt] Holdings tab...")
    holdings_ws = sheet.worksheet("Holdings")
    format_holdings(sheet, holdings_ws)

    print("  [fmt] Transactions tab...")
    txn_ws = sheet.worksheet("Transactions")
    format_transactions(sheet, txn_ws)

    print("  [fmt] Dividends tab...")
    divs_ws = sheet.worksheet("Dividends")
    format_dividends(sheet, divs_ws)

    print("  [fmt] Historical tab...")
    hist_ws = sheet.worksheet("Historical")
    format_historical(sheet, hist_ws)

    print("  [fmt] Formatting complete.")


# ── Stubs filled in by subsequent tasks ────────────────────────────────────

def compute_period_returns(portfolio_df: pd.DataFrame, spy_df: pd.DataFrame,
                           qqq_df: pd.DataFrame) -> pd.DataFrame:
    raise NotImplementedError


def write_hidden_tabs(sheet):
    raise NotImplementedError


def write_dashboard_sections(sheet, dashboard_ws):
    raise NotImplementedError


def add_portfolio_chart(sheet, dashboard_ws):
    raise NotImplementedError


def format_holdings(sheet, ws):
    raise NotImplementedError


def format_transactions(sheet, ws):
    raise NotImplementedError


def format_dividends(sheet, ws):
    raise NotImplementedError


def format_historical(sheet, ws):
    raise NotImplementedError
```

- [ ] **Step 4: Run import test — expect pass**

```bash
pytest tests/test_format_dashboard.py::test_import -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/format_dashboard.py tests/test_format_dashboard.py
git commit -m "feat: scaffold format_dashboard.py with constants, helpers, and apply_formatting stub"
```

---

### Task 2: `compute_period_returns` — pure function with full tests

**Files:**
- Modify: `tools/format_dashboard.py` (replace stub)
- Modify: `tests/test_format_dashboard.py` (add tests)

This function is the only purely computational piece in format_dashboard.py. It takes three DataFrames and returns a period comparison table. No API calls, fully unit-testable.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_format_dashboard.py  (add below test_import)
import pandas as pd
from tools.format_dashboard import compute_period_returns


def _make_frames(n_days=500):
    """Generate n_days of synthetic daily data starting 2024-01-02."""
    dates = pd.date_range("2024-01-02", periods=n_days, freq="B")
    portfolio = pd.DataFrame({
        "date": dates,
        "total_value": [10000 + i * 10 for i in range(n_days)],
    })
    spy = pd.DataFrame({
        "date": dates,
        "close": [400.0 + i * 0.5 for i in range(n_days)],
    })
    qqq = pd.DataFrame({
        "date": dates,
        "close": [300.0 + i * 0.4 for i in range(n_days)],
    })
    return portfolio, spy, qqq


def test_period_returns_columns():
    p, s, q = _make_frames()
    result = compute_period_returns(p, s, q)
    assert list(result.columns) == ["period", "portfolio_pct", "spy_pct", "qqq_pct"]


def test_period_returns_rows():
    p, s, q = _make_frames()
    result = compute_period_returns(p, s, q)
    assert list(result["period"]) == ["1M", "3M", "6M", "YTD", "1Y", "2Y", "All"]


def test_period_returns_all_positive_for_rising_series():
    p, s, q = _make_frames()
    result = compute_period_returns(p, s, q)
    for col in ["portfolio_pct", "spy_pct", "qqq_pct"]:
        assert result.loc[result["period"] == "All", col].iloc[0] > 0, f"{col} All return should be positive"


def test_period_returns_all_negative_for_falling_series():
    n = 300
    dates = pd.date_range("2024-01-02", periods=n, freq="B")
    p = pd.DataFrame({"date": dates, "total_value": [10000 - i * 5 for i in range(n)]})
    s = pd.DataFrame({"date": dates, "close": [400.0 - i * 0.3 for i in range(n)]})
    q = pd.DataFrame({"date": dates, "close": [300.0 - i * 0.2 for i in range(n)]})
    result = compute_period_returns(p, s, q)
    assert result.loc[result["period"] == "All", "portfolio_pct"].iloc[0] < 0


def test_period_returns_empty_returns_zeros():
    p = pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "total_value": pd.Series(dtype=float)})
    s = pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "close": pd.Series(dtype=float)})
    q = pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "close": pd.Series(dtype=float)})
    result = compute_period_returns(p, s, q)
    assert (result[["portfolio_pct", "spy_pct", "qqq_pct"]] == 0).all().all()
```

- [ ] **Step 2: Run tests — expect failures (NotImplementedError)**

```bash
pytest tests/test_format_dashboard.py -k "period_returns" -v
```
Expected: all 5 tests FAIL with `NotImplementedError`

- [ ] **Step 3: Implement `compute_period_returns`** (replace the stub in `tools/format_dashboard.py`)

```python
def compute_period_returns(portfolio_df: pd.DataFrame, spy_df: pd.DataFrame,
                           qqq_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute portfolio, SPY, and QQQ returns for each benchmark period.

    Args:
        portfolio_df: columns ['date', 'total_value'], date as datetime or date-parseable str
        spy_df:       columns ['date', 'close'], date as datetime or date-parseable str
        qqq_df:       columns ['date', 'close'], date as datetime or date-parseable str

    Returns:
        DataFrame with columns: period, portfolio_pct, spy_pct, qqq_pct
        Periods: 1M, 3M, 6M, YTD, 1Y, 2Y, All
    """
    today = pd.Timestamp.today().normalize()

    def _period_start(label: str) -> pd.Timestamp:
        if label == "1M":  return today - pd.DateOffset(months=1)
        if label == "3M":  return today - pd.DateOffset(months=3)
        if label == "6M":  return today - pd.DateOffset(months=6)
        if label == "YTD": return pd.Timestamp(today.year, 1, 1)
        if label == "1Y":  return today - pd.DateOffset(years=1)
        if label == "2Y":  return today - pd.DateOffset(years=2)
        if label == "All": return pd.Timestamp("1900-01-01")
        raise ValueError(f"Unknown period: {label}")

    def _series_return(df: pd.DataFrame, value_col: str, start: pd.Timestamp) -> float:
        df = df[df["date"] >= start].sort_values("date")
        if len(df) < 2:
            return 0.0
        return round((df[value_col].iloc[-1] / df[value_col].iloc[0] - 1) * 100, 2)

    # Normalize dates to datetime
    portfolio_df = portfolio_df.copy()
    spy_df = spy_df.copy()
    qqq_df = qqq_df.copy()
    for df in (portfolio_df, spy_df, qqq_df):
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

    periods = ["1M", "3M", "6M", "YTD", "1Y", "2Y", "All"]
    rows = []
    for p in periods:
        start = _period_start(p)
        rows.append({
            "period": p,
            "portfolio_pct": _series_return(portfolio_df, "total_value", start),
            "spy_pct":        _series_return(spy_df, "close", start),
            "qqq_pct":        _series_return(qqq_df, "close", start),
        })
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
pytest tests/test_format_dashboard.py -k "period_returns" -v
```
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tools/format_dashboard.py tests/test_format_dashboard.py
git commit -m "feat: implement compute_period_returns with full period coverage"
```

---

### Task 3: `write_hidden_tabs` — `_PortfolioHistory` + `_Benchmarks`

**Files:**
- Modify: `tools/format_dashboard.py` (replace stub)

This function reads the Historical tab, aggregates daily totals into `_PortfolioHistory`, fetches SPY/QQQ via yfinance, computes period returns, and writes them to `_Benchmarks`. Both tabs are hidden after writing.

**Context about this codebase:**
- yfinance 1.2.1 always returns a MultiIndex DataFrame for multi-ticker downloads; use `raw["Close"]["SPY"]` to get a Series
- The Historical tab has columns: `date`, `ticker`, `shares_held`, `close_price`, `position_value`
- `read_tab_as_df(ws)` from `tools.sheets_client` returns a pandas DataFrame
- `sheet.worksheet(name)` returns a gspread Worksheet; raises `gspread.WorksheetNotFound` if missing
- On re-runs, clear each hidden tab before re-writing (call `ws.clear()` then `ws.append_row(headers)`)

- [ ] **Step 1: Write a smoke test (runs with no Historical data, should not raise)**

```python
# tests/test_format_dashboard.py  (add below existing tests)
from unittest.mock import MagicMock, patch
import pandas as pd


def test_write_hidden_tabs_skips_gracefully_when_historical_empty():
    """write_hidden_tabs should return without error if Historical tab is empty."""
    from tools.format_dashboard import write_hidden_tabs

    mock_ws = MagicMock()
    mock_sheet = MagicMock()
    mock_sheet.worksheet.return_value = mock_ws

    with patch("tools.format_dashboard.read_tab_as_df", return_value=pd.DataFrame()):
        # Should not raise
        write_hidden_tabs(mock_sheet)
```

- [ ] **Step 2: Run test — expect failure (NotImplementedError)**

```bash
pytest tests/test_format_dashboard.py::test_write_hidden_tabs_skips_gracefully_when_historical_empty -v
```

- [ ] **Step 3: Implement `write_hidden_tabs`** (replace the stub)

```python
def write_hidden_tabs(sheet):
    """
    Build _PortfolioHistory (daily portfolio totals) and _Benchmarks (period returns).
    Both tabs are hidden. Safe to re-run — tabs are cleared before re-writing.
    """
    import yfinance as yf
    from tools.sheets_client import read_tab_as_df

    # ── Read Historical tab ─────────────────────────────────────────────────
    try:
        hist_ws = sheet.worksheet("Historical")
    except Exception:
        print("  [fmt] Skipping hidden tabs: Historical tab not found.")
        return

    hist_df = read_tab_as_df(hist_ws)
    if hist_df.empty:
        print("  [fmt] Skipping hidden tabs: Historical tab is empty.")
        return

    hist_df["date"] = pd.to_datetime(hist_df["date"], errors="coerce")
    hist_df["position_value"] = pd.to_numeric(hist_df["position_value"], errors="coerce")

    # ── Aggregate to daily portfolio totals ─────────────────────────────────
    portfolio_daily = (
        hist_df.groupby("date")["position_value"]
        .sum()
        .reset_index()
        .rename(columns={"position_value": "total_value"})
        .sort_values("date")
    )

    # ── Write _PortfolioHistory ─────────────────────────────────────────────
    ph_headers = ["date", "total_value"]
    try:
        ph_ws = sheet.worksheet("_PortfolioHistory")
        ph_ws.clear()
        ph_ws.append_row(ph_headers)
    except Exception:
        ph_ws = sheet.add_worksheet(title="_PortfolioHistory", rows=2000, cols=2)
        ph_ws.append_row(ph_headers)

    ph_rows = [
        [str(row["date"].date()), round(float(row["total_value"]), 2)]
        for _, row in portfolio_daily.iterrows()
    ]
    if ph_rows:
        ph_ws.append_rows(ph_rows, value_input_option="USER_ENTERED")
    _hide_tab(sheet, ph_ws)

    # ── Fetch SPY and QQQ via yfinance ──────────────────────────────────────
    start_date = str(portfolio_daily["date"].min().date())
    try:
        raw = yf.download(
            ["SPY", "QQQ"], start=start_date, auto_adjust=True, progress=False
        )
        # yfinance 1.x always returns MultiIndex for list of tickers
        spy_closes = (
            raw["Close"]["SPY"]
            .dropna()
            .reset_index()
            .rename(columns={"Date": "date", "SPY": "close"})
        )
        qqq_closes = (
            raw["Close"]["QQQ"]
            .dropna()
            .reset_index()
            .rename(columns={"Date": "date", "QQQ": "close"})
        )
    except Exception as exc:
        print(f"  [fmt] Warning: yfinance fetch failed ({exc}). Benchmark tab skipped.")
        return

    # ── Compute period returns ──────────────────────────────────────────────
    period_df = compute_period_returns(portfolio_daily, spy_closes, qqq_closes)

    # ── Write _Benchmarks ───────────────────────────────────────────────────
    bm_headers = ["period", "portfolio_pct", "spy_pct", "qqq_pct"]
    try:
        bm_ws = sheet.worksheet("_Benchmarks")
        bm_ws.clear()
        bm_ws.append_row(bm_headers)
    except Exception:
        bm_ws = sheet.add_worksheet(title="_Benchmarks", rows=20, cols=4)
        bm_ws.append_row(bm_headers)

    bm_rows = [
        [row["period"], row["portfolio_pct"], row["spy_pct"], row["qqq_pct"]]
        for _, row in period_df.iterrows()
    ]
    bm_ws.append_rows(bm_rows, value_input_option="USER_ENTERED")
    _hide_tab(sheet, bm_ws)

    print(f"  [fmt] _PortfolioHistory: {len(ph_rows)} rows, _Benchmarks: {len(bm_rows)} rows")
```

- [ ] **Step 4: Run smoke test — expect pass**

```bash
pytest tests/test_format_dashboard.py::test_write_hidden_tabs_skips_gracefully_when_historical_empty -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/format_dashboard.py tests/test_format_dashboard.py
git commit -m "feat: implement write_hidden_tabs — _PortfolioHistory and _Benchmarks"
```

---

### Task 4: `format_holdings` — Dark Pro Holdings tab

**Files:**
- Modify: `tools/format_dashboard.py` (replace stub)
- Modify: `tests/test_format_dashboard.py` (add smoke test)

Holdings tab columns (0-indexed): ticker(0), shares_held(1), avg_cost_basis(2), total_cost_basis(3), current_price(4), current_value(5), unrealized_pnl(6), unrealized_pnl_pct(7), day_change_pct(8)

Formatting to apply:
- Freeze row 1 (header)
- Header row: `_BG_CARD` background, white bold text, 10pt, center-aligned
- Data rows 2+: `_BG_DARK` base / `_BG_ROW_ALT` alternating (via banding), white 10pt text
- Conditional format on col 6 (unrealized_pnl) and col 8 (day_change_pct): green text if > 0, red text if < 0
- Conditional format on col 7 (unrealized_pnl_pct): green badge (green bg + bold green text) if > 0, red badge if < 0

- [ ] **Step 1: Write smoke test**

```python
# tests/test_format_dashboard.py  (add below existing tests)
def test_format_holdings_calls_batch_update():
    from tools.format_dashboard import format_holdings

    mock_ws = MagicMock()
    mock_ws._properties = {"sheetId": 42}
    mock_sheet = MagicMock()
    mock_sheet.fetch_sheet_metadata.return_value = {
        "sheets": [{"properties": {"sheetId": 42}, "bandedRanges": [], "conditionalFormats": []}]
    }

    format_holdings(mock_sheet, mock_ws)

    assert mock_sheet.batch_update.called
```

- [ ] **Step 2: Run — expect failure (NotImplementedError)**

```bash
pytest tests/test_format_dashboard.py::test_format_holdings_calls_batch_update -v
```

- [ ] **Step 3: Implement `format_holdings`** (replace the stub)

```python
def format_holdings(sheet, ws):
    """Apply Dark Pro formatting to the Holdings tab."""
    _clear_tab_formatting(sheet, ws)
    ws_id = _ws_id(ws)
    requests = []

    # Freeze header
    requests.append({
        "updateSheetProperties": {
            "properties": {"sheetId": ws_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }
    })

    # Header row styling (row 0, cols 0-8)
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 0, 1, 0, 9),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _BG_CARD,
                "textFormat": {"foregroundColor": _WHITE, "bold": True, "fontSize": 10},
                "horizontalAlignment": "CENTER",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
        }
    })

    # Data rows: white text on dark background
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 1, 1000, 0, 9),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _BG_DARK,
                "textFormat": {"foregroundColor": _WHITE, "fontSize": 10},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }
    })

    # Alternating row banding
    requests.append({
        "addBanding": {
            "bandedRange": {
                "range": _range(ws_id, 1, 1000, 0, 9),
                "rowProperties": {
                    "firstBandColor": _BG_DARK,
                    "secondBandColor": _BG_ROW_ALT,
                },
            }
        }
    })

    _batch_update(sheet, requests)

    # Conditional formatting (separate batch — must follow banding setup)
    cf = []
    # Columns 6 (unrealized_pnl) and 8 (day_change_pct): green/red text
    for col_idx in [6, 8]:
        cf.append({"addConditionalFormatRule": {"rule": {
            "ranges": [_range(ws_id, 1, 1000, col_idx, col_idx + 1)],
            "booleanRule": {
                "condition": {"type": "NUMBER_GREATER", "values": [{"userEnteredValue": "0"}]},
                "format": {"textFormat": {"foregroundColor": _GREEN}},
            },
        }, "index": 0}})
        cf.append({"addConditionalFormatRule": {"rule": {
            "ranges": [_range(ws_id, 1, 1000, col_idx, col_idx + 1)],
            "booleanRule": {
                "condition": {"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0"}]},
                "format": {"textFormat": {"foregroundColor": _RED}},
            },
        }, "index": 0}})

    # Column 7 (unrealized_pnl_pct): colored badge (bg + text)
    cf.append({"addConditionalFormatRule": {"rule": {
        "ranges": [_range(ws_id, 1, 1000, 7, 8)],
        "booleanRule": {
            "condition": {"type": "NUMBER_GREATER", "values": [{"userEnteredValue": "0"}]},
            "format": {
                "backgroundColor": _GREEN_BG,
                "textFormat": {"foregroundColor": _GREEN, "bold": True},
            },
        },
    }, "index": 0}})
    cf.append({"addConditionalFormatRule": {"rule": {
        "ranges": [_range(ws_id, 1, 1000, 7, 8)],
        "booleanRule": {
            "condition": {"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0"}]},
            "format": {
                "backgroundColor": _RED_BG,
                "textFormat": {"foregroundColor": _RED, "bold": True},
            },
        },
    }, "index": 0}})

    _batch_update(sheet, cf)
```

- [ ] **Step 4: Run smoke test — expect pass**

```bash
pytest tests/test_format_dashboard.py::test_format_holdings_calls_batch_update -v
```

- [ ] **Step 5: Commit**

```bash
git add tools/format_dashboard.py tests/test_format_dashboard.py
git commit -m "feat: implement format_holdings with Dark Pro theme and conditional P&L formatting"
```

---

### Task 5: `format_transactions` — action color-coding

**Files:**
- Modify: `tools/format_dashboard.py` (replace stub)
- Modify: `tests/test_format_dashboard.py` (add smoke test)

Transactions tab columns (0-indexed): date(0), ticker(1), action(2), shares(3), price(4), amount(5), description(6)

Formatting:
- Freeze row 1, dark header (same pattern as Holdings)
- Action column (col 2): BUY=blue text, SELL=orange text, DIVIDEND=teal text, REINVESTMENT=teal text
- Amount column (col 5): negative value = red text, positive = green text
- Date column (col 0): NUMBER format `MM/DD/YYYY`
- Data rows: alternating `_BG_DARK` / `_BG_ROW_ALT`, white text

- [ ] **Step 1: Write smoke test**

```python
# tests/test_format_dashboard.py  (add below existing tests)
def test_format_transactions_calls_batch_update():
    from tools.format_dashboard import format_transactions

    mock_ws = MagicMock()
    mock_ws._properties = {"sheetId": 10}
    mock_sheet = MagicMock()
    mock_sheet.fetch_sheet_metadata.return_value = {
        "sheets": [{"properties": {"sheetId": 10}, "bandedRanges": [], "conditionalFormats": []}]
    }

    format_transactions(mock_sheet, mock_ws)

    assert mock_sheet.batch_update.called
```

- [ ] **Step 2: Run — expect failure (NotImplementedError)**

```bash
pytest tests/test_format_dashboard.py::test_format_transactions_calls_batch_update -v
```

- [ ] **Step 3: Implement `format_transactions`** (replace the stub)

```python
def format_transactions(sheet, ws):
    """Apply Dark Pro formatting and action color-coding to the Transactions tab."""
    _clear_tab_formatting(sheet, ws)
    ws_id = _ws_id(ws)
    requests = []

    # Freeze header
    requests.append({
        "updateSheetProperties": {
            "properties": {"sheetId": ws_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }
    })

    # Header row
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 0, 1, 0, 7),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _BG_CARD,
                "textFormat": {"foregroundColor": _WHITE, "bold": True, "fontSize": 10},
                "horizontalAlignment": "CENTER",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
        }
    })

    # Data rows
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 1, 5000, 0, 7),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _BG_DARK,
                "textFormat": {"foregroundColor": _WHITE, "fontSize": 10},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }
    })

    # Alternating banding
    requests.append({
        "addBanding": {
            "bandedRange": {
                "range": _range(ws_id, 1, 5000, 0, 7),
                "rowProperties": {
                    "firstBandColor": _BG_DARK,
                    "secondBandColor": _BG_ROW_ALT,
                },
            }
        }
    })

    _batch_update(sheet, requests)

    # Conditional formatting: action column (col 2) color-coding
    cf = []
    action_colors = [
        ("BUY",          _BLUE),
        ("SELL",         _ORANGE),
        ("DIVIDEND",     _TEAL),
        ("REINVESTMENT", _TEAL),
    ]
    for action_text, color in action_colors:
        cf.append({"addConditionalFormatRule": {"rule": {
            "ranges": [_range(ws_id, 1, 5000, 2, 3)],
            "booleanRule": {
                "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": action_text}]},
                "format": {"textFormat": {"foregroundColor": color, "bold": True}},
            },
        }, "index": 0}})

    # Amount column (col 5): negative=red, positive=green
    cf.append({"addConditionalFormatRule": {"rule": {
        "ranges": [_range(ws_id, 1, 5000, 5, 6)],
        "booleanRule": {
            "condition": {"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0"}]},
            "format": {"textFormat": {"foregroundColor": _RED}},
        },
    }, "index": 0}})
    cf.append({"addConditionalFormatRule": {"rule": {
        "ranges": [_range(ws_id, 1, 5000, 5, 6)],
        "booleanRule": {
            "condition": {"type": "NUMBER_GREATER", "values": [{"userEnteredValue": "0"}]},
            "format": {"textFormat": {"foregroundColor": _GREEN}},
        },
    }, "index": 0}})

    _batch_update(sheet, cf)
```

- [ ] **Step 4: Run smoke test — expect pass**

```bash
pytest tests/test_format_dashboard.py::test_format_transactions_calls_batch_update -v
```

- [ ] **Step 5: Commit**

```bash
git add tools/format_dashboard.py tests/test_format_dashboard.py
git commit -m "feat: implement format_transactions with BUY/SELL/DIVIDEND color-coding"
```

---

### Task 6: `format_dividends` + `format_historical` — simple Dark Pro headers

**Files:**
- Modify: `tools/format_dashboard.py` (replace two stubs)
- Modify: `tests/test_format_dashboard.py` (add smoke tests)

Dividends tab columns: date(0), ticker(1), amount(2), type(3)
- Frozen header, dark card background, white bold text
- Type column (col 3): DIVIDEND=teal, REINVESTMENT=blue
- Amount (col 2): format as currency `$#,##0.00`

Historical tab: frozen header only (data-only tab, no complex formatting needed).

- [ ] **Step 1: Write smoke tests**

```python
# tests/test_format_dashboard.py  (add below existing tests)
def test_format_dividends_calls_batch_update():
    from tools.format_dashboard import format_dividends

    mock_ws = MagicMock()
    mock_ws._properties = {"sheetId": 20}
    mock_sheet = MagicMock()
    mock_sheet.fetch_sheet_metadata.return_value = {
        "sheets": [{"properties": {"sheetId": 20}, "bandedRanges": [], "conditionalFormats": []}]
    }
    format_dividends(mock_sheet, mock_ws)
    assert mock_sheet.batch_update.called


def test_format_historical_calls_batch_update():
    from tools.format_dashboard import format_historical

    mock_ws = MagicMock()
    mock_ws._properties = {"sheetId": 30}
    mock_sheet = MagicMock()
    format_historical(mock_sheet, mock_ws)
    assert mock_sheet.batch_update.called
```

- [ ] **Step 2: Run — expect failures (NotImplementedError)**

```bash
pytest tests/test_format_dashboard.py -k "format_dividends or format_historical" -v
```

- [ ] **Step 3: Implement both functions** (replace stubs in `tools/format_dashboard.py`)

```python
def format_dividends(sheet, ws):
    """Apply Dark Pro formatting to the Dividends tab."""
    _clear_tab_formatting(sheet, ws)
    ws_id = _ws_id(ws)
    requests = []

    # Freeze header
    requests.append({
        "updateSheetProperties": {
            "properties": {"sheetId": ws_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }
    })

    # Header row
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 0, 1, 0, 4),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _BG_CARD,
                "textFormat": {"foregroundColor": _WHITE, "bold": True, "fontSize": 10},
                "horizontalAlignment": "CENTER",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
        }
    })

    # Data rows
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 1, 5000, 0, 4),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _BG_DARK,
                "textFormat": {"foregroundColor": _WHITE, "fontSize": 10},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }
    })

    # Amount column (col 2): currency format
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 1, 5000, 2, 3),
            "cell": {"userEnteredFormat": {
                "numberFormat": {"type": "CURRENCY", "pattern": '"$"#,##0.00'},
            }},
            "fields": "userEnteredFormat.numberFormat",
        }
    })

    _batch_update(sheet, requests)

    # Type column (col 3): DIVIDEND=teal, REINVESTMENT=blue
    cf = []
    for type_text, color in [("DIVIDEND", _TEAL), ("REINVESTMENT", _BLUE)]:
        cf.append({"addConditionalFormatRule": {"rule": {
            "ranges": [_range(ws_id, 1, 5000, 3, 4)],
            "booleanRule": {
                "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": type_text}]},
                "format": {"textFormat": {"foregroundColor": color, "bold": True}},
            },
        }, "index": 0}})

    _batch_update(sheet, cf)


def format_historical(sheet, ws):
    """Apply minimal Dark Pro formatting to the Historical tab (data-only tab)."""
    ws_id = _ws_id(ws)
    requests = [
        # Freeze header
        {
            "updateSheetProperties": {
                "properties": {"sheetId": ws_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        },
        # Header row
        {
            "repeatCell": {
                "range": _range(ws_id, 0, 1, 0, 5),
                "cell": {"userEnteredFormat": {
                    "backgroundColor": _BG_CARD,
                    "textFormat": {"foregroundColor": _WHITE, "bold": True, "fontSize": 10},
                    "horizontalAlignment": "CENTER",
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
            }
        },
        # Data rows background
        {
            "repeatCell": {
                "range": _range(ws_id, 1, 10000, 0, 5),
                "cell": {"userEnteredFormat": {
                    "backgroundColor": _BG_DARK,
                    "textFormat": {"foregroundColor": _WHITE, "fontSize": 10},
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        },
    ]
    _batch_update(sheet, requests)
```

- [ ] **Step 4: Run smoke tests — expect both pass**

```bash
pytest tests/test_format_dashboard.py -k "format_dividends or format_historical" -v
```

- [ ] **Step 5: Commit**

```bash
git add tools/format_dashboard.py tests/test_format_dashboard.py
git commit -m "feat: implement format_dividends and format_historical with Dark Pro headers"
```

---

### Task 7: `write_dashboard_sections` — KPI row + benchmark comparison table

**Files:**
- Modify: `tools/format_dashboard.py` (replace stub)
- Modify: `tests/test_format_dashboard.py` (add smoke test)

This function rewrites the Dashboard tab with:
- **Row 1:** Tab title "PORTFOLIO DASHBOARD" (merged A1:E1, centered, large white text)
- **Row 2:** KPI labels (5 cards across A2:E2): `TOTAL VALUE`, `UNREALIZED P&L`, `COST BASIS`, `DIVIDENDS YTD`, `BEST PERFORMER`
- **Row 3:** KPI formula values (A3:E3)
- **Row 4:** Empty spacer
- **Row 5:** Section header "PORTFOLIO GROWTH" (A5, left-aligned)
- **Rows 6-25:** Empty rows reserved for chart overlay
- **Row 26:** Section header "vs. BENCHMARKS" (A26)
- **Row 27:** Benchmark table headers: `PERIOD`, `YOUR PORTFOLIO`, `S&P 500`, `QQQ`
- **Rows 28-34:** Benchmark data rows (1M, 3M, 6M, YTD, 1Y, 2Y, All) — values read from `_Benchmarks` tab or left as 0.0% if tab is missing

All cells use Dark Pro colors. Benchmark comparison cells: portfolio column uses conditional formatting `CUSTOM_FORMULA` to be green if portfolio_pct > spy_pct, red otherwise.

- [ ] **Step 1: Write smoke test**

```python
# tests/test_format_dashboard.py  (add below existing tests)
def test_write_dashboard_sections_calls_batch_update():
    from tools.format_dashboard import write_dashboard_sections

    mock_ws = MagicMock()
    mock_ws._properties = {"sheetId": 0}
    mock_sheet = MagicMock()
    mock_sheet.fetch_sheet_metadata.return_value = {
        "sheets": [{"properties": {"sheetId": 0}, "bandedRanges": [], "conditionalFormats": []}]
    }
    # _Benchmarks tab not found — should fall back to zero returns
    mock_sheet.worksheet.side_effect = Exception("not found")

    write_dashboard_sections(mock_sheet, mock_ws)

    assert mock_ws.clear.called or mock_ws.update.called or mock_ws.batch_update.called or mock_sheet.batch_update.called
```

- [ ] **Step 2: Run — expect failure (NotImplementedError)**

```bash
pytest tests/test_format_dashboard.py::test_write_dashboard_sections_calls_batch_update -v
```

- [ ] **Step 3: Implement `write_dashboard_sections`** (replace the stub)

```python
def write_dashboard_sections(sheet, dashboard_ws):
    """
    Rewrite the Dashboard tab with KPI row, section headers, and benchmark comparison table.
    The portfolio growth chart is added separately by add_portfolio_chart().
    """
    _clear_tab_formatting(sheet, dashboard_ws)
    ws_id = _ws_id(dashboard_ws)

    # ── Read benchmark data ─────────────────────────────────────────────────
    period_labels = ["1M", "3M", "6M", "YTD", "1Y", "2Y", "All"]
    bm_data = {p: {"portfolio": 0.0, "spy": 0.0, "qqq": 0.0} for p in period_labels}
    try:
        bm_ws = sheet.worksheet("_Benchmarks")
        from tools.sheets_client import read_tab_as_df
        bm_df = read_tab_as_df(bm_ws)
        if not bm_df.empty:
            for _, row in bm_df.iterrows():
                p = str(row.get("period", ""))
                if p in bm_data:
                    bm_data[p] = {
                        "portfolio": float(row.get("portfolio_pct", 0) or 0),
                        "spy":       float(row.get("spy_pct", 0) or 0),
                        "qqq":       float(row.get("qqq_pct", 0) or 0),
                    }
    except Exception:
        pass  # Benchmarks tab not yet available

    # ── Build cell values ───────────────────────────────────────────────────
    # Row 1 (index 0): title
    # Row 2 (index 1): KPI labels
    # Row 3 (index 2): KPI values (formulas)
    # Row 4 (index 3): spacer
    # Row 5 (index 4): "PORTFOLIO GROWTH" header
    # Rows 6-25 (index 5-24): chart zone (empty)
    # Row 26 (index 25): "vs. BENCHMARKS" header
    # Row 27 (index 26): benchmark table column headers
    # Rows 28-34 (index 27-33): benchmark data rows

    kpi_labels = ["TOTAL VALUE", "UNREALIZED P&L", "COST BASIS", "DIVIDENDS YTD", "BEST PERFORMER"]
    kpi_formulas = [
        "=SUM(Holdings!F:F)",
        "=SUM(Holdings!G:G)",
        "=SUM(Holdings!D:D)",
        "=SUM(Dividends!C:C)",
        '=IFERROR(INDEX(Holdings!A2:A,MATCH(MAX(Holdings!H2:H),Holdings!H2:H,0))&" +"&TEXT(MAX(Holdings!H2:H),"0.00%"),"—")',
    ]

    bm_header_row = ["PERIOD", "YOUR PORTFOLIO", "S&P 500", "QQQ"]
    bm_rows = [
        [p, bm_data[p]["portfolio"], bm_data[p]["spy"], bm_data[p]["qqq"]]
        for p in period_labels
    ]

    # Clear and write all cells
    dashboard_ws.clear()
    # Write using a list of rows; pad shorter rows with empty strings
    all_rows = [
        ["PORTFOLIO DASHBOARD", "", "", "", ""],    # row 1
        kpi_labels,                                  # row 2
        kpi_formulas,                                # row 3
        ["", "", "", "", ""],                         # row 4 spacer
        ["PORTFOLIO GROWTH", "", "", "", ""],         # row 5
    ]
    all_rows += [[""] * 5 for _ in range(20)]        # rows 6-25: chart zone
    all_rows += [
        ["vs. BENCHMARKS", "", "", ""],              # row 26
        bm_header_row,                               # row 27
    ]
    all_rows += bm_rows                              # rows 28-34

    dashboard_ws.update(all_rows, value_input_option="USER_ENTERED")

    # ── Formatting requests ─────────────────────────────────────────────────
    requests = []

    # Full sheet dark background
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 0, 200, 0, 10),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _BG_DARK,
                "textFormat": {"foregroundColor": _WHITE, "fontSize": 10},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }
    })

    # Row 1: title — large, bold, centered, card background
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 0, 1, 0, 5),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _BG_CARD,
                "textFormat": {"foregroundColor": _WHITE, "bold": True, "fontSize": 16},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
        }
    })

    # Row 2: KPI labels — small gray caps
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 1, 2, 0, 5),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _BG_CARD,
                "textFormat": {"foregroundColor": _GRAY, "bold": False, "fontSize": 8},
                "horizontalAlignment": "CENTER",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
        }
    })

    # Row 3: KPI values — large, bold, card background
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 2, 3, 0, 5),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _BG_CARD,
                "textFormat": {"foregroundColor": _WHITE, "bold": True, "fontSize": 14},
                "horizontalAlignment": "CENTER",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
        }
    })

    # Row 3, col 1 (Unrealized P&L): color conditional (handled below in CF)
    # Row 3, col 4 (Best Performer): purple
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 2, 3, 4, 5),
            "cell": {"userEnteredFormat": {
                "textFormat": {"foregroundColor": _PURPLE, "bold": True, "fontSize": 14},
            }},
            "fields": "userEnteredFormat.textFormat",
        }
    })

    # Row 3, col 3 (Dividends YTD): blue
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 2, 3, 3, 4),
            "cell": {"userEnteredFormat": {
                "textFormat": {"foregroundColor": _BLUE, "bold": True, "fontSize": 14},
            }},
            "fields": "userEnteredFormat.textFormat",
        }
    })

    # Section headers: "PORTFOLIO GROWTH" and "vs. BENCHMARKS"
    for row_idx in [4, 25]:
        requests.append({
            "repeatCell": {
                "range": _range(ws_id, row_idx, row_idx + 1, 0, 5),
                "cell": {"userEnteredFormat": {
                    "backgroundColor": _BG_CARD,
                    "textFormat": {"foregroundColor": _BLUE, "bold": True, "fontSize": 11},
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        })

    # Benchmark table header row (row 27, index 26)
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 26, 27, 0, 4),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _BG_CARD,
                "textFormat": {"foregroundColor": _WHITE, "bold": True, "fontSize": 10},
                "horizontalAlignment": "CENTER",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
        }
    })

    # Benchmark data cells (rows 28-34, index 27-34): centered, card bg
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 27, 34, 0, 4),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _BG_CARD,
                "textFormat": {"foregroundColor": _WHITE, "bold": True, "fontSize": 11},
                "horizontalAlignment": "CENTER",
                "numberFormat": {"type": "NUMBER", "pattern": '#,##0.00"%"'},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,numberFormat)",
        }
    })

    # Period label column (col 0, rows 28-34): gray text
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 27, 34, 0, 1),
            "cell": {"userEnteredFormat": {
                "textFormat": {"foregroundColor": _GRAY, "bold": False},
            }},
            "fields": "userEnteredFormat.textFormat",
        }
    })

    _batch_update(sheet, requests)

    # ── KPI Unrealized P&L: green if positive, red if negative ─────────────
    cf = []
    cf.append({"addConditionalFormatRule": {"rule": {
        "ranges": [_range(ws_id, 2, 3, 1, 2)],  # row 3, col B (Unrealized P&L)
        "booleanRule": {
            "condition": {"type": "NUMBER_GREATER_THAN_EQ", "values": [{"userEnteredValue": "0"}]},
            "format": {"textFormat": {"foregroundColor": _GREEN, "bold": True, "fontSize": 14}},
        },
    }, "index": 0}})
    cf.append({"addConditionalFormatRule": {"rule": {
        "ranges": [_range(ws_id, 2, 3, 1, 2)],
        "booleanRule": {
            "condition": {"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0"}]},
            "format": {"textFormat": {"foregroundColor": _RED, "bold": True, "fontSize": 14}},
        },
    }, "index": 0}})

    # ── Benchmark: portfolio column (col 1, rows 28-34) green if > spy ─────
    # CUSTOM_FORMULA: relative row reference — formula anchored to top-left of range
    cf.append({"addConditionalFormatRule": {"rule": {
        "ranges": [_range(ws_id, 27, 34, 1, 2)],
        "booleanRule": {
            "condition": {
                "type": "CUSTOM_FORMULA",
                "values": [{"userEnteredValue": "=$B28>$C28"}],
            },
            "format": {
                "backgroundColor": _GREEN_BG,
                "textFormat": {"foregroundColor": _GREEN, "bold": True},
            },
        },
    }, "index": 0}})
    cf.append({"addConditionalFormatRule": {"rule": {
        "ranges": [_range(ws_id, 27, 34, 1, 2)],
        "booleanRule": {
            "condition": {
                "type": "CUSTOM_FORMULA",
                "values": [{"userEnteredValue": "=$B28<$C28"}],
            },
            "format": {
                "backgroundColor": _RED_BG,
                "textFormat": {"foregroundColor": _RED, "bold": True},
            },
        },
    }, "index": 0}})

    # SPY and QQQ columns: positive = green text, negative = red text
    for col_idx in [2, 3]:
        cf.append({"addConditionalFormatRule": {"rule": {
            "ranges": [_range(ws_id, 27, 34, col_idx, col_idx + 1)],
            "booleanRule": {
                "condition": {"type": "NUMBER_GREATER_THAN_EQ", "values": [{"userEnteredValue": "0"}]},
                "format": {"textFormat": {"foregroundColor": _GREEN}},
            },
        }, "index": 0}})
        cf.append({"addConditionalFormatRule": {"rule": {
            "ranges": [_range(ws_id, 27, 34, col_idx, col_idx + 1)],
            "booleanRule": {
                "condition": {"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0"}]},
                "format": {"textFormat": {"foregroundColor": _RED}},
            },
        }, "index": 0}})

    _batch_update(sheet, cf)
```

- [ ] **Step 4: Run smoke test — expect pass**

```bash
pytest tests/test_format_dashboard.py::test_write_dashboard_sections_calls_batch_update -v
```

- [ ] **Step 5: Commit**

```bash
git add tools/format_dashboard.py tests/test_format_dashboard.py
git commit -m "feat: implement write_dashboard_sections with KPI row and benchmark comparison table"
```

---

### Task 8: `add_portfolio_chart` — native Google Sheets line chart

**Files:**
- Modify: `tools/format_dashboard.py` (replace stub)
- Modify: `tests/test_format_dashboard.py` (add smoke test)

Creates a LINE chart in the Dashboard tab sourced from `_PortfolioHistory` (date col = domain, total_value col = series). On re-runs, deletes existing charts anchored to the Dashboard tab before creating a new one.

The chart is positioned at Dashboard row 6, column 0 (0-indexed row 5), spanning ~700×300 pixels.

**Important:** `sheet.fetch_sheet_metadata()` returns charts in `sheets[*].charts` — each chart has a `chartId` and `position.overlayPosition.anchorCell.sheetId`. If `anchorCell.sheetId` matches the Dashboard ws_id, delete it first via `deleteEmbeddedObject`.

If `_PortfolioHistory` tab does not exist (e.g., first run before hidden tabs are written), skip chart creation and log a warning.

- [ ] **Step 1: Write smoke test**

```python
# tests/test_format_dashboard.py  (add below existing tests)
def test_add_portfolio_chart_skips_when_no_history_tab():
    from tools.format_dashboard import add_portfolio_chart

    mock_ws = MagicMock()
    mock_ws._properties = {"sheetId": 0}
    mock_sheet = MagicMock()
    mock_sheet.fetch_sheet_metadata.return_value = {"sheets": []}
    # _PortfolioHistory not found
    mock_sheet.worksheet.side_effect = Exception("not found")

    # Should not raise
    add_portfolio_chart(mock_sheet, mock_ws)
```

- [ ] **Step 2: Run — expect failure (NotImplementedError)**

```bash
pytest tests/test_format_dashboard.py::test_add_portfolio_chart_skips_when_no_history_tab -v
```

- [ ] **Step 3: Implement `add_portfolio_chart`** (replace the stub)

```python
def add_portfolio_chart(sheet, dashboard_ws):
    """
    Create (or replace) a LINE chart on the Dashboard tab sourced from _PortfolioHistory.
    Positioned at Dashboard row 6 (0-indexed row 5), column A, 700×300 pixels.
    No-ops gracefully if _PortfolioHistory does not exist yet.
    """
    # ── Get _PortfolioHistory worksheet ────────────────────────────────────
    try:
        ph_ws = sheet.worksheet("_PortfolioHistory")
    except Exception:
        print("  [fmt] Skipping portfolio chart: _PortfolioHistory not found.")
        return

    dashboard_ws_id = _ws_id(dashboard_ws)
    ph_ws_id = _ws_id(ph_ws)

    # ── Delete any existing charts anchored to Dashboard ───────────────────
    meta = sheet.fetch_sheet_metadata()
    delete_reqs = []
    for s in meta.get("sheets", []):
        for chart in s.get("charts", []):
            anchor = (
                chart.get("position", {})
                .get("overlayPosition", {})
                .get("anchorCell", {})
                .get("sheetId")
            )
            if anchor == dashboard_ws_id:
                delete_reqs.append({
                    "deleteEmbeddedObject": {"objectId": chart["chartId"]}
                })
    if delete_reqs:
        _batch_update(sheet, delete_reqs)

    # ── Add new line chart ──────────────────────────────────────────────────
    _batch_update(sheet, [{
        "addChart": {
            "chart": {
                "spec": {
                    "title": "Portfolio Growth",
                    "titleTextFormat": {
                        "foregroundColor": _WHITE,
                        "fontSize": 13,
                        "bold": True,
                    },
                    "backgroundColor": _BG_CARD,
                    "basicChart": {
                        "chartType": "LINE",
                        "legendPosition": "NO_LEGEND",
                        "headerCount": 1,
                        "axis": [
                            {
                                "position": "BOTTOM_AXIS",
                                "format": {"foregroundColor": _GRAY, "fontSize": 8},
                            },
                            {
                                "position": "LEFT_AXIS",
                                "title": "Portfolio Value ($)",
                                "format": {"foregroundColor": _GRAY, "fontSize": 8},
                            },
                        ],
                        "domains": [{
                            "domain": {
                                "sourceRange": {
                                    "sources": [{
                                        "sheetId": ph_ws_id,
                                        "startRowIndex": 0,
                                        "endRowIndex": 2000,
                                        "startColumnIndex": 0,
                                        "endColumnIndex": 1,
                                    }]
                                }
                            }
                        }],
                        "series": [{
                            "series": {
                                "sourceRange": {
                                    "sources": [{
                                        "sheetId": ph_ws_id,
                                        "startRowIndex": 0,
                                        "endRowIndex": 2000,
                                        "startColumnIndex": 1,
                                        "endColumnIndex": 2,
                                    }]
                                }
                            },
                            "targetAxis": "LEFT_AXIS",
                            "color": _BLUE,
                            "lineStyle": {"width": 2, "type": "SOLID"},
                        }],
                    },
                },
                "position": {
                    "overlayPosition": {
                        "anchorCell": {
                            "sheetId": dashboard_ws_id,
                            "rowIndex": 5,     # row 6 (0-indexed)
                            "columnIndex": 0,
                        },
                        "widthPixels": 700,
                        "heightPixels": 300,
                        "offsetXPixels": 0,
                        "offsetYPixels": 0,
                    }
                },
            }
        }
    }])
```

- [ ] **Step 4: Run smoke test — expect pass**

```bash
pytest tests/test_format_dashboard.py::test_add_portfolio_chart_skips_when_no_history_tab -v
```

- [ ] **Step 5: Run all tests to confirm no regressions**

```bash
pytest tests/test_format_dashboard.py -v
```
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add tools/format_dashboard.py tests/test_format_dashboard.py
git commit -m "feat: implement add_portfolio_chart with Dark Pro line chart from _PortfolioHistory"
```

---

### Task 9: Wire `apply_formatting` into `import_transactions.py`

**Files:**
- Modify: `tools/import_transactions.py`
  - Remove `write_dashboard()` function and its call from `main()`
  - Add `apply_formatting(sheet)` call at the end of `main()`, after all tab writes
  - Update progress print to reflect 5 steps becoming 6

**Context:** `write_dashboard()` writes a simple metric-table to the Dashboard tab. Its formulas (`=SUM(Holdings!F:F)` etc.) are now duplicated inside `write_dashboard_sections()` in `format_dashboard.py`. Remove the old function to avoid conflicts on re-run.

- [ ] **Step 1: Write a test verifying `write_dashboard` is gone and `apply_formatting` is called**

```python
# tests/test_format_dashboard.py  (add below existing tests)
def test_import_transactions_calls_apply_formatting():
    """apply_formatting should be importable and callable from import_transactions.main context."""
    import importlib
    import tools.import_transactions as it
    src = importlib.util.find_spec("tools.import_transactions").origin
    with open(src) as f:
        source = f.read()
    assert "apply_formatting" in source, "import_transactions.py must call apply_formatting"
    assert "write_dashboard" not in source, "write_dashboard should be removed from import_transactions.py"
```

- [ ] **Step 2: Run — expect failure**

```bash
pytest tests/test_format_dashboard.py::test_import_transactions_calls_apply_formatting -v
```
Expected: FAIL (`write_dashboard` still present, `apply_formatting` not imported)

- [ ] **Step 3: Edit `tools/import_transactions.py`**

Remove the entire `write_dashboard` function (lines containing `def write_dashboard(ws):` through its end), and update `main()`:

**Remove from `main()`:**
```python
    dashboard_ws = get_or_create_tab(sheet, "Dashboard", _DASHBOARD_HEADERS)
    write_dashboard(dashboard_ws)
```

**Replace the final print block in `main()` with:**
```python
    print("\n[5/5] Applying Dark Pro formatting and analytics...")
    from tools.format_dashboard import apply_formatting
    apply_formatting(sheet)

    print("\nDone. All tabs updated.")
    print(f"  Sheet: https://docs.google.com/spreadsheets/d/{os.environ['GOOGLE_SHEET_ID']}")
```

Also update the earlier print statement `[4/5]` step count comment if present.

- [ ] **Step 4: Run test — expect pass**

```bash
pytest tests/test_format_dashboard.py::test_import_transactions_calls_apply_formatting -v
```

- [ ] **Step 5: Run all tests to confirm no regressions**

```bash
pytest tests/ -v
```
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add tools/import_transactions.py tests/test_format_dashboard.py
git commit -m "feat: wire apply_formatting into import_transactions.main, remove write_dashboard"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Dark Pro theme (`#0f1117` bg, white text, `#00c805` green, `#ff4d4d` red, `#4f8ef7` blue, `#a78bfa` purple) — Task 1 constants
- [x] Dashboard KPI row (5 cards: Total Value, Unrealized P&L, Cost Basis, Dividends, Best Performer) — Task 7
- [x] Portfolio growth chart (line chart from full history) — Task 8
- [x] Benchmark comparison panel (SPY + QQQ, all periods at once, green if beating) — Tasks 3 + 7
- [x] `_Benchmarks` hidden tab with SPY/QQQ data — Task 3
- [x] Holdings tab: alternating rows, Return % badge, Day Change green/red — Task 4
- [x] Transactions tab: action color-coding BUY/SELL/DIVIDEND, amount +/- colors — Task 5
- [x] Dividends tab: currency format, DIVIDEND/REINVESTMENT color — Task 6
- [x] Historical tab: frozen header — Task 6
- [x] Called from `import_transactions.py main()` — Task 9
- [x] Period selector via all-periods-at-once benchmark table (not a toggle — Sheets limitation) — Task 7

**No placeholders:** All task steps contain complete code.

**Type consistency:** `_range()`, `_ws_id()`, `_batch_update()` used consistently across all tasks. `compute_period_returns` signature matches usage in `write_hidden_tabs`.
