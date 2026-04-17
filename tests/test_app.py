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
    # Column names match what import_transactions.py writes (lowercase/snake_case)
    return pd.DataFrame([{
        "ticker": "AAPL",
        "shares_held": "10.0",
        "avg_cost_basis": "150.0",
        "total_cost_basis": "1500.0",
        "current_price": "175.0",
        "current_value": "1750.0",
        "unrealized_pnl": "250.0",
        "unrealized_pnl_pct": "0.1667",
        "day_change_pct": "0.012",
    }])


def _make_transactions_df():
    return pd.DataFrame([{
        "date": "2023-01-15",
        "ticker": "AAPL",
        "action": "BUY",
        "shares": "10.0",
        "price": "150.0",
        "amount": "-1500.0",
        "description": "Buy AAPL",
    }])


def _make_dividends_df():
    return pd.DataFrame([{
        "date": "2024-03-15",
        "ticker": "AAPL",
        "amount": "23.50",
        "type": "DIVIDEND",
    }])


def _make_history_df():
    return pd.DataFrame([{"date": "2023-07-01", "total_value": "45000.0"}])


_LIVE_HISTORY = [{"date": "2023-07-01", "total_value": 45000.0}]

def _mock_live_returns_full(benchmarks=None):
    return {
        "brokerage":       benchmarks or [],
        "ira":             [],
        "overall":         [],
        "brk_history":     _LIVE_HISTORY,
        "ira_history":     _LIVE_HISTORY,
        "overall_history": _LIVE_HISTORY,
    }


def _make_benchmarks_df():
    return pd.DataFrame([{
        "period": "1M",
        "portfolio_pct": "4.79",
        "spy_pct": "2.29",
        "qqq_pct": "2.44",
    }])


def _mock_ws(df):
    ws = MagicMock()
    ws.get_all_records.return_value = df.to_dict("records")
    return ws


@patch("app._compute_live_returns")
@patch("app.get_sheet")
def test_api_data_keys(mock_get_sheet, mock_live_returns, client):
    sheet = MagicMock()
    mock_get_sheet.return_value = sheet
    mock_live_returns.return_value = _mock_live_returns_full(
        benchmarks=[{"period": "MTD", "twr_pct": 1.0, "mwr_pct": 1.0, "spy_pct": 0.5, "qqq_pct": 0.3}]
    )

    def worksheet_side_effect(name):
        mapping = {
            "Holdings":     _mock_ws(_make_holdings_df()),
            "Transactions": _mock_ws(_make_transactions_df()),
            "Dividends":    _mock_ws(_make_dividends_df()),
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


@patch("app._compute_live_returns")
@patch("app.get_sheet")
def test_api_data_holdings_numeric(mock_get_sheet, mock_live_returns, client):
    sheet = MagicMock()
    mock_get_sheet.return_value = sheet
    mock_live_returns.return_value = _mock_live_returns_full()

    def worksheet_side_effect(name):
        mapping = {
            "Holdings":     _mock_ws(_make_holdings_df()),
            "Transactions": _mock_ws(_make_transactions_df()),
            "Dividends":    _mock_ws(_make_dividends_df()),
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
    mock_live_returns.return_value = _mock_live_returns_full()

    def worksheet_side_effect(name):
        mapping = {
            "Holdings":     _mock_ws(_make_holdings_df()),
            "Transactions": _mock_ws(_make_transactions_df()),
            "Dividends":    _mock_ws(_make_dividends_df()),
        }
        if name not in mapping:
            import gspread
            raise gspread.WorksheetNotFound(name)
        return mapping[name]

    sheet.worksheet.side_effect = worksheet_side_effect

    resp = client.get("/api/data")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    # portfolio_history now comes from _compute_live_returns (not _PortfolioHistory tab directly)
    assert data["portfolio_history"] == _LIVE_HISTORY
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


from zoneinfo import ZoneInfo as _ZoneInfo

_ET = _ZoneInfo("America/New_York")


def test_cache_ttl_during_market_hours():
    """Returns 300 (5 min) during weekday market hours."""
    from app import _cache_ttl
    from datetime import datetime
    market_time = datetime(2026, 4, 14, 10, 0, 0, tzinfo=_ET)  # Monday 10am ET
    with patch("app.datetime") as mock_dt:
        mock_dt.now.return_value = market_time
        assert _cache_ttl() == 900


def test_cache_ttl_outside_market_hours():
    """Returns 3600 (1 hr) outside market hours."""
    from app import _cache_ttl
    from datetime import datetime
    evening = datetime(2026, 4, 14, 20, 0, 0, tzinfo=_ET)  # Monday 8pm ET
    with patch("app.datetime") as mock_dt:
        mock_dt.now.return_value = evening
        assert _cache_ttl() == 3600


def test_cache_ttl_on_weekend():
    """Returns 3600 (1 hr) on weekends."""
    from app import _cache_ttl
    from datetime import datetime
    saturday = datetime(2026, 4, 12, 11, 0, 0, tzinfo=_ET)  # Saturday 11am ET
    with patch("app.datetime") as mock_dt:
        mock_dt.now.return_value = saturday
        assert _cache_ttl() == 3600
