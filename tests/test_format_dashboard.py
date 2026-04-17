def test_import():
    from tools.format_dashboard import apply_formatting, compute_period_returns
    assert callable(apply_formatting)
    assert callable(compute_period_returns)


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
    assert list(result.columns) == ["period", "twr_pct", "mwr_pct", "spy_pct", "qqq_pct"]


def test_period_returns_rows():
    p, s, q = _make_frames()
    result = compute_period_returns(p, s, q)
    assert list(result["period"]) == ["MTD", "1M", "3M", "6M", "YTD", "1Y", "2Y", "3Y", "All"]


def test_period_returns_all_positive_for_rising_series():
    p, s, q = _make_frames()
    result = compute_period_returns(p, s, q)
    for col in ["twr_pct", "spy_pct", "qqq_pct"]:
        assert result.loc[result["period"] == "All", col].iloc[0] > 0, f"{col} All return should be positive"


def test_period_returns_all_negative_for_falling_series():
    n = 300
    dates = pd.date_range("2024-01-02", periods=n, freq="B")
    p = pd.DataFrame({"date": dates, "total_value": [10000 - i * 5 for i in range(n)]})
    s = pd.DataFrame({"date": dates, "close": [400.0 - i * 0.3 for i in range(n)]})
    q = pd.DataFrame({"date": dates, "close": [300.0 - i * 0.2 for i in range(n)]})
    result = compute_period_returns(p, s, q)
    assert result.loc[result["period"] == "All", "twr_pct"].iloc[0] < 0


def test_period_returns_empty_returns_zeros():
    p = pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "total_value": pd.Series(dtype=float)})
    s = pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "close": pd.Series(dtype=float)})
    q = pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "close": pd.Series(dtype=float)})
    result = compute_period_returns(p, s, q)
    assert (result[["twr_pct", "spy_pct", "qqq_pct"]] == 0).all().all()


def test_period_returns_twr_strips_new_capital():
    """
    Portfolio value grows but part of that growth comes from a cash deposit.
    TWR should strip out the deposit and report a lower return than naive.
    """
    dates = pd.date_range("2024-01-02", periods=500, freq="B")
    p = pd.DataFrame({"date": dates, "total_value": [10000 + i * 20 for i in range(500)]})
    s = pd.DataFrame({"date": dates, "close": [400.0 + i * 0.1 for i in range(500)]})
    q = pd.DataFrame({"date": dates, "close": [300.0 + i * 0.1 for i in range(500)]})

    # Inject 5000 as a DEPOSIT partway through the All period
    txns = pd.DataFrame([{
        "date": dates[100],
        "action": "DEPOSIT",
        "amount": 5000.0,
        "ticker": "CASH",
    }])

    result_no_txn = compute_period_returns(p, s, q, transactions_df=None)
    result_with_txn = compute_period_returns(p, s, q, transactions_df=txns)

    all_no_txn = result_no_txn.loc[result_no_txn["period"] == "All", "twr_pct"].iloc[0]
    all_with_txn = result_with_txn.loc[result_with_txn["period"] == "All", "twr_pct"].iloc[0]

    # TWR with deposit stripped should be lower than naive return that includes the deposit
    assert all_with_txn < all_no_txn, "TWR should be lower than naive return when a deposit was injected"


def test_twr_deposit_then_buy_no_double_count():
    """
    Deposit and same-day BUY should not double-count the external CF.
    Portfolio value on deposit day = prev_value + deposit (no market gain).
    TWR sub-period return for that day must be exactly 1.0 (0% return).
    """
    from tools.format_dashboard import _build_daily_cf
    import pandas as pd

    dates = pd.date_range("2024-01-02", periods=3, freq="B")
    # Day 0: 100k, Day 1: 109k (deposit 9k, no market gain), Day 2: 109.5k (small gain)
    portfolio = pd.DataFrame({"date": dates, "total_value": [100000.0, 109000.0, 109500.0]})
    spy = pd.DataFrame({"date": dates, "close": [400.0, 400.0, 401.0]})
    qqq = pd.DataFrame({"date": dates, "close": [300.0, 300.0, 301.0]})

    txns = pd.DataFrame([
        {"date": dates[1], "action": "DEPOSIT", "amount": 9000.0, "ticker": "CASH"},
        {"date": dates[1], "action": "BUY",     "amount": -9000.0, "ticker": "AAPL"},
    ])

    # ext_cf on deposit day should be exactly the deposit amount (9000), not 18000
    # Deposit funds the BUY — the BUY is covered by available, so max(0, buys-available)=0
    daily_cf = _build_daily_cf(txns)
    deposit_day = pd.Timestamp(dates[1]).normalize()
    assert daily_cf.get(deposit_day, 0.0) == pytest.approx(9000.0, abs=1.0), \
        "ext_cf should be 9000 (deposit only) — BUY funded by deposit produces zero additional ext_cf"


import pytest


from unittest.mock import MagicMock, patch


def test_write_hidden_tabs_skips_gracefully_when_historical_empty():
    """write_hidden_tabs should return without error if Historical tab is empty."""
    from tools.format_dashboard import write_hidden_tabs

    mock_ws = MagicMock()
    mock_sheet = MagicMock()
    mock_sheet.worksheet.return_value = mock_ws

    with patch("tools.sheets_client.read_tab_as_df", return_value=pd.DataFrame()):
        # Should not raise
        write_hidden_tabs(mock_sheet)


def test_format_holdings_calls_batch_update():
    """format_holdings should call batch_update to apply formatting."""
    from tools.format_dashboard import format_holdings

    mock_ws = MagicMock()
    mock_ws.id = 42  # Use .id directly (not ._properties)
    mock_sheet = MagicMock()
    mock_sheet.fetch_sheet_metadata.return_value = {
        "sheets": [{"properties": {"sheetId": 42}, "bandedRanges": [], "conditionalFormats": []}]
    }

    format_holdings(mock_sheet, mock_ws)

    assert mock_sheet.batch_update.called


def test_format_transactions_calls_batch_update():
    """format_transactions should call batch_update to apply formatting."""
    from tools.format_dashboard import format_transactions

    mock_ws = MagicMock()
    mock_ws.id = 10
    mock_sheet = MagicMock()
    mock_sheet.fetch_sheet_metadata.return_value = {
        "sheets": [{"properties": {"sheetId": 10}, "bandedRanges": [], "conditionalFormats": []}]
    }

    format_transactions(mock_sheet, mock_ws)

    assert mock_sheet.batch_update.called


def test_format_dividends_calls_batch_update():
    """format_dividends should call batch_update to apply formatting."""
    from tools.format_dashboard import format_dividends

    mock_ws = MagicMock()
    mock_ws.id = 20
    mock_sheet = MagicMock()
    mock_sheet.fetch_sheet_metadata.return_value = {
        "sheets": [{"properties": {"sheetId": 20}, "bandedRanges": [], "conditionalFormats": []}]
    }

    format_dividends(mock_sheet, mock_ws)

    assert mock_sheet.batch_update.called


def test_format_historical_calls_batch_update():
    """format_historical should call batch_update to apply formatting."""
    from tools.format_dashboard import format_historical

    mock_ws = MagicMock()
    mock_ws.id = 30
    mock_sheet = MagicMock()

    format_historical(mock_sheet, mock_ws)

    assert mock_sheet.batch_update.called


def test_write_dashboard_sections_calls_batch_update():
    from tools.format_dashboard import write_dashboard_sections

    mock_ws = MagicMock()
    mock_ws.id = 0
    mock_sheet = MagicMock()
    mock_sheet.fetch_sheet_metadata.return_value = {
        "sheets": [{"properties": {"sheetId": 0}, "bandedRanges": [], "conditionalFormats": []}]
    }
    # _Benchmarks tab not found — should fall back to zero returns
    mock_sheet.worksheet.side_effect = Exception("not found")

    write_dashboard_sections(mock_sheet, mock_ws)

    assert mock_ws.clear.called or mock_ws.update.called or mock_sheet.batch_update.called


def test_add_portfolio_chart_skips_when_no_history_tab():
    from tools.format_dashboard import add_portfolio_chart

    mock_ws = MagicMock()
    mock_ws.id = 0
    mock_sheet = MagicMock()
    mock_sheet.fetch_sheet_metadata.return_value = {"sheets": []}
    # _PortfolioHistory not found
    mock_sheet.worksheet.side_effect = Exception("not found")

    # Should not raise
    add_portfolio_chart(mock_sheet, mock_ws)


def test_import_transactions_calls_apply_formatting():
    """apply_formatting should be wired into import_transactions.main context."""
    import importlib.util
    src = importlib.util.find_spec("tools.import_transactions").origin
    with open(src) as f:
        source = f.read()
    assert "apply_formatting" in source, "import_transactions.py must call apply_formatting"
    assert "write_dashboard" not in source, "write_dashboard should be removed from import_transactions.py"
