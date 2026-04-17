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

    mock_fetch.return_value = pd.DataFrame()

    mock_ws = MagicMock()
    existing_df = _make_existing_historical_df("2026-04-10")

    with patch("tools.import_transactions.read_tab_as_df", return_value=existing_df):
        write_historical(mock_ws, _make_transactions())

    assert mock_fetch.called, "_fetch_all_closes should have been called"
    call_args = mock_fetch.call_args[0]
    # start_date is the 2nd positional arg (index 1)
    start_date = call_args[1]
    # Should be 2026-04-05 (2026-04-10 minus 5 days) — NOT 2024-01-10 (all-time)
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
    call_args = mock_fetch.call_args[0]
    start_date = call_args[1]
    # Should fetch from first trade date: 2024-01-10
    assert start_date <= date(2024, 1, 15), (
        f"On first run, fetch should start from first trade date, got {start_date}"
    )
