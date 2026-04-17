import pandas as pd
import pytest
from tools.portfolio_calculator import calculate_holdings, calculate_dividends


def make_txns(rows):
    return pd.DataFrame(rows, columns=["date", "ticker", "action", "shares", "price", "amount", "description"])


def test_single_buy():
    txns = make_txns([
        ("2023-10-19", "TSLA", "BUY", 15.0, 219.04, -3285.59, "TESLA INC COM"),
    ])
    holdings = calculate_holdings(txns)
    assert len(holdings) == 1
    row = holdings[holdings["ticker"] == "TSLA"].iloc[0]
    assert row["shares_held"] == 15.0
    assert abs(row["avg_cost_basis"] - 219.04) < 0.01
    assert abs(row["total_cost_basis"] - 3285.59) < 0.01


def test_buy_then_partial_sell():
    txns = make_txns([
        ("2023-10-19", "TSLA", "BUY", 15.0, 219.04, -3285.59, "TESLA"),
        ("2023-11-01", "TSLA", "SELL", -5.0, 240.00, 1200.00, "TESLA"),
    ])
    holdings = calculate_holdings(txns)
    row = holdings[holdings["ticker"] == "TSLA"].iloc[0]
    assert row["shares_held"] == 10.0
    # avg cost basis unchanged by sell
    assert abs(row["avg_cost_basis"] - 219.04) < 0.01


def test_full_sell_removes_position():
    txns = make_txns([
        ("2023-10-19", "GME", "BUY", 100.0, 15.53, -1553.0, "GME"),
        ("2023-11-30", "GME", "SELL", -100.0, 14.91, 1491.0, "GME"),
    ])
    holdings = calculate_holdings(txns)
    assert "GME" not in holdings["ticker"].values


def test_weighted_avg_cost_basis():
    txns = make_txns([
        ("2023-01-01", "AAPL", "BUY", 10.0, 100.0, -1000.0, "AAPL"),
        ("2023-06-01", "AAPL", "BUY", 10.0, 200.0, -2000.0, "AAPL"),
    ])
    holdings = calculate_holdings(txns)
    row = holdings[holdings["ticker"] == "AAPL"].iloc[0]
    # weighted avg: (10*100 + 10*200) / 20 = 150
    assert abs(row["avg_cost_basis"] - 150.0) < 0.01
    assert row["shares_held"] == 20.0
    assert abs(row["total_cost_basis"] - 3000.0) < 0.01


def test_cash_equivalents_excluded():
    txns = make_txns([
        ("2023-01-01", "TSLA", "BUY", 10.0, 200.0, -2000.0, "TESLA"),
        ("2023-01-02", "SPAXX", "DIVIDEND", 0.0, None, 5.0, "FIDELITY GOVT"),
    ])
    holdings = calculate_holdings(txns)
    assert "SPAXX" not in holdings["ticker"].values
    assert "TSLA" in holdings["ticker"].values


def test_calculate_dividends():
    txns = make_txns([
        ("2024-12-27", "META", "DIVIDEND", 0.0, None, 17.38, "META PLATFORMS"),
        ("2023-10-19", "TSLA", "BUY", 15.0, 219.04, -3285.59, "TESLA"),
    ])
    dividends = calculate_dividends(txns)
    assert len(dividends) == 1
    row = dividends.iloc[0]
    assert row["ticker"] == "META"
    assert row["amount"] == 17.38
    assert row["type"] == "DIVIDEND"
