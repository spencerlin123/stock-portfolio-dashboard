#!/usr/bin/env python3
"""
Import Fidelity transaction CSVs from .tmp/ and .tmp/ira/ into Google Sheets.

Usage:
    python tools/import_transactions.py

Reads all .csv files from .tmp/ (Individual Brokerage) and .tmp/ira/ (Roth IRA/401k),
deduplicates against existing Sheets tabs, and updates Holdings, Historical, and Dividends.
"""
import os
import sys
import glob
import bisect
import time
import datetime
import requests
import pandas as pd
from dotenv import load_dotenv

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from tools.fidelity_parser import parse_fidelity_csv, parse_401k_csv, detect_csv_format
from tools.portfolio_calculator import calculate_holdings, calculate_dividends
from tools.sheets_client import get_sheet, get_or_create_tab, read_tab_as_df, overwrite_tab

_TMP_DIR     = os.path.join(_PROJECT_ROOT, ".tmp")
_TMP_IRA_DIR = os.path.join(_PROJECT_ROOT, ".tmp", "ira")

_TRANSACTION_HEADERS = ["date", "ticker", "action", "shares", "price", "amount", "description"]
_HOLDINGS_HEADERS    = ["ticker", "shares_held", "avg_cost_basis", "total_cost_basis",
                        "current_price", "current_value", "unrealized_pnl", "unrealized_pnl_pct", "day_change_pct"]
_DIVIDENDS_HEADERS   = ["date", "ticker", "amount", "type"]
_HISTORICAL_HEADERS  = ["date", "ticker", "shares_held", "close_price", "position_value"]
_CASH_EQUIVALENTS    = {"SPAXX", "FZFXX", "FDIC", "FCASH"}
# Tickers that have no Yahoo Finance price data — tracked at cost basis only
_NO_PRICE_TICKERS    = {"PUTN_LCV"}

import re as _re
_CUSIP_RE = _re.compile(r'^[A-Z0-9]{8}[0-9]$')

def _is_cusip(ticker: str) -> bool:
    """Return True if ticker looks like a CUSIP (9-char alphanumeric) — not a real exchange symbol."""
    return bool(_CUSIP_RE.match(ticker))


# ── Shared helpers ────────────────────────────────────────────────────────────

def deduplicate_against_sheet(new_df: pd.DataFrame, existing_df: pd.DataFrame) -> pd.DataFrame:
    """Return only rows in new_df not already present in existing_df."""
    if existing_df.empty:
        return new_df
    key_cols = ["date", "ticker", "action", "shares", "amount"]
    existing_df = existing_df.copy()
    new_df = new_df.copy()
    existing_df["date"] = pd.to_datetime(existing_df["date"], errors="coerce")
    new_df["date"]      = pd.to_datetime(new_df["date"], errors="coerce")
    for col in ["shares", "amount"]:
        existing_df[col] = pd.to_numeric(existing_df[col], errors="coerce")
        new_df[col]      = pd.to_numeric(new_df[col], errors="coerce")
    merged   = new_df.merge(existing_df[key_cols].drop_duplicates(), on=key_cols, how="left", indicator=True)
    new_only = merged[merged["_merge"] == "left_only"].drop(columns=["_merge"])
    return new_only.reset_index(drop=True)


def _txn_rows(df: pd.DataFrame) -> list:
    rows = []
    for _, r in df.iterrows():
        rows.append([
            str(r["date"])[:10],
            r["ticker"],
            r["action"],
            r["shares"],
            r["price"] if pd.notna(r.get("price")) else "",
            r["amount"],
            r["description"],
        ])
    return rows


def write_transactions(ws, all_transactions: pd.DataFrame):
    """Append new transactions to a Transactions tab."""
    existing = read_tab_as_df(ws)
    new_rows = deduplicate_against_sheet(all_transactions, existing)
    if new_rows.empty:
        print("  No new transactions to add.")
        return
    print(f"  Writing {len(new_rows)} new transaction rows...")
    ws.append_rows(_txn_rows(new_rows), value_input_option="USER_ENTERED")
    print("  Transactions tab updated.")


def write_holdings(ws, all_transactions: pd.DataFrame, cash_env_var: str | None = None):
    """Recompute and overwrite Holdings tab from full transaction history.
    Cash balance is read from cash_env_var (manually verified against Fidelity).
    Transaction-derived cash is intentionally not used here — fees, sweeps, and
    withheld tax make the computed balance unreliable for display.
    """
    holdings = calculate_holdings(all_transactions)
    print(f"  Writing {len(holdings)} holdings...")
    rows = []
    for _, r in holdings.iterrows():
        ticker     = r["ticker"]
        shares     = r["shares_held"]
        avg_cost   = r["avg_cost_basis"]
        total_cost = r["total_cost_basis"]
        row_num    = len(rows) + 2
        if ticker in _NO_PRICE_TICKERS:
            # No live price — show cost basis as current value
            rows.append([ticker, shares, avg_cost, total_cost,
                         avg_cost, total_cost, 0, 0, 0])
        else:
            rows.append([
                ticker, shares, avg_cost, total_cost,
                f'=GOOGLEFINANCE("{ticker}","price")',
                f"={shares}*E{row_num}",
                f"=F{row_num}-{total_cost}",
                f"=G{row_num}/{total_cost}",
                f'=GOOGLEFINANCE("{ticker}","changepct")',
            ])

    # Use env var as the source of truth for uninvested cash (manually verified from Fidelity)
    cash_val = float(os.environ.get(cash_env_var, 0) or 0) if cash_env_var else 0.0
    if cash_val > 0.01:
        # CASH: face value = cost basis, so P&L = 0 (deposited funds, not an investment)
        rows.append(["CASH", cash_val, 1.0, cash_val, 1.0, cash_val, 0.0, 0.0, 0.0])

    overwrite_tab(ws, _HOLDINGS_HEADERS, rows)
    print("  Holdings tab updated.")


def write_dividends(ws, all_transactions: pd.DataFrame):
    """Recompute and overwrite Dividends tab."""
    divs = calculate_dividends(all_transactions)
    print(f"  Writing {len(divs)} dividend rows...")
    rows = [[str(r["date"])[:10], r["ticker"], r["amount"], r["type"]] for _, r in divs.iterrows()]
    overwrite_tab(ws, _DIVIDENDS_HEADERS, rows)
    print("  Dividends tab updated.")


def _build_cash_balance(all_transactions: pd.DataFrame) -> tuple[dict, list]:
    """
    Compute running idle-cash balance per transaction date.
    Returns (cash_by_date_str, sorted_dates).
    """
    txns = all_transactions.copy()
    txns["amount"] = pd.to_numeric(txns["amount"], errors="coerce").fillna(0.0)
    txns = txns.sort_values("date").reset_index(drop=True)
    running = 0.0
    cash_by_date: dict[str, float] = {}
    for _, row in txns.iterrows():
        action = row.get("action", "")
        amount = float(row.get("amount", 0.0))
        if action in ("SELL", "DIVIDEND", "DEPOSIT"):
            running += abs(amount)
        elif action in ("BUY", "REINVESTMENT"):
            running = max(0.0, running - abs(amount))
        cash_by_date[str(row["date"])[:10]] = running
    return cash_by_date, sorted(cash_by_date.keys())


def _cash_on(date_str: str, cash_by_date: dict, sorted_dates: list) -> float:
    idx = bisect.bisect_right(sorted_dates, date_str) - 1
    return cash_by_date[sorted_dates[idx]] if idx >= 0 else 0.0


_YF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _fetch_ticker_closes(ticker: str, start_date, end_date) -> pd.Series:
    """
    Fetch adjusted daily closes for `ticker` from Yahoo Finance v8 API.
    Retries once after 2s on transient connection errors.
    Returns a pd.Series indexed by pd.Timestamp, or empty Series on failure.
    """
    start_ts = int(datetime.datetime.combine(start_date, datetime.time()).timestamp())
    end_ts   = int(datetime.datetime.combine(end_date, datetime.time()).timestamp()) + 86400
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?interval=1d&period1={start_ts}&period2={end_ts}"
    )
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=_YF_HEADERS, timeout=10)
            resp.raise_for_status()
            result = resp.json()["chart"]["result"]
            if not result:
                return pd.Series(dtype=float, name=ticker)
            result = result[0]
            timestamps = result["timestamp"]
            adjclose_list = result["indicators"].get("adjclose")
            if adjclose_list:
                closes = adjclose_list[0]["adjclose"]
            else:
                closes = result["indicators"]["quote"][0]["close"]
            dates = [pd.Timestamp(datetime.datetime.utcfromtimestamp(ts).date()) for ts in timestamps]
            s = pd.Series(closes, index=dates, name=ticker, dtype=float)
            return s.dropna()
        except Exception as exc:
            if attempt == 0:
                print(f"  Warning: price fetch for {ticker} failed ({exc}), retrying...")
                time.sleep(2)
            else:
                print(f"  Warning: price fetch for {ticker} failed after retry ({exc})")
    return pd.Series(dtype=float, name=ticker)


def _fetch_all_closes(tickers: list, start_date, end_date) -> pd.DataFrame:
    """
    Fetch close prices for all `tickers` via Yahoo Finance, returning a DataFrame
    with ticker columns and DatetimeIndex — same shape as yf.download()[\"Close\"].
    """
    frames = {}
    for i, ticker in enumerate(tickers):
        s = _fetch_ticker_closes(ticker, start_date, end_date)
        if not s.empty:
            frames[ticker] = s
        if i < len(tickers) - 1:
            time.sleep(0.3)   # light rate-limit courtesy
    if not frames:
        return pd.DataFrame()
    return pd.DataFrame(frames).sort_index()


def write_historical(ws, all_transactions: pd.DataFrame,
                     no_price_tickers: set | None = None):
    """
    Build portfolio value over time using Yahoo Finance historical close prices.
    Tickers in no_price_tickers are tracked at cost basis only (no market price).
    Skips dates already present in the Historical tab.
    """

    if no_price_tickers is None:
        no_price_tickers = _NO_PRICE_TICKERS

    buys_sells = all_transactions[all_transactions["action"].isin(["BUY", "SELL"])].copy()
    if buys_sells.empty:
        print("  No buy/sell transactions — skipping Historical tab.")
        return

    existing = read_tab_as_df(ws)
    if "date" not in existing.columns:
        ws.clear()
        ws.append_row(_HISTORICAL_HEADERS)
        existing_dates = set()
    else:
        existing_dates = set(existing["date"].astype(str).tolist())

    if existing_dates:
        max_existing = pd.Timestamp(max(existing_dates)).date()
        start_date = (pd.Timestamp(max_existing) - pd.Timedelta(days=5)).date()
    else:
        start_date = buys_sells["date"].min().date()
    end_date = pd.Timestamp.today().date()
    all_dates  = pd.date_range(start=start_date, end=end_date, freq="B")

    all_tickers      = [t for t in buys_sells["ticker"].unique() if t not in _CASH_EQUIVALENTS]
    price_tickers    = [t for t in all_tickers if t not in no_price_tickers and not _is_cusip(t)]
    no_price_set     = {t for t in all_tickers if t in no_price_tickers or _is_cusip(t)}

    close_prices = pd.DataFrame()
    if price_tickers:
        print(f"  Fetching historical prices for {len(price_tickers)} tickers via yfinance...")
        close_prices = _fetch_all_closes(price_tickers, start_date, end_date)

    cash_by_date, sorted_dates = _build_cash_balance(all_transactions)

    rows = []
    for date in all_dates:
        date_str    = str(date.date())
        if date_str in existing_dates:
            continue
        txns_to_date = buys_sells[buys_sells["date"] <= date]

        for ticker in all_tickers:
            ticker_txns = txns_to_date[txns_to_date["ticker"] == ticker]
            if ticker_txns.empty:
                continue
            buys   = ticker_txns[ticker_txns["action"] == "BUY"]["shares"].sum()
            sells  = abs(ticker_txns[ticker_txns["action"] == "SELL"]["shares"].sum())
            shares = round(buys - sells, 6)
            if shares <= 0:
                continue

            if ticker in no_price_set:
                # Use WAVG cost basis as position value (no market price)
                cost_buys  = ticker_txns[ticker_txns["action"] == "BUY"]
                total_cost = (cost_buys["shares"] * cost_buys["price"].fillna(0)).sum()
                total_shares_bought = cost_buys["shares"].sum()
                avg_cost = total_cost / total_shares_bought if total_shares_bought > 0 else 0.0
                pos_val  = round(shares * avg_cost, 2)
                rows.append([date_str, ticker, shares, round(avg_cost, 4), pos_val])
            else:
                if ticker not in close_prices.columns:
                    continue
                try:
                    close = close_prices[ticker].asof(date)
                    if pd.isna(close):
                        continue
                except Exception:
                    continue
                rows.append([date_str, ticker, shares,
                             round(float(close), 4),
                             round(shares * float(close), 2)])

        cash_val = _cash_on(date_str, cash_by_date, sorted_dates)
        if cash_val > 0.01:
            rows.append([date_str, "CASH", 1, round(cash_val, 2), round(cash_val, 2)])

    if rows:
        print(f"  Writing {len(rows)} historical rows...")
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    else:
        print("  Historical tab already up to date.")
    print("  Historical tab updated.")


# ── Brokerage pipeline ────────────────────────────────────────────────────────

def load_all_csvs() -> pd.DataFrame:
    """Parse all CSV files in .tmp/ (brokerage format) and return combined DataFrame."""
    pattern = os.path.join(_TMP_DIR, "*.csv")
    files   = glob.glob(pattern)
    if not files:
        raise FileNotFoundError(f"No CSV files found in {_TMP_DIR}/")
    print(f"Found {len(files)} brokerage CSV file(s)")
    frames  = [parse_fidelity_csv(f) for f in files]
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates()
    combined = combined.sort_values("date").reset_index(drop=True)
    print(f"  {len(combined)} transactions parsed (after dedup within CSVs)")
    return combined


# ── IRA pipeline ──────────────────────────────────────────────────────────────

def load_ira_csvs() -> pd.DataFrame:
    """
    Parse all CSV files in .tmp/ira/ — auto-detects brokerage vs 401k format.
    Returns combined DataFrame with same schema as brokerage transactions.
    """
    pattern = os.path.join(_TMP_IRA_DIR, "*.csv")
    files   = glob.glob(pattern)
    if not files:
        print(f"  No IRA CSV files found in {_TMP_IRA_DIR}/ — skipping IRA pipeline.")
        return pd.DataFrame()

    print(f"Found {len(files)} IRA CSV file(s)")
    frames = []
    for f in files:
        fmt = detect_csv_format(f)
        if fmt == "401k":
            frames.append(parse_401k_csv(f))
        else:
            frames.append(parse_fidelity_csv(f))

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates()
    combined = combined.sort_values("date").reset_index(drop=True)
    print(f"  {len(combined)} IRA transactions parsed (after dedup within CSVs)")
    return combined


def run_ira_pipeline(sheet, all_ira_txns: pd.DataFrame):
    """Write IRA transactions to IRA_* Sheets tabs and recompute derived tabs."""
    if all_ira_txns.empty:
        return

    print("\n[IRA] Updating IRA_Transactions tab...")
    ira_txn_ws = get_or_create_tab(sheet, "IRA_Transactions", _TRANSACTION_HEADERS)
    write_transactions(ira_txn_ws, all_ira_txns)

    print("[IRA] Recomputing IRA_Holdings, IRA_Historical, IRA_Dividends...")
    all_ira_in_sheet = read_tab_as_df(ira_txn_ws)
    all_ira_in_sheet["date"] = pd.to_datetime(all_ira_in_sheet["date"], errors="coerce")
    for col in ["shares", "price", "amount"]:
        all_ira_in_sheet[col] = pd.to_numeric(all_ira_in_sheet[col], errors="coerce")

    ira_holdings_ws = get_or_create_tab(sheet, "IRA_Holdings", _HOLDINGS_HEADERS)
    write_holdings(ira_holdings_ws, all_ira_in_sheet, cash_env_var="IRA_CASH")

    ira_hist_ws = get_or_create_tab(sheet, "IRA_Historical", _HISTORICAL_HEADERS)
    write_historical(ira_hist_ws, all_ira_in_sheet, no_price_tickers=_NO_PRICE_TICKERS)

    ira_divs_ws = get_or_create_tab(sheet, "IRA_Dividends", _DIVIDENDS_HEADERS)
    write_dividends(ira_divs_ws, all_ira_in_sheet)

    print("[IRA] IRA tabs updated.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print("=== Stock Portfolio Dashboard Import ===")

    print("\n[1/6] Parsing brokerage CSV files...")
    all_txns = load_all_csvs()

    print("\n[2/6] Parsing IRA CSV files...")
    all_ira_txns = load_ira_csvs()

    print("\n[3/6] Connecting to Google Sheets...")
    sheet = get_sheet()

    print("\n[4/6] Updating Transactions tab (Individual Brokerage)...")
    txn_ws = get_or_create_tab(sheet, "Transactions", _TRANSACTION_HEADERS)
    write_transactions(txn_ws, all_txns)

    print("\n[5/6] Recomputing Holdings, Historical, and Dividends (Individual Brokerage)...")
    all_txns_in_sheet = read_tab_as_df(txn_ws)
    all_txns_in_sheet["date"] = pd.to_datetime(all_txns_in_sheet["date"], errors="coerce")
    for col in ["shares", "price", "amount"]:
        all_txns_in_sheet[col] = pd.to_numeric(all_txns_in_sheet[col], errors="coerce")

    holdings_ws = get_or_create_tab(sheet, "Holdings", _HOLDINGS_HEADERS)
    write_holdings(holdings_ws, all_txns_in_sheet, cash_env_var="BROKERAGE_CASH")

    hist_ws = get_or_create_tab(sheet, "Historical", _HISTORICAL_HEADERS)
    write_historical(hist_ws, all_txns_in_sheet)

    divs_ws = get_or_create_tab(sheet, "Dividends", _DIVIDENDS_HEADERS)
    write_dividends(divs_ws, all_txns_in_sheet)

    if not all_ira_txns.empty:
        run_ira_pipeline(sheet, all_ira_txns)

    print("\n[6/6] Applying Dark Pro formatting and analytics...")
    from tools.format_dashboard import apply_formatting
    apply_formatting(sheet)

    print("\nDone. All tabs updated.")
    print(f"  Sheet: https://docs.google.com/spreadsheets/d/{os.environ['GOOGLE_SHEET_ID']}")


if __name__ == "__main__":
    main()
