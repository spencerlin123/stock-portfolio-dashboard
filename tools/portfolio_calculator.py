import pandas as pd

_CASH_EQUIVALENTS = {"SPAXX", "FZFXX", "FDIC", "FCASH"}


def calculate_holdings(transactions: pd.DataFrame) -> pd.DataFrame:
    """
    Derive current open positions from full transaction history.

    Uses weighted average cost basis. Excludes cash equivalents.
    Returns DataFrame with columns:
        ticker, shares_held, avg_cost_basis, total_cost_basis
    """
    buys_sells = transactions[
        transactions["action"].isin(["BUY", "SELL"]) &
        ~transactions["ticker"].isin(_CASH_EQUIVALENTS)
    ].copy()

    if buys_sells.empty:
        return pd.DataFrame(columns=["ticker", "shares_held", "avg_cost_basis", "total_cost_basis"])

    holdings = []
    for ticker, group in buys_sells.groupby("ticker"):
        buys = group[group["action"] == "BUY"]
        sells = group[group["action"] == "SELL"]

        shares_bought = buys["shares"].sum()
        shares_sold = abs(sells["shares"].sum())
        shares_held = round(shares_bought - shares_sold, 6)

        if shares_held <= 0:
            continue

        # Weighted average cost basis from buy transactions only
        total_cost = (buys["shares"] * buys["price"].fillna(0)).sum()
        avg_cost = total_cost / shares_bought if shares_bought > 0 else 0.0

        holdings.append({
            "ticker": ticker,
            "shares_held": shares_held,
            "avg_cost_basis": round(avg_cost, 4),
            "total_cost_basis": round(shares_held * avg_cost, 2),
        })

    return pd.DataFrame(holdings) if holdings else pd.DataFrame(
        columns=["ticker", "shares_held", "avg_cost_basis", "total_cost_basis"]
    )


def calculate_realized_gains(transactions: pd.DataFrame) -> float:
    """
    Compute total realized P&L from all completed sell transactions.

    Uses weighted average cost basis (WAVG): for each ticker, tracks the running
    average cost per share from buys and computes gain/loss on each sell as:
        realized_gain = shares_sold * (sell_price - avg_cost_at_time_of_sell)

    Returns the total realized gain (positive = profit, negative = loss).
    """
    buys_sells = transactions[
        transactions["action"].isin(["BUY", "SELL"]) &
        ~transactions["ticker"].isin(_CASH_EQUIVALENTS)
    ].copy()

    if buys_sells.empty:
        return 0.0

    buys_sells["date"] = pd.to_datetime(buys_sells["date"], errors="coerce")
    buys_sells["shares"] = pd.to_numeric(buys_sells["shares"], errors="coerce").fillna(0.0)
    buys_sells["price"] = pd.to_numeric(buys_sells["price"], errors="coerce").fillna(0.0)

    # Sort by date, then BUYs before SELLs within the same date so cost basis is
    # always established before the corresponding sell is processed
    buys_sells["_action_order"] = buys_sells["action"].map({"BUY": 0, "SELL": 1}).fillna(1)
    buys_sells = buys_sells.sort_values(["date", "_action_order"])

    total_realized = 0.0
    for ticker, group in buys_sells.groupby("ticker"):
        avg_cost = 0.0
        shares_held = 0.0
        for _, row in group.iterrows():
            if row["action"] == "BUY":
                new_shares = row["shares"]
                new_cost = row["price"]
                avg_cost = (avg_cost * shares_held + new_cost * new_shares) / (shares_held + new_shares) if (shares_held + new_shares) > 0 else new_cost
                shares_held += new_shares
            elif row["action"] == "SELL":
                shares_sold = abs(row["shares"])
                sell_price = row["price"]
                total_realized += shares_sold * (sell_price - avg_cost)
                shares_held = max(0.0, shares_held - shares_sold)

    return round(total_realized, 2)


def calculate_dividends(transactions: pd.DataFrame) -> pd.DataFrame:
    """
    Extract dividend rows from transactions.

    Returns DataFrame with columns:
        date, ticker, amount, type
    """
    divs = transactions[transactions["action"].isin(["DIVIDEND", "REINVESTMENT"])].copy()
    if divs.empty:
        return pd.DataFrame(columns=["date", "ticker", "amount", "type"])

    result = divs[["date", "ticker", "amount", "action"]].copy()
    result = result.rename(columns={"action": "type"})
    result["amount"] = result["amount"].abs()
    return result.reset_index(drop=True)
