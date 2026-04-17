"""
Apply Dark Pro formatting and analytics to all Google Sheets tabs.

Entry point:
    from tools.format_dashboard import apply_formatting
    apply_formatting(sheet)   # sheet is a gspread.Spreadsheet object
"""
import os
import sys
import time
import requests
import pandas as pd
from tools.sheets_client import read_tab_as_df

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


_YF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _fetch_closes(ticker: str, start_date: str) -> pd.DataFrame:
    """
    Fetch daily adjusted close prices for `ticker` from Yahoo Finance v8 API.
    Retries once after 2s on transient errors.
    Returns DataFrame with columns ['date', 'close'], sorted ascending.
    Falls back to empty DataFrame on any error.
    """
    import datetime as _dt
    start_ts = int(_dt.datetime.strptime(start_date, "%Y-%m-%d").timestamp())
    end_ts = int(_dt.datetime.now().timestamp()) + 86400
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?interval=1d&period1={start_ts}&period2={end_ts}&events=div"
    )
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=_YF_HEADERS, timeout=10)
            resp.raise_for_status()
            chart = resp.json()["chart"]["result"][0]
            timestamps = chart["timestamp"]
            closes = chart["indicators"]["adjclose"][0]["adjclose"]
            dates = [
                _dt.datetime.utcfromtimestamp(ts).date().isoformat()
                for ts in timestamps
            ]
            df = pd.DataFrame({"date": dates, "close": closes}).dropna()
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            return df.sort_values("date").reset_index(drop=True)
        except Exception as exc:
            if attempt == 0:
                print(f"  [fmt] Warning: price fetch for {ticker} failed ({exc}), retrying...")
                time.sleep(2)
            else:
                print(f"  [fmt] Warning: price fetch for {ticker} failed after retry ({exc})")
    return pd.DataFrame(columns=["date", "close"])


def _fetch_spy_qqq(start_date: str):
    """Return (spy_closes_df, qqq_closes_df). Either may be empty on failure."""
    spy = _fetch_closes("SPY", start_date)
    time.sleep(0.2)          # light rate-limit courtesy
    qqq = _fetch_closes("QQQ", start_date)
    return spy, qqq


def _ws_id(ws) -> int:
    """Return the numeric sheet ID for a gspread Worksheet."""
    return ws.id


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
    import gspread

    print("  [fmt] Writing hidden analytics tabs (Individual Brokerage)...")
    write_hidden_tabs(sheet)

    print("  [fmt] Writing hidden analytics tabs (IRA)...")
    write_ira_hidden_tabs(sheet)

    print("  [fmt] Writing hidden analytics tabs (Overall)...")
    write_overall_hidden_tabs(sheet)

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

    # IRA tabs — apply same formatting if they exist
    for tab_name, fmt_fn in [
        ("IRA_Holdings",     format_holdings),
        ("IRA_Transactions", format_transactions),
        ("IRA_Dividends",    format_dividends),
        ("IRA_Historical",   format_historical),
    ]:
        try:
            ws = sheet.worksheet(tab_name)
            print(f"  [fmt] {tab_name} tab...")
            fmt_fn(sheet, ws)
        except gspread.WorksheetNotFound:
            pass  # IRA tabs not yet created — skip

    print("  [fmt] Formatting complete.")


def compute_risk_metrics(portfolio_df: pd.DataFrame, spy_closes: pd.DataFrame) -> dict:
    """
    Compute annualized volatility and beta vs SPY for 1Y and All-time windows.

    Returns dict with keys:
        vol_1y, vol_all, beta_1y, beta_all
    All values are floats; vol in % (e.g. 18.5 means 18.5%), beta dimensionless.
    """
    import numpy as np

    today = pd.Timestamp.today().normalize()
    port  = portfolio_df.copy()
    port["date"] = pd.to_datetime(port["date"])
    port = port.sort_values("date").set_index("date")

    spy = spy_closes.copy()
    spy["date"] = pd.to_datetime(spy["date"])
    spy = spy.sort_values("date").set_index("date")

    def _vol_beta(start: pd.Timestamp):
        p = port[port.index >= start]["total_value"].pct_change().dropna()
        s = spy[spy.index >= start]["close"].pct_change().dropna()
        # Align on common dates
        aligned = pd.concat([p.rename("port"), s.rename("spy")], axis=1).dropna()
        if len(aligned) < 20:
            return None, None
        vol = float(aligned["port"].std() * (252 ** 0.5) * 100)
        cov = float(aligned.cov().loc["port", "spy"])
        var_spy = float(aligned["spy"].var())
        beta = round(cov / var_spy, 3) if var_spy > 0 else None
        return round(vol, 2), beta

    vol_1y,  beta_1y  = _vol_beta(today - pd.DateOffset(years=1))
    vol_all, beta_all = _vol_beta(pd.Timestamp("1900-01-01"))

    return {
        "vol_1y":   vol_1y  if vol_1y  is not None else "",
        "vol_all":  vol_all if vol_all is not None else "",
        "beta_1y":  beta_1y  if beta_1y  is not None else "",
        "beta_all": beta_all if beta_all is not None else "",
    }


def _xirr(cashflows: list, dates: list) -> float:
    """
    Compute XIRR: annualized internal rate of return for irregular cash flows.
    Negative cashflows = money going in, positive = money coming out.
    Uses Newton-Raphson with a bisection fallback. Returns 0.0 on failure.
    """
    if len(cashflows) < 2:
        return 0.0
    t0 = dates[0]
    years = [(d - t0).days / 365.25 for d in dates]

    def npv(r):
        return sum(cf / (1 + r) ** t for cf, t in zip(cashflows, years))

    def npv_d(r):
        return sum(-t * cf / (1 + r) ** (t + 1) for cf, t in zip(cashflows, years))

    rate = 0.1
    for _ in range(200):
        f, fp = npv(rate), npv_d(rate)
        if abs(fp) < 1e-12:
            break
        step = f / fp
        rate = max(-0.9999, rate - step)
        if abs(step) < 1e-9:
            break

    # Sanity check — reject obviously wrong results
    if not (-0.99 < rate < 50.0):
        return 0.0
    return rate


def _build_daily_cf(transactions_df: pd.DataFrame) -> dict:
    """
    Compute per-day external cash flow from a single account's transactions.
    Returns dict of {Timestamp: float} for days with external CF > $0.01.
    Processes from inception so running_cash is correct at any sub-period start.
    """
    txn_df = transactions_df.copy()
    txn_df["date"]   = pd.to_datetime(txn_df["date"], errors="coerce")
    txn_df["amount"] = pd.to_numeric(txn_df["amount"], errors="coerce").fillna(0.0)
    daily_cf: dict = {}
    running_cash = 0.0
    for d, day_txns in txn_df.sort_values("date").groupby("date"):
        deposits  = day_txns[day_txns["action"] == "DEPOSIT"]["amount"].abs().sum()
        sells     = day_txns[day_txns["action"].isin(["SELL", "DIVIDEND"])]["amount"].abs().sum()
        buys      = day_txns[day_txns["action"].isin(["BUY", "REINVESTMENT"])]["amount"].abs().sum()
        # Deposits (brokerage EFTs, IRA cash contributions) are explicit external capital.
        # For 401k-style accounts, contributions arrive as direct BUYs with no prior deposit
        # event — the fallback max(0, buys - available) catches those as external capital too.
        available    = running_cash + float(sells) + float(deposits)
        ext_cf       = float(deposits) + max(0.0, float(buys) - available)
        running_cash = max(0.0, available - float(buys))
        if ext_cf > 0.01:
            daily_cf[pd.Timestamp(d).normalize()] = ext_cf
    return daily_cf


def compute_period_returns(portfolio_df: pd.DataFrame, spy_df: pd.DataFrame,
                           qqq_df: pd.DataFrame,
                           transactions_df: pd.DataFrame | None = None,
                           daily_cf_override: dict | None = None) -> pd.DataFrame:
    """
    Compute portfolio TWR, MWR, SPY, and QQQ returns for each benchmark period.

    TWR  — Time-Weighted Return: strips deposit timing, ideal for benchmark comparison.
    MWR  — Money-Weighted Return (XIRR): reflects actual investor experience.
    Both are expressed as total period returns (not annualized) to match SPY/QQQ.

    Returns:
        DataFrame with columns: period, twr_pct, mwr_pct, spy_pct, qqq_pct
    """
    today = pd.Timestamp.today().normalize()

    def _period_start(label: str) -> pd.Timestamp:
        if label == "MTD": return pd.Timestamp(today.year, today.month, 1)
        if label == "1M":  return today - pd.DateOffset(months=1)
        if label == "3M":  return today - pd.DateOffset(months=3)
        if label == "6M":  return today - pd.DateOffset(months=6)
        if label == "YTD": return pd.Timestamp(today.year, 1, 1)
        if label == "1Y":  return today - pd.DateOffset(years=1)
        if label == "2Y":  return today - pd.DateOffset(years=2)
        if label == "3Y":  return today - pd.DateOffset(years=3)
        if label == "All": return pd.Timestamp("1900-01-01")
        raise ValueError(f"Unknown period: {label}")

    def _series_return(df: pd.DataFrame, value_col: str, start: pd.Timestamp) -> float:
        df = df[df["date"] >= start].sort_values("date")
        if len(df) < 2:
            return 0.0
        return round((df[value_col].iloc[-1] / df[value_col].iloc[0] - 1) * 100, 2)

    # Normalize dates
    portfolio_df = portfolio_df.copy()
    spy_df = spy_df.copy()
    qqq_df = qqq_df.copy()
    for df in (portfolio_df, spy_df, qqq_df):
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

    txn_df = None
    if transactions_df is not None and not transactions_df.empty:
        txn_df = transactions_df.copy()
        txn_df["date"] = pd.to_datetime(txn_df["date"], errors="coerce")
        txn_df["amount"] = pd.to_numeric(txn_df["amount"], errors="coerce").fillna(0.0)

    # ── Build daily external CF map from ALL history (inception → today) ────
    # external_cf(d) = portion of BUYs on day d NOT covered by available idle cash.
    # Must process from inception so running_cash is correct at any sub-period start.
    if daily_cf_override is not None:
        daily_cf = daily_cf_override
    else:
        daily_cf: dict = {}
        if txn_df is not None:
            daily_cf = _build_daily_cf(transactions_df)

    def _twr(port_df: pd.DataFrame, start: pd.Timestamp) -> float:
        """Chain daily sub-period returns, adjusting each day's denominator for new external capital."""
        window = port_df[port_df["date"] >= start].sort_values("date").reset_index(drop=True)
        if len(window) < 2:
            return 0.0
        twr = 1.0
        for i in range(1, len(window)):
            v_prev    = float(window.loc[i - 1, "total_value"])
            v_curr    = float(window.loc[i, "total_value"])
            date_curr = pd.Timestamp(window.loc[i, "date"]).normalize()
            cf        = daily_cf.get(date_curr, 0.0)
            denom     = v_prev + cf
            if denom <= 0:
                continue
            twr *= v_curr / denom
        return round((twr - 1) * 100, 2)

    def _mwr(port_df: pd.DataFrame, start: pd.Timestamp) -> float:
        """
        XIRR-based MWR: treats start_val as initial outlay, external deposits during
        the period as additional outlays, and end_val as the terminal inflow.
        Returns total period return (de-annualized from XIRR) to match TWR scale.
        """
        window = port_df[port_df["date"] >= start].sort_values("date").reset_index(drop=True)
        if len(window) < 2:
            return 0.0
        start_date = pd.Timestamp(window.loc[0, "date"]).normalize()
        end_date   = pd.Timestamp(window.loc[len(window) - 1, "date"]).normalize()
        start_val  = float(window.loc[0, "total_value"])
        end_val    = float(window.loc[len(window) - 1, "total_value"])
        if start_val <= 0:
            return 0.0

        # Build XIRR cash flow list
        # Negative = money going in, positive = money coming out
        cfs   = [-start_val]
        dates = [start_date]
        for d, cf in sorted(daily_cf.items()):
            if start_date < d < end_date:
                cfs.append(-cf)
                dates.append(d)
        cfs.append(end_val)
        dates.append(end_date)

        if (end_date - start_date).days < 2:
            return 0.0

        annualized = _xirr(cfs, dates)
        period_years = (end_date - start_date).days / 365.25
        total_return = (1 + annualized) ** period_years - 1
        return round(total_return * 100, 2)

    periods = ["MTD", "1M", "3M", "6M", "YTD", "1Y", "2Y", "3Y", "All"]
    rows = []
    for p in periods:
        start = _period_start(p)
        rows.append({
            "period":   p,
            "twr_pct":  _twr(portfolio_df, start),
            "mwr_pct":  _mwr(portfolio_df, start),
            "spy_pct":  _series_return(spy_df, "close", start),
            "qqq_pct":  _series_return(qqq_df, "close", start),
        })
    return pd.DataFrame(rows)


def _fix_historical_cash_rows(sheet, transactions_df: pd.DataFrame):
    """
    One-time migration: recompute CASH rows in the Historical tab using the correct
    running-balance method (SELLs/DIVs add cash, BUYs draw it down, floor at 0).
    Removes all existing CASH rows and replaces them with corrected values.
    """
    try:
        hist_ws = sheet.worksheet("Historical")
    except Exception:
        return

    all_vals = hist_ws.get_all_values()
    if len(all_vals) < 2:
        return

    headers = all_vals[0]
    non_cash = [headers]
    old_cash_count = 0
    equity_dates: set[str] = set()
    for row in all_vals[1:]:
        if len(row) > 1 and row[1] == "CASH":
            old_cash_count += 1
        else:
            non_cash.append(row)
            if row and row[0]:
                equity_dates.add(row[0])

    if old_cash_count == 0:
        return  # Already clean — nothing to fix

    # Build running cash balance from transactions
    txn = transactions_df.copy()
    txn["date"] = pd.to_datetime(txn["date"], errors="coerce")
    txn["amount"] = pd.to_numeric(txn["amount"], errors="coerce").fillna(0.0)
    txn = txn.sort_values("date").reset_index(drop=True)

    running = 0.0
    cash_by_date: dict[str, float] = {}
    for _, row in txn.iterrows():
        action = row.get("action", "")
        amount = float(row.get("amount", 0.0))
        if action in ("SELL", "DIVIDEND"):
            running += abs(amount)
        elif action in ("BUY", "REINVESTMENT"):
            running = max(0.0, running - abs(amount))
        cash_by_date[str(row["date"].date())] = running

    sorted_txn_dates = sorted(cash_by_date.keys())

    def _cash_on(date_str: str) -> float:
        import bisect
        idx = bisect.bisect_right(sorted_txn_dates, date_str) - 1
        return cash_by_date[sorted_txn_dates[idx]] if idx >= 0 else 0.0

    new_cash_rows = []
    for d in sorted(equity_dates):
        val = _cash_on(d)
        if val > 0.01:
            new_cash_rows.append([d, "CASH", 1, round(val, 2), round(val, 2)])

    all_rows = non_cash + new_cash_rows
    all_rows_sorted = [all_rows[0]] + sorted(all_rows[1:], key=lambda r: r[0])

    hist_ws.clear()
    hist_ws.update(all_rows_sorted, value_input_option="USER_ENTERED")
    print(f"  [fix] Historical CASH rows: removed {old_cash_count} old, wrote {len(new_cash_rows)} corrected")


def write_hidden_tabs(sheet):
    """
    Build _PortfolioHistory (daily portfolio totals) and _Benchmarks (period returns).
    Both tabs are hidden. Safe to re-run — tabs are cleared before re-writing.
    """

    # ── Migrate Historical CASH rows to correct running-balance method ──────
    # Must happen before we read Historical below, so _PortfolioHistory is built
    # from corrected values.
    try:
        txn_ws = sheet.worksheet("Transactions")
        _txn_for_migration = read_tab_as_df(txn_ws)
        if not _txn_for_migration.empty:
            _fix_historical_cash_rows(sheet, _txn_for_migration)
    except Exception as _e:
        print(f"  [fix] CASH row migration skipped: {_e}")

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

    # ── Read Transactions tab (needed for both Dietz returns and realized gains) ──
    transactions_df = None
    try:
        txn_ws = sheet.worksheet("Transactions")
        transactions_df = read_tab_as_df(txn_ws)
    except Exception:
        pass  # Falls back to simple return if tab missing

    # ── Write _Analytics (realized gains — independent of yfinance) ────────
    from tools.portfolio_calculator import calculate_realized_gains
    realized_gains = 0.0
    if transactions_df is not None and not transactions_df.empty:
        realized_gains = calculate_realized_gains(transactions_df)
    try:
        an_ws = sheet.worksheet("_Analytics")
        an_ws.clear()
    except Exception:
        an_ws = sheet.add_worksheet(title="_Analytics", rows=10, cols=2)
    first_buy_date = ""
    if transactions_df is not None and not transactions_df.empty:
        buys = transactions_df[transactions_df["action"] == "BUY"]["date"]
        buys = pd.to_datetime(buys, errors="coerce").dropna()
        if not buys.empty:
            first_buy_date = str(buys.min().date())

    an_ws.update([
        ["metric", "value"],
        ["realized_gains", realized_gains],
        ["first_investment_date", first_buy_date],
    ], value_input_option="USER_ENTERED")
    _hide_tab(sheet, an_ws)
    print(f"  [fmt] _Analytics written — realized_gains: {realized_gains}")

    # ── Fetch SPY and QQQ via Yahoo Finance ─────────────────────────────────
    start_date = str(portfolio_daily["date"].min().date())
    spy_closes, qqq_closes = _fetch_spy_qqq(start_date)
    if spy_closes.empty or qqq_closes.empty:
        print("  [fmt] Warning: SPY/QQQ fetch failed. Benchmark tab skipped.")
        return

    # ── Compute period returns (Modified Dietz for portfolio) ───────────────
    period_df = compute_period_returns(portfolio_daily, spy_closes, qqq_closes, transactions_df)

    # ── Write _Benchmarks ───────────────────────────────────────────────────
    bm_headers = ["period", "twr_pct", "mwr_pct", "spy_pct", "qqq_pct"]
    try:
        bm_ws = sheet.worksheet("_Benchmarks")
        bm_ws.clear()
        bm_ws.append_row(bm_headers)
    except Exception:
        bm_ws = sheet.add_worksheet(title="_Benchmarks", rows=20, cols=5)
        bm_ws.append_row(bm_headers)

    bm_rows = [
        [row["period"], row["twr_pct"], row["mwr_pct"], row["spy_pct"], row["qqq_pct"]]
        for _, row in period_df.iterrows()
    ]
    bm_ws.append_rows(bm_rows, value_input_option="USER_ENTERED")
    _hide_tab(sheet, bm_ws)

    # ── Append risk metrics to _Analytics ──────────────────────────────────
    risk = compute_risk_metrics(portfolio_daily, spy_closes)
    an_ws.append_rows([
        ["vol_1y",   risk["vol_1y"]],
        ["vol_all",  risk["vol_all"]],
        ["beta_1y",  risk["beta_1y"]],
        ["beta_all", risk["beta_all"]],
    ], value_input_option="USER_ENTERED")
    print(f"  [fmt] _PortfolioHistory: {len(ph_rows)} rows, _Benchmarks: {len(bm_rows)} rows, vol_1y: {risk['vol_1y']}%, beta_1y: {risk['beta_1y']}")


def write_ira_hidden_tabs(sheet):
    """
    Build _IRA_PortfolioHistory, _IRA_Benchmarks, and _IRA_Analytics for the Roth IRA account.
    Mirrors write_hidden_tabs() but reads from IRA_Historical and IRA_Transactions tabs.
    """

    try:
        hist_ws = sheet.worksheet("IRA_Historical")
    except Exception:
        print("  [fmt] IRA_Historical not found — skipping IRA hidden tabs.")
        return

    hist_df = read_tab_as_df(hist_ws)
    if hist_df.empty:
        print("  [fmt] IRA_Historical is empty — skipping IRA hidden tabs.")
        return

    hist_df["date"]           = pd.to_datetime(hist_df["date"], errors="coerce")
    hist_df["position_value"] = pd.to_numeric(hist_df["position_value"], errors="coerce")

    portfolio_daily = (
        hist_df.groupby("date")["position_value"]
        .sum().reset_index()
        .rename(columns={"position_value": "total_value"})
        .sort_values("date")
    )

    # Write _IRA_PortfolioHistory
    ph_headers = ["date", "total_value"]
    try:
        ph_ws = sheet.worksheet("_IRA_PortfolioHistory")
        ph_ws.clear()
        ph_ws.append_row(ph_headers)
    except Exception:
        ph_ws = sheet.add_worksheet(title="_IRA_PortfolioHistory", rows=2000, cols=2)
        ph_ws.append_row(ph_headers)

    ph_rows = [[str(r["date"].date()), round(float(r["total_value"]), 2)]
               for _, r in portfolio_daily.iterrows()]
    if ph_rows:
        ph_ws.append_rows(ph_rows, value_input_option="USER_ENTERED")
    _hide_tab(sheet, ph_ws)

    # Read IRA transactions — two views:
    #   all_txns_df : full history (for realized gains — rollover is a real economic event)
    #   transactions_df : excludes ROLLOVER_OUT (for TWR/MWR external CF calculations)
    all_txns_df = None
    transactions_df = None
    try:
        txn_ws = sheet.worksheet("IRA_Transactions")
        raw_txns = read_tab_as_df(txn_ws)
        if not raw_txns.empty:
            raw_txns["date"]   = pd.to_datetime(raw_txns["date"], errors="coerce")
            raw_txns["amount"] = pd.to_numeric(raw_txns["amount"], errors="coerce").fillna(0.0)
            all_txns_df    = raw_txns
            transactions_df = raw_txns[
                ~raw_txns["description"].astype(str).str.contains("ROLLOVER_OUT", na=False)
            ]
    except Exception:
        pass

    # Write _IRA_Analytics
    from tools.portfolio_calculator import calculate_realized_gains
    realized_gains = 0.0
    first_buy_date = ""
    if all_txns_df is not None and not all_txns_df.empty:
        realized_gains = calculate_realized_gains(all_txns_df)
        buys = all_txns_df[all_txns_df["action"] == "BUY"]["date"].dropna()
        if not buys.empty:
            first_buy_date = str(buys.min().date())

    try:
        an_ws = sheet.worksheet("_IRA_Analytics")
        an_ws.clear()
    except Exception:
        an_ws = sheet.add_worksheet(title="_IRA_Analytics", rows=10, cols=2)
    an_ws.update([
        ["metric", "value"],
        ["realized_gains", realized_gains],
        ["first_investment_date", first_buy_date],
    ], value_input_option="USER_ENTERED")
    _hide_tab(sheet, an_ws)

    # Fetch SPY/QQQ for benchmark comparison
    start_date = str(portfolio_daily["date"].min().date())
    spy_closes, qqq_closes = _fetch_spy_qqq(start_date)
    if spy_closes.empty or qqq_closes.empty:
        print("  [fmt] IRA: SPY/QQQ fetch failed. Benchmark tab skipped.")
        return

    # Use all_txns_df (including ROLLOVER_OUT) for TWR/MWR so that rollover proceeds
    # sitting as CASH in the portfolio correctly cover the next-day IRA re-buys.
    # Excluding ROLLOVER_OUT would make those re-buys look like fresh external capital,
    # inflating the TWR denominator and producing a phantom ~40% single-day loss.
    period_df = compute_period_returns(portfolio_daily, spy_closes, qqq_closes, all_txns_df)

    bm_headers = ["period", "twr_pct", "mwr_pct", "spy_pct", "qqq_pct"]
    try:
        bm_ws = sheet.worksheet("_IRA_Benchmarks")
        bm_ws.clear()
        bm_ws.append_row(bm_headers)
    except Exception:
        bm_ws = sheet.add_worksheet(title="_IRA_Benchmarks", rows=20, cols=5)
        bm_ws.append_row(bm_headers)

    bm_rows = [[r["period"], r["twr_pct"], r["mwr_pct"], r["spy_pct"], r["qqq_pct"]]
               for _, r in period_df.iterrows()]
    bm_ws.append_rows(bm_rows, value_input_option="USER_ENTERED")
    _hide_tab(sheet, bm_ws)

    # ── Append risk metrics to _IRA_Analytics ──────────────────────────────
    risk = compute_risk_metrics(portfolio_daily, spy_closes)
    an_ws.append_rows([
        ["vol_1y",   risk["vol_1y"]],
        ["vol_all",  risk["vol_all"]],
        ["beta_1y",  risk["beta_1y"]],
        ["beta_all", risk["beta_all"]],
    ], value_input_option="USER_ENTERED")
    print(f"  [fmt] _IRA_PortfolioHistory: {len(ph_rows)} rows, _IRA_Benchmarks: {len(bm_rows)} rows, realized_gains: {realized_gains}, vol_1y: {risk['vol_1y']}%, beta_1y: {risk['beta_1y']}")


def write_overall_hidden_tabs(sheet):
    """
    Build _Overall_PortfolioHistory and _Overall_Benchmarks by combining the
    Individual Brokerage and Roth IRA histories.
    """

    # ── Load both portfolio histories ───────────────────────────────────────
    def _load_ph(tab_name):
        try:
            ws = sheet.worksheet(tab_name)
            df = read_tab_as_df(ws)
            if df.empty:
                return pd.DataFrame(columns=["date", "total_value"])
            df["date"]        = pd.to_datetime(df["date"], errors="coerce")
            df["total_value"] = pd.to_numeric(df["total_value"], errors="coerce").fillna(0.0)
            return df[["date", "total_value"]].dropna()
        except Exception:
            return pd.DataFrame(columns=["date", "total_value"])

    brk_ph = _load_ph("_PortfolioHistory")
    ira_ph = _load_ph("_IRA_PortfolioHistory")

    if brk_ph.empty and ira_ph.empty:
        print("  [fmt] Overall: no portfolio history found — skipping.")
        return

    # Sum both accounts by date
    combined = pd.concat([brk_ph, ira_ph], ignore_index=True)
    portfolio_daily = (
        combined.groupby("date")["total_value"]
        .sum().reset_index().sort_values("date")
    )

    # ── Write _Overall_PortfolioHistory ─────────────────────────────────────
    ph_headers = ["date", "total_value"]
    try:
        ph_ws = sheet.worksheet("_Overall_PortfolioHistory")
        ph_ws.clear()
        ph_ws.append_row(ph_headers)
    except Exception:
        ph_ws = sheet.add_worksheet(title="_Overall_PortfolioHistory", rows=2000, cols=2)
        ph_ws.append_row(ph_headers)

    ph_rows = [[str(r["date"].date()), round(float(r["total_value"]), 2)]
               for _, r in portfolio_daily.iterrows()]
    if ph_rows:
        ph_ws.append_rows(ph_rows, value_input_option="USER_ENTERED")
    _hide_tab(sheet, ph_ws)

    # ── Load both transaction sets — combine, excluding ROLLOVER_OUT from CF math ──
    def _load_txns(tab_name, exclude_rollover=False):
        try:
            ws = sheet.worksheet(tab_name)
            df = read_tab_as_df(ws)
            if df.empty:
                return pd.DataFrame()
            df["date"]   = pd.to_datetime(df["date"], errors="coerce")
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
            if exclude_rollover:
                df = df[~df["description"].astype(str).str.contains("ROLLOVER_OUT", na=False)]
            return df
        except Exception:
            return pd.DataFrame()

    brk_txns = _load_txns("Transactions")
    # For Overall, include ROLLOVER_OUT in the IRA transactions so the Oct 6 rollover
    # proceeds (~$23K) correctly replenish running_cash before the Oct 7 re-buys.
    # Excluding them would make the Oct 7 re-buys look like fresh external capital,
    # inflating the TWR denominator and creating a phantom single-day loss.
    ira_txns = _load_txns("IRA_Transactions", exclude_rollover=False)

    # ── Fetch SPY/QQQ ───────────────────────────────────────────────────────
    start_date = str(portfolio_daily["date"].min().date())
    spy_closes, qqq_closes = _fetch_spy_qqq(start_date)
    if spy_closes.empty or qqq_closes.empty:
        print("  [fmt] Overall: SPY/QQQ fetch failed. Benchmark tab skipped.")
        return

    # ── Build external CF separately per account, then sum by date ─────────
    # Merging transactions into one pool causes running_cash from one account to
    # bleed into the other, making real deposits look like recycled proceeds.
    # The correct approach: each account's cash balance is independent.
    combined_cf: dict = {}
    for txns in [brk_txns, ira_txns]:
        if not txns.empty:
            for d, amt in _build_daily_cf(txns).items():
                combined_cf[d] = combined_cf.get(d, 0.0) + amt

    period_df = compute_period_returns(portfolio_daily, spy_closes, qqq_closes,
                                       daily_cf_override=combined_cf)

    bm_headers = ["period", "twr_pct", "mwr_pct", "spy_pct", "qqq_pct"]
    try:
        bm_ws = sheet.worksheet("_Overall_Benchmarks")
        bm_ws.clear()
        bm_ws.append_row(bm_headers)
    except Exception:
        bm_ws = sheet.add_worksheet(title="_Overall_Benchmarks", rows=20, cols=5)
        bm_ws.append_row(bm_headers)

    bm_rows = [[r["period"], r["twr_pct"], r["mwr_pct"], r["spy_pct"], r["qqq_pct"]]
               for _, r in period_df.iterrows()]
    bm_ws.append_rows(bm_rows, value_input_option="USER_ENTERED")
    _hide_tab(sheet, bm_ws)

    # ── Write _Overall_Analytics with risk metrics ──────────────────────────
    risk = compute_risk_metrics(portfolio_daily, spy_closes)
    try:
        oa_ws = sheet.worksheet("_Overall_Analytics")
        oa_ws.clear()
    except Exception:
        oa_ws = sheet.add_worksheet(title="_Overall_Analytics", rows=10, cols=2)
    oa_ws.update([
        ["metric", "value"],
        ["vol_1y",   risk["vol_1y"]],
        ["vol_all",  risk["vol_all"]],
        ["beta_1y",  risk["beta_1y"]],
        ["beta_all", risk["beta_all"]],
    ], value_input_option="USER_ENTERED")
    _hide_tab(sheet, oa_ws)

    print(f"  [fmt] _Overall_PortfolioHistory: {len(ph_rows)} rows, _Overall_Benchmarks: {len(bm_rows)} rows, vol_1y: {risk['vol_1y']}%, beta_1y: {risk['beta_1y']}")


def write_dashboard_sections(sheet, dashboard_ws):
    """
    Rewrite the Dashboard tab with KPI row, section headers, and benchmark comparison table.
    The portfolio growth chart is added separately by add_portfolio_chart().
    """
    _clear_tab_formatting(sheet, dashboard_ws)
    ws_id = _ws_id(dashboard_ws)

    # ── Read first investment date ──────────────────────────────────────────
    first_investment_label = "All"
    try:
        txn_ws = sheet.worksheet("Transactions")
        txn_df = read_tab_as_df(txn_ws)
        if not txn_df.empty:
            txn_df["date"] = pd.to_datetime(txn_df["date"], errors="coerce")
            buys = txn_df[txn_df["action"] == "BUY"]["date"].dropna()
            if not buys.empty:
                first_date = buys.min()
                first_investment_label = f"All (since {first_date.strftime('%-m/%-d/%y')})"
    except Exception:
        pass

    # ── Read benchmark data ─────────────────────────────────────────────────
    period_labels = ["MTD", "1M", "3M", "6M", "YTD", "1Y", "2Y", "3Y", "All"]
    display_labels = ["MTD", "1M", "3M", "6M", "YTD", "1Y", "2Y", "3Y", first_investment_label]
    bm_data = {p: {"twr": 0.0, "mwr": 0.0, "spy": 0.0, "qqq": 0.0} for p in period_labels}
    try:
        bm_ws = sheet.worksheet("_Benchmarks")
        bm_df = read_tab_as_df(bm_ws)
        if not bm_df.empty:
            for _, row in bm_df.iterrows():
                p = str(row.get("period", ""))
                if p in bm_data:
                    bm_data[p] = {
                        "twr": float(row.get("twr_pct", 0) or 0),
                        "mwr": float(row.get("mwr_pct", 0) or 0),
                        "spy": float(row.get("spy_pct", 0) or 0),
                        "qqq": float(row.get("qqq_pct", 0) or 0),
                    }
    except Exception:
        pass  # Benchmarks tab not yet available

    # ── Read realized gains from _Analytics (written by write_hidden_tabs) ──
    realized_gains_val = 0.0
    try:
        an_ws = sheet.worksheet("_Analytics")
        an_df = read_tab_as_df(an_ws)
        if not an_df.empty:
            match = an_df[an_df["metric"] == "realized_gains"]
            if not match.empty:
                realized_gains_val = float(match.iloc[0]["value"])
    except Exception:
        pass

    # ── Build cell values ───────────────────────────────────────────────────
    kpi_labels = ["TOTAL VALUE", "UNREALIZED P&L", "REALIZED GAINS", "COST BASIS", "BEST PERFORMER"]
    kpi_formulas = [
        "=SUM(Holdings!F:F)",
        "=SUM(Holdings!G:G)",
        realized_gains_val,
        "=SUM(Holdings!D:D)",
        '=IFERROR(INDEX(Holdings!A2:A,MATCH(MAX(Holdings!H2:H),Holdings!H2:H,0))&" +"&TEXT(MAX(Holdings!H2:H),"0.00%"),"—")',
    ]

    bm_header_row = ["PERIOD", "TWR", "MWR", "S&P 500", "QQQ"]
    bm_rows = [
        [disp, bm_data[key]["twr"], bm_data[key]["mwr"], bm_data[key]["spy"], bm_data[key]["qqq"]]
        for key, disp in zip(period_labels, display_labels)
    ]

    # Clear and write all cells
    dashboard_ws.clear()
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

    # Column widths: 5 KPI columns each 160px wide
    for col_idx in range(5):
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": ws_id,
                    "dimension": "COLUMNS",
                    "startIndex": col_idx,
                    "endIndex": col_idx + 1,
                },
                "properties": {"pixelSize": 160},
                "fields": "pixelSize",
            }
        })

    # Row heights: title row 48px, KPI label row 24px, KPI value row 52px
    for row_idx, px in [(0, 48), (1, 24), (2, 52)]:
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": ws_id,
                    "dimension": "ROWS",
                    "startIndex": row_idx,
                    "endIndex": row_idx + 1,
                },
                "properties": {"pixelSize": px},
                "fields": "pixelSize",
            }
        })

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

    # Row 1 (index 0): title — large, bold, centered, card background
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

    # Row 2 (index 1): KPI labels — small gray caps
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

    # Row 3 (index 2): KPI values — large, bold, card background
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

    # Row 3, col 4 (Best Performer, index 4): purple
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 2, 3, 4, 5),
            "cell": {"userEnteredFormat": {
                "textFormat": {"foregroundColor": _PURPLE, "bold": True, "fontSize": 14},
            }},
            "fields": "userEnteredFormat.textFormat",
        }
    })

    # Row 3, col 3 (Cost Basis, index 3): teal
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 2, 3, 3, 4),
            "cell": {"userEnteredFormat": {
                "textFormat": {"foregroundColor": _TEAL, "bold": True, "fontSize": 14},
            }},
            "fields": "userEnteredFormat.textFormat",
        }
    })

    # Section headers: "PORTFOLIO GROWTH" (row index 4) and "vs. BENCHMARKS" (row index 25)
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

    # Benchmark table header row (row index 26)
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

    # Benchmark data cells (rows index 27-33, cols 1-3): centered, card bg, number format
    # Col 0 (period labels) styled separately below — excluded here to avoid number format bleed
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 27, 35, 1, 4),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _BG_CARD,
                "textFormat": {"foregroundColor": _WHITE, "bold": True, "fontSize": 11},
                "horizontalAlignment": "CENTER",
                "numberFormat": {"type": "NUMBER", "pattern": '#,##0.00"%"'},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,numberFormat)",
        }
    })

    # Period label column (col 0, rows index 27-33): card bg, gray text, no number format
    requests.append({
        "repeatCell": {
            "range": _range(ws_id, 27, 35, 0, 1),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _BG_CARD,
                "textFormat": {"foregroundColor": _GRAY, "bold": False, "fontSize": 11},
                "horizontalAlignment": "CENTER",
                "numberFormat": {"type": "TEXT"},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,numberFormat)",
        }
    })

    _batch_update(sheet, requests)

    # ── Conditional formatting ──────────────────────────────────────────────
    cf = []

    # KPI row 3: Unrealized P&L (col 1) and Realized Gains (col 2) — green if >= 0, red if < 0
    for col_idx in [1, 2]:
        cf.append({"addConditionalFormatRule": {"rule": {
            "ranges": [_range(ws_id, 2, 3, col_idx, col_idx + 1)],
            "booleanRule": {
                "condition": {"type": "NUMBER_GREATER_THAN_EQ", "values": [{"userEnteredValue": "0"}]},
                "format": {"textFormat": {"foregroundColor": _GREEN, "bold": True}},
            },
        }, "index": 0}})
        cf.append({"addConditionalFormatRule": {"rule": {
            "ranges": [_range(ws_id, 2, 3, col_idx, col_idx + 1)],
            "booleanRule": {
                "condition": {"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0"}]},
                "format": {"textFormat": {"foregroundColor": _RED, "bold": True}},
            },
        }, "index": 0}})

    # Benchmark portfolio column (col 1, rows 28-34, index 27-33): green bg if > spy, red if < spy
    cf.append({"addConditionalFormatRule": {"rule": {
        "ranges": [_range(ws_id, 27, 35, 1, 2)],
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
        "ranges": [_range(ws_id, 27, 35, 1, 2)],
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

    # SPY and QQQ columns (col 2 and 3, rows 28-34): positive=green text, negative=red text
    for col_idx in [2, 3]:
        cf.append({"addConditionalFormatRule": {"rule": {
            "ranges": [_range(ws_id, 27, 35, col_idx, col_idx + 1)],
            "booleanRule": {
                "condition": {"type": "NUMBER_GREATER_THAN_EQ", "values": [{"userEnteredValue": "0"}]},
                "format": {"textFormat": {"foregroundColor": _GREEN}},
            },
        }, "index": 0}})
        cf.append({"addConditionalFormatRule": {"rule": {
            "ranges": [_range(ws_id, 27, 35, col_idx, col_idx + 1)],
            "booleanRule": {
                "condition": {"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0"}]},
                "format": {"textFormat": {"foregroundColor": _RED}},
            },
        }, "index": 0}})

    _batch_update(sheet, cf)


def add_portfolio_chart(sheet, dashboard_ws):
    """
    Create (or replace) a LINE chart on the Dashboard tab sourced from _PortfolioHistory.
    Positioned at Dashboard row 6 (0-indexed row 5), column A, 700x300 pixels.
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
                            "rowIndex": 5,
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

    # Header row (row 0, cols 0-6)
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

    # Data rows (rows 1-5000, cols 0-6)
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

    # Alternating row banding (rows 1-5000, cols 0-6)
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

    # Header row (row 0, cols 0-4)
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

    # Data rows (rows 1-5000, cols 0-4)
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

    # Amount column (col 2, rows 1-5000): currency format
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

    # Type column (col 3, rows 1-5000): DIVIDEND=teal, REINVESTMENT=blue
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
        # Header row (row 0, cols 0-5)
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
        # Data rows (rows 1-10000, cols 0-5)
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
