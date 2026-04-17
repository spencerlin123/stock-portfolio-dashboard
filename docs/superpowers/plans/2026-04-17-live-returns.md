# Live Returns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace static `_Benchmarks` reads in `app.py` with live return computation using `_PortfolioHistory` + live Holdings sum + Yahoo Finance SPY/QQQ, and make `import_transactions.py` only fetch missing price history instead of all-time prices on every run.

**Architecture:** `app.py` gains a `_compute_live_returns(sheet)` function that assembles portfolio history in-memory, appends today's live value from the Holdings tab, fetches only SPY/QQQ from Yahoo Finance, and calls the existing `compute_period_returns()` logic. Results are cached with a smart TTL (5 min market hours, 1 hr off-hours). In `import_transactions.py`, `write_historical()` reads the max date already in the Historical tab and passes that as `start_date` to Yahoo Finance instead of the first-ever trade date.

**Tech Stack:** Python 3.9+, Flask, gspread, pandas, `zoneinfo` (stdlib), Yahoo Finance v8 API (already used), pytest + unittest.mock

---

## File Map

| File | Change |
|------|--------|
| `app.py` | Add `_cache_ttl()`, `_compute_live_returns()`, replace three `_Benchmarks` `_read_tab` calls |
| `tools/import_transactions.py` | Incremental `start_date` in `write_historical()` |
| `tests/test_app.py` | Update existing tests that mock `_Benchmarks`; add cache TTL tests |
| `tests/test_import_transactions.py` | New file — test incremental start_date logic |

---

## Task 1: Add `_cache_ttl()` and `_compute_live_returns()` to `app.py`

**Files:**
- Modify: `app.py` (after the `_sector_cache` block, around line 44)

- [ ] **Step 1: Write failing tests for `_cache_ttl()`**

Add to `tests/test_app.py`:

```python
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")


def test_cache_ttl_during_market_hours():
    """Returns 300 (5 min) during weekday market hours."""
    from app import _cache_ttl
    market_time = datetime(2026, 4, 14, 10, 0, 0, tzinfo=_ET)  # Monday 10am ET
    with patch("app.datetime") as mock_dt:
        mock_dt.now.return_value = market_time
        assert _cache_ttl() == 300


def test_cache_ttl_outside_market_hours():
    """Returns 3600 (1 hr) outside market hours."""
    from app import _cache_ttl
    evening = datetime(2026, 4, 14, 20, 0, 0, tzinfo=_ET)  # Monday 8pm ET
    with patch("app.datetime") as mock_dt:
        mock_dt.now.return_value = evening
        assert _cache_ttl() == 3600


def test_cache_ttl_on_weekend():
    """Returns 3600 (1 hr) on weekends."""
    from app import _cache_ttl
    saturday = datetime(2026, 4, 12, 11, 0, 0, tzinfo=_ET)  # Saturday 11am ET
    with patch("app.datetime") as mock_dt:
        mock_dt.now.return_value = saturday
        assert _cache_ttl() == 3600
```

- [ ] **Step 2: Run to confirm they fail**

```
pytest tests/test_app.py::test_cache_ttl_during_market_hours tests/test_app.py::test_cache_ttl_outside_market_hours tests/test_app.py::test_cache_ttl_on_weekend -v
```

Expected: `ImportError` or `AttributeError` — `_cache_ttl` not yet defined.

- [ ] **Step 3: Add imports and cache globals to `app.py`**

After the existing imports block (after `from tools.sheets_client import get_sheet, read_tab_as_df` on line 19), add:

```python
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
_RETURNS_CACHE: dict = {}
_RETURNS_CACHE_TS: float = 0.0
```

- [ ] **Step 4: Add `_cache_ttl()` to `app.py`**

Add after the `_SECTOR_TTL` line (around line 46), before `def _fetch_sectors`:

```python
def _cache_ttl() -> float:
    """5-min TTL during market hours (9:30–16:00 ET weekdays), 1-hr otherwise."""
    now_et = datetime.now(_ET)
    if (
        now_et.weekday() < 5
        and now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        <= now_et
        <= now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    ):
        return 300
    return 3600
```

- [ ] **Step 5: Run cache TTL tests — confirm they pass**

```
pytest tests/test_app.py::test_cache_ttl_during_market_hours tests/test_app.py::test_cache_ttl_outside_market_hours tests/test_app.py::test_cache_ttl_on_weekend -v
```

Expected: all three PASS.

- [ ] **Step 6: Add `_compute_live_returns()` to `app.py`**

Add after `_cache_ttl()` and before `app = Flask(...)`:

```python
def _compute_live_returns(sheet) -> dict:
    """
    Compute period returns live for brokerage, IRA, and overall accounts.
    Reads _PortfolioHistory + live Holdings sum from Sheets; fetches SPY/QQQ from Yahoo Finance.
    Cached: 5 min during market hours, 1 hr otherwise.

    Returns:
        {
            'brokerage': [{period, twr_pct, mwr_pct, spy_pct, qqq_pct}, ...],
            'ira':       [{period, twr_pct, mwr_pct, spy_pct, qqq_pct}, ...],
            'overall':   [{period, twr_pct, mwr_pct, spy_pct, qqq_pct}, ...],
        }
    """
    import time as _t
    global _RETURNS_CACHE, _RETURNS_CACHE_TS

    now = _t.time()
    if _RETURNS_CACHE and now - _RETURNS_CACHE_TS < _cache_ttl():
        return _RETURNS_CACHE

    from tools.format_dashboard import compute_period_returns, _fetch_spy_qqq, _build_daily_cf

    today_ts = pd.Timestamp(datetime.now(timezone.utc).date())

    def _ph_df(history_records: list, today_val: float) -> pd.DataFrame:
        """Build portfolio history DataFrame with today's live value appended."""
        if not history_records:
            return pd.DataFrame(columns=["date", "total_value"])
        df = pd.DataFrame(history_records)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["total_value"] = pd.to_numeric(df["total_value"], errors="coerce")
        df = df[df["date"] < today_ts]
        today_row = pd.DataFrame([{"date": today_ts, "total_value": float(today_val)}])
        return pd.concat([df, today_row], ignore_index=True).sort_values("date").reset_index(drop=True)

    def _txns_df(records: list) -> pd.DataFrame:
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
        return df

    def _today_val(holdings_records: list) -> float:
        return sum(float(h.get("current_value") or 0) for h in holdings_records)

    # Read inputs from Sheets
    brk_ph   = _read_tab(sheet, "_PortfolioHistory",     _HISTORY_COLS,      _HISTORY_NUMERIC)
    ira_ph   = _read_tab(sheet, "_IRA_PortfolioHistory", _HISTORY_COLS,      _HISTORY_NUMERIC)
    brk_h    = _read_tab(sheet, "Holdings",              _HOLDINGS_COLS,     _HOLDINGS_NUMERIC)
    ira_h    = _read_tab(sheet, "IRA_Holdings",          _HOLDINGS_COLS,     _HOLDINGS_NUMERIC)
    brk_txns = _read_tab(sheet, "Transactions",          _TRANSACTIONS_COLS, _TRANSACTIONS_NUMERIC)
    ira_txns = _read_tab(sheet, "IRA_Transactions",      _TRANSACTIONS_COLS, _TRANSACTIONS_NUMERIC)

    brk_ph_df   = _ph_df(brk_ph, _today_val(brk_h))
    ira_ph_df   = _ph_df(ira_ph, _today_val(ira_h))
    brk_txns_df = _txns_df(brk_txns)
    ira_txns_df = _txns_df(ira_txns)

    # Overall: sum daily values across both accounts
    combined = pd.concat([brk_ph_df, ira_ph_df], ignore_index=True)
    overall_ph_df = (
        combined.groupby("date")["total_value"]
        .sum().reset_index().sort_values("date").reset_index(drop=True)
    )

    # Fetch SPY/QQQ once — from earliest date across all histories
    all_starts = [df["date"].min() for df in [brk_ph_df, ira_ph_df] if not df.empty]
    start_date = str(min(all_starts).date()) if all_starts else str(today_ts.date())
    spy_df, qqq_df = _fetch_spy_qqq(start_date)

    # Overall CF: build per-account independently, then sum by date
    combined_cf: dict = {}
    for txns in [brk_txns_df, ira_txns_df]:
        if not txns.empty:
            for d, amt in _build_daily_cf(txns).items():
                combined_cf[d] = combined_cf.get(d, 0.0) + amt

    brk_ret     = compute_period_returns(brk_ph_df,     spy_df, qqq_df, brk_txns_df)
    ira_ret     = compute_period_returns(ira_ph_df,     spy_df, qqq_df, ira_txns_df)
    overall_ret = compute_period_returns(overall_ph_df, spy_df, qqq_df,
                                         daily_cf_override=combined_cf)

    result = {
        "brokerage": brk_ret.to_dict("records"),
        "ira":       ira_ret.to_dict("records"),
        "overall":   overall_ret.to_dict("records"),
    }
    _RETURNS_CACHE    = result
    _RETURNS_CACHE_TS = now
    return result
```

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: add _cache_ttl and _compute_live_returns to app.py"
```

---

## Task 2: Wire `_compute_live_returns()` into `/api/data` and update tests

**Files:**
- Modify: `app.py` (lines 214–218 in `/api/data`)
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write a failing test that expects live returns (no `_Benchmarks` read)**

Replace the existing `test_api_data_keys` test in `tests/test_app.py` with:

```python
@patch("app._compute_live_returns")
@patch("app.get_sheet")
def test_api_data_keys(mock_get_sheet, mock_live_returns, client):
    sheet = MagicMock()
    mock_get_sheet.return_value = sheet
    mock_live_returns.return_value = {
        "brokerage": [{"period": "MTD", "twr_pct": 1.0, "mwr_pct": 1.0, "spy_pct": 0.5, "qqq_pct": 0.3}],
        "ira":       [],
        "overall":   [],
    }

    def worksheet_side_effect(name):
        mapping = {
            "Holdings":     _mock_ws(_make_holdings_df()),
            "Transactions": _mock_ws(_make_transactions_df()),
            "Dividends":    _mock_ws(_make_dividends_df()),
            "_PortfolioHistory": _mock_ws(_make_history_df()),
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
    assert data["benchmarks"] == [{"period": "MTD", "twr_pct": 1.0, "mwr_pct": 1.0, "spy_pct": 0.5, "qqq_pct": 0.3}]
```

Also replace `test_api_data_holdings_numeric` and `test_api_data_missing_hidden_tabs` with patched versions:

```python
@patch("app._compute_live_returns")
@patch("app.get_sheet")
def test_api_data_holdings_numeric(mock_get_sheet, mock_live_returns, client):
    sheet = MagicMock()
    mock_get_sheet.return_value = sheet
    mock_live_returns.return_value = {"brokerage": [], "ira": [], "overall": []}

    def worksheet_side_effect(name):
        mapping = {
            "Holdings":     _mock_ws(_make_holdings_df()),
            "Transactions": _mock_ws(_make_transactions_df()),
            "Dividends":    _mock_ws(_make_dividends_df()),
            "_PortfolioHistory": _mock_ws(_make_history_df()),
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


@patch("app._compute_live_returns")
@patch("app.get_sheet")
def test_api_data_missing_hidden_tabs(mock_get_sheet, mock_live_returns, client):
    """If _PortfolioHistory doesn't exist yet, return empty list; benchmarks come from live compute."""
    sheet = MagicMock()
    mock_get_sheet.return_value = sheet
    mock_live_returns.return_value = {"brokerage": [], "ira": [], "overall": []}

    def worksheet_side_effect(name):
        if name == "_PortfolioHistory":
            import gspread
            raise gspread.WorksheetNotFound(name)
        mapping = {
            "Holdings":     _mock_ws(_make_holdings_df()),
            "Transactions": _mock_ws(_make_transactions_df()),
            "Dividends":    _mock_ws(_make_dividends_df()),
        }
        return mapping[name]

    sheet.worksheet.side_effect = worksheet_side_effect

    resp = client.get("/api/data")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["portfolio_history"] == []
    assert data["benchmarks"] == []
```

- [ ] **Step 2: Run updated tests to confirm they fail (function not yet wired)**

```
pytest tests/test_app.py::test_api_data_keys tests/test_app.py::test_api_data_holdings_numeric tests/test_app.py::test_api_data_missing_hidden_tabs -v
```

Expected: tests that assert `data["benchmarks"]` content will fail because `/api/data` still reads `_Benchmarks` from Sheets.

- [ ] **Step 3: Replace `_Benchmarks` reads in `/api/data`**

In `app.py`, find this block inside `api_data()` (around lines 214–218):

```python
        benchmarks        = _read_tab(sheet, "_Benchmarks",       _BENCHMARKS_COLS, _BENCHMARKS_NUMERIC)
```

And these two lines nearby:

```python
        ira_benchmarks        = _read_tab(sheet, "_IRA_Benchmarks",       _BENCHMARKS_COLS,    _BENCHMARKS_NUMERIC)
```

```python
        overall_benchmarks        = _read_tab(sheet, "_Overall_Benchmarks",       _BENCHMARKS_COLS, _BENCHMARKS_NUMERIC)
```

Replace all three with a single block (place it before the `analytics_rows` line):

```python
        _live              = _compute_live_returns(sheet)
        benchmarks         = _live["brokerage"]
        ira_benchmarks     = _live["ira"]
        overall_benchmarks = _live["overall"]
```

Remove the now-unused three `_read_tab` calls for `_Benchmarks`, `_IRA_Benchmarks`, `_Overall_Benchmarks`.

- [ ] **Step 4: Run updated tests — confirm they pass**

```
pytest tests/test_app.py::test_api_data_keys tests/test_app.py::test_api_data_holdings_numeric tests/test_app.py::test_api_data_missing_hidden_tabs tests/test_app.py::test_api_data_sheets_unavailable tests/test_app.py::test_index_route -v
```

Expected: all PASS.

- [ ] **Step 5: Run full test suite**

```
pytest tests/ -v
```

Expected: all existing tests pass (or pre-existing failures unrelated to this change).

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: compute returns live in app.py, replace static _Benchmarks reads"
```

---

## Task 3: Incremental Historical fetch in `import_transactions.py`

**Files:**
- Modify: `tools/import_transactions.py` (inside `write_historical()`, around line 249)
- Create: `tests/test_import_transactions.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_import_transactions.py`:

```python
import pandas as pd
import pytest
from datetime import date
from unittest.mock import MagicMock, patch


def _make_transactions():
    return pd.DataFrame([
        {"date": pd.Timestamp("2024-01-10"), "ticker": "AAPL", "action": "BUY",
         "shares": 10.0, "price": 150.0, "amount": -1500.0, "description": ""},
        {"date": pd.Timestamp("2024-06-01"), "ticker": "AAPL", "action": "BUY",
         "shares": 5.0,  "price": 160.0, "amount": -800.0,  "description": ""},
    ])


def _make_existing_historical_df(max_date="2026-04-10"):
    """Simulate an already-populated Historical tab."""
    return pd.DataFrame([
        {"date": "2026-04-08", "ticker": "AAPL", "shares_held": "10", "close_price": "175", "position_value": "1750"},
        {"date": max_date,     "ticker": "AAPL", "shares_held": "15", "close_price": "178", "position_value": "2670"},
    ])


@patch("tools.import_transactions._fetch_all_closes")
def test_write_historical_incremental_start_date(mock_fetch):
    """When Historical tab already has data, fetch only from (max_date - 5 days), not all-time."""
    from tools.import_transactions import write_historical
    from tools.sheets_client import read_tab_as_df

    mock_fetch.return_value = pd.DataFrame()  # no new prices needed for this assertion

    mock_ws = MagicMock()
    existing_df = _make_existing_historical_df("2026-04-10")

    with patch("tools.import_transactions.read_tab_as_df", return_value=existing_df):
        write_historical(mock_ws, _make_transactions())

    assert mock_fetch.called, "_fetch_all_closes should have been called"
    call_kwargs = mock_fetch.call_args
    # start_date is the 2nd positional arg (index 1) or kwarg
    start_date = call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get("start_date")
    # Should be 2026-04-05 (2026-04-10 minus 5 days) or later — NOT 2024-01-10 (all-time)
    assert start_date >= date(2026, 4, 1), (
        f"Expected incremental start near 2026-04-10, got {start_date} — "
        "fetch should not go back to first trade date when history already exists"
    )


@patch("tools.import_transactions._fetch_all_closes")
def test_write_historical_full_fetch_on_first_run(mock_fetch):
    """When Historical tab is empty, fetch from the first trade date."""
    from tools.import_transactions import write_historical

    mock_fetch.return_value = pd.DataFrame()

    mock_ws = MagicMock()
    empty_df = pd.DataFrame(columns=["date", "ticker", "shares_held", "close_price", "position_value"])

    with patch("tools.import_transactions.read_tab_as_df", return_value=empty_df):
        write_historical(mock_ws, _make_transactions())

    assert mock_fetch.called
    call_kwargs = mock_fetch.call_args
    start_date = call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get("start_date")
    # Should fetch from first trade date: 2024-01-10
    assert start_date <= date(2024, 1, 15), (
        f"On first run, fetch should start from first trade date, got {start_date}"
    )
```

- [ ] **Step 2: Run to confirm the tests fail**

```
pytest tests/test_import_transactions.py -v
```

Expected: `AssertionError` — start_date is currently the all-time first trade date even when history exists.

- [ ] **Step 3: Apply incremental start_date fix in `write_historical()`**

In `tools/import_transactions.py`, find this block inside `write_historical()` (around line 249):

```python
    start_date = buys_sells["date"].min().date()
    end_date   = pd.Timestamp.today().date()
```

Replace with:

```python
    if existing_dates:
        max_existing = pd.Timestamp(max(existing_dates)).date()
        start_date = (pd.Timestamp(max_existing) - pd.Timedelta(days=5)).date()
    else:
        start_date = buys_sells["date"].min().date()
    end_date = pd.Timestamp.today().date()
```

- [ ] **Step 4: Run the new tests — confirm they pass**

```
pytest tests/test_import_transactions.py -v
```

Expected: both PASS.

- [ ] **Step 5: Run full test suite**

```
pytest tests/ -v
```

Expected: all pass (or same pre-existing failures as before).

- [ ] **Step 6: Commit**

```bash
git add tools/import_transactions.py tests/test_import_transactions.py
git commit -m "perf: incremental Yahoo Finance fetch in write_historical — skip already-populated dates"
```
