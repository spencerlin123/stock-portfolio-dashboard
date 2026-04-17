import re
import pandas as pd
from io import StringIO


_ACTION_PATTERNS = {
    "BUY": r"YOU BOUGHT",
    "SELL": r"YOU SOLD",
    "DIVIDEND": r"DIVIDEND RECEIVED|LONG-TERM CAP GAIN|SHORT-TERM CAP GAIN",
    "REINVESTMENT": r"REINVESTMENT",
    "BUY": r"YOU BOUGHT|ROLLOVER SHARES",  # ROLLOVER SHARES = new positions entering IRA
}

# Rebuild cleanly (dict literals deduplicate keys — use ordered list instead)
_ACTION_PATTERNS = [
    ("BUY",         r"YOU BOUGHT|ROLLOVER SHARES"),
    ("SELL",        r"YOU SOLD"),
    ("DIVIDEND",    r"DIVIDEND RECEIVED|LONG-TERM CAP GAIN|SHORT-TERM CAP GAIN"),
    ("REINVESTMENT",r"REINVESTMENT"),
    ("DEPOSIT",     r"ELECTRONIC FUNDS TRANSFER RECEIVED|CASH CONTRIBUTION"),
]

# 401k fund name → ticker symbol
_FUND_NAME_TO_TICKER = {
    "FID 500 INDEX":       "FXAIX",
    "FID MID CAP IDX":     "FSMDX",
    "PUTN LG CP VAL TR IA":"PUTN_LCV",  # no yfinance; cost-basis tracking only
}

# 401k transaction types → normalized action (None = skip)
_401K_ACTION_MAP = {
    "Contributions":        "BUY",
    "Dividend":             "DIVIDEND",
    "Withdrawals":          "SELL",       # rollover out — tagged as transfer in description
    "RECORDKEEPING FEE":    "SELL",       # fee deducts shares from account
    "TERMINATED MAINTENANCE": "SELL",    # final fee at account close, also removes shares
    # all others → skip
}
_401K_SKIP = {
    "Realized Gain/Loss", "REVENUE CREDIT", "Adjustments",
}


def detect_csv_format(filepath: str) -> str:
    """Return 'brokerage' if standard Fidelity format, '401k' if retirement plan format."""
    with open(filepath, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if "Run Date" in line:
                return "brokerage"
            if "Transaction Type" in line:
                return "401k"
    return "brokerage"  # default


def extract_action_type(action_str: str) -> str | None:
    """Return normalized action type from verbose Fidelity action string, or None to skip."""
    for action_type, pattern in _ACTION_PATTERNS:
        if re.search(pattern, action_str, re.IGNORECASE):
            return action_type
    return None


def _safe_float(row: pd.Series, col: str, default: float | None = None) -> float | None:
    """Convert a Series cell to float, treating blank and 'nan' strings as missing."""
    val = str(row.get(col, "")).strip()
    if val.lower() in ("", "nan"):
        return default
    return float(val)


def parse_fidelity_csv(filepath: str) -> pd.DataFrame:
    """
    Parse a Fidelity brokerage transaction history CSV.

    Handles:
    - UTF-8 BOM at start of file
    - Blank lines before the header row
    - Verbose Action column (extracts action type)
    - ROLLOVER SHARES → BUY (new positions entering IRA from rollover)
    - Filters out transfers, foreign tax, cash contributions (no ticker), and unknown action types

    Returns a DataFrame with columns:
        date, ticker, action, shares, price, amount, description
    """
    with open(filepath, encoding="utf-8-sig") as f:
        lines = f.readlines()

    lines = [line for line in lines if line.strip()]
    content = "".join(lines)
    raw = pd.read_csv(StringIO(content), dtype=str)
    raw.columns = [c.strip() for c in raw.columns]

    if "Run Date" not in raw.columns:
        raise ValueError(
            f"Expected column 'Run Date' not found. Columns found: {list(raw.columns)}"
        )

    records = []
    skipped_no_ticker = 0

    for _, row in raw.iterrows():
        action_raw = str(row.get("Action", "")).strip()
        action_type = extract_action_type(action_raw)
        if action_type is None:
            continue

        ticker = str(row.get("Symbol", "")).strip()
        if not ticker or ticker.lower() == "nan":
            if action_type == "DEPOSIT":
                ticker = "CASH"
            else:
                skipped_no_ticker += 1
                continue

        # For ROLLOVER SHARES, Quantity may be in "Quantity" col with no price
        quantity = _safe_float(row, "Quantity", default=0.0)
        price    = _safe_float(row, "Price ($)", default=None)
        amount   = _safe_float(row, "Amount ($)", default=0.0)

        # Derive price from amount/quantity when price is missing (e.g. ROLLOVER SHARES)
        if price is None and quantity and quantity != 0:
            price = abs(float(amount)) / abs(float(quantity))

        records.append({
            "date":        pd.to_datetime(row["Run Date"]).date(),
            "ticker":      ticker,
            "action":      action_type,
            "shares":      quantity,
            "price":       price,
            "amount":      amount,
            "description": str(row.get("Description", "")).strip(),
        })

    if skipped_no_ticker:
        print(f"Warning: {skipped_no_ticker} row(s) skipped due to missing ticker symbol.")

    if not records:
        return pd.DataFrame(columns=["date", "ticker", "action", "shares", "price", "amount", "description"])

    return pd.DataFrame(records)


def parse_401k_csv(filepath: str) -> pd.DataFrame:
    """
    Parse a Fidelity 401k/retirement plan transaction history CSV.

    Format: Date, Investment, Transaction Type, Shares/Unit, Amount ($)
    Fund names are mapped to ticker symbols via _FUND_NAME_TO_TICKER.
    PUTN_LCV (Putnam fund) is recorded with amount only (no yfinance price tracking).

    Rollover Withdrawals are tagged with 'ROLLOVER_OUT' in description so the
    combined portfolio view can exclude them from external cash flow calculations.

    Returns same schema as parse_fidelity_csv:
        date, ticker, action, shares, price, amount, description
    """
    with open(filepath, encoding="utf-8-sig") as f:
        lines = f.readlines()

    lines = [line for line in lines if line.strip()]
    content = "".join(lines)
    raw = pd.read_csv(StringIO(content), dtype=str)
    raw.columns = [c.strip() for c in raw.columns]

    if "Transaction Type" not in raw.columns:
        raise ValueError(
            f"Expected column 'Transaction Type' not found. Columns: {list(raw.columns)}"
        )

    records = []
    for _, row in raw.iterrows():
        txn_type = str(row.get("Transaction Type", "")).strip()

        if txn_type in _401K_SKIP:
            continue

        action = _401K_ACTION_MAP.get(txn_type)
        if action is None:
            continue

        fund_name = str(row.get("Investment", "")).strip()
        ticker = _FUND_NAME_TO_TICKER.get(fund_name)
        if ticker is None:
            continue  # unknown fund — skip

        shares_raw = str(row.get("Shares/Unit", "")).strip()
        amount_raw = str(row.get("Amount ($)", "")).strip()

        try:
            shares = float(shares_raw) if shares_raw and shares_raw.lower() != "nan" else 0.0
        except ValueError:
            shares = 0.0

        try:
            amount = float(amount_raw) if amount_raw and amount_raw.lower() != "nan" else 0.0
        except ValueError:
            amount = 0.0

        # Derive price per share; for PUTN_LCV with no shares, price stays 0
        price = 0.0
        if shares and shares != 0:
            price = abs(amount) / abs(shares)

        # Normalize signs: BUY → positive shares, SELL → negative shares (like brokerage CSV)
        if action == "SELL":
            shares = -abs(shares)   # Fidelity 401k stores withdrawals as negative already, ensure

        description = fund_name
        if txn_type == "Withdrawals":
            description = f"ROLLOVER_OUT {fund_name}"

        try:
            date = pd.to_datetime(row["Date"]).date()
        except Exception:
            continue

        records.append({
            "date":        date,
            "ticker":      ticker,
            "action":      action,
            "shares":      shares,
            "price":       price,
            "amount":      amount,
            "description": description,
        })

    if not records:
        return pd.DataFrame(columns=["date", "ticker", "action", "shares", "price", "amount", "description"])

    return pd.DataFrame(records)
