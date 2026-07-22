#!/usr/bin/env python3
"""
Flask server for the Stock Portfolio Dashboard.

Routes:
  GET /          — serve static/index.html
  GET /api/data  — return full data payload as JSON
"""

from datetime import datetime, timezone

import gspread
import pandas as pd
import re as _re
import requests as _requests
from dotenv import load_dotenv
from flask import Flask, jsonify, send_from_directory

from tools.sheets_client import get_sheet, read_tab_as_df
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
_RETURNS_CACHE: dict = {}
_RETURNS_CACHE_TS: float = 0.0

load_dotenv()

# ---------------------------------------------------------------------------
# Shared HTTP headers for Yahoo Finance requests
# ---------------------------------------------------------------------------
_YF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}

# ---------------------------------------------------------------------------
# Sector lookup (cached 24 h)
# ---------------------------------------------------------------------------
_CUSIP_RE_PY = _re.compile(r'^[A-Z0-9]{8}[0-9]$')
_NO_PRICE_TICKERS_APP: frozenset = frozenset({"PUTN_LCV"})

_ETF_OVERRIDES: dict[str, str] = {
    "SPY": "ETF", "QQQ": "ETF", "IVV": "ETF", "VOO": "ETF", "VTI": "ETF",
    "GLD": "Commodities", "SLV": "Commodities", "USO": "Commodities", "IAU": "Commodities",
    "FXAIX": "ETF", "FSMDX": "ETF",
    "PUTN_LCV": "Other",
    "CASH": "Cash",
}

_sector_cache: dict[str, str] = {}
_sector_cache_ts: float = 0.0
_SECTOR_TTL: float = 86400.0  # 24 hours


def _cache_ttl() -> float:
    """15-min TTL during market hours (9:30–16:00 ET weekdays), 1-hr otherwise.
    Matches Yahoo Finance's ~15-min data delay for free tier."""
    now_et = datetime.now(_ET)
    if (
        now_et.weekday() < 5
        and now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        <= now_et
        <= now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    ):
        return 900   # 15 min — matches Yahoo Finance delay
    return 3600


def _fetch_sectors(tickers: list[str]) -> dict[str, str]:
    """Fetch sector via Yahoo Finance v1/search (no auth required).
    Cached 24 h. ETFs/commodities resolved via _ETF_OVERRIDES without a network call.
    """
    import time as _t
    global _sector_cache, _sector_cache_ts
    now = _t.time()
    if _sector_cache and now - _sector_cache_ts < _SECTOR_TTL:
        return _sector_cache

    result: dict[str, str] = dict(_ETF_OVERRIDES)
    to_fetch = [
        t for t in set(tickers)
        if t and t not in result and not _CUSIP_RE_PY.match(t)
    ]

    for ticker in to_fetch:
        try:
            url = (
                f"https://query1.finance.yahoo.com/v1/finance/search"
                f"?q={ticker}&quotesCount=1&newsCount=0&enableFuzzyQuery=false"
            )
            r = _requests.get(url, headers=_YF_HEADERS, timeout=10)
            r.raise_for_status()
            quotes = r.json().get("quotes") or []
            # Pick the quote whose symbol exactly matches (search can return similar tickers)
            quote = next((q for q in quotes if q.get("symbol", "").upper() == ticker.upper()), quotes[0] if quotes else {})
            sector = quote.get("sector", "")
            qtype  = quote.get("quoteType", "")
            if sector:
                result[ticker] = sector
            elif qtype in ("ETF", "MUTUALFUND"):
                result[ticker] = "ETF"
            else:
                result[ticker] = "Other"
            print(f"  [app] sector {ticker} → {result[ticker]}")
        except Exception as exc:
            print(f"  [app] sector {ticker} failed: {exc}")
            result[ticker] = "Other"
        _t.sleep(0.15)

    _sector_cache = result
    _sector_cache_ts = now
    return result


def _backfill_history_gap(
    ph_df: pd.DataFrame,
    holdings_records: list,
    today_ts: pd.Timestamp,
    txn_cash: float | None = None,
) -> pd.DataFrame:
    """
    Fill any gap between the last stored _PortfolioHistory entry and yesterday by
    computing daily portfolio values from current Holdings shares × Yahoo Finance prices.
    Prevents short-period charts (1W, MTD) from going blank when the scheduled import
    hasn't run recently. Results are merged without overwriting stored data.
    """
    import time as _t
    from tools.format_dashboard import _fetch_closes

    if ph_df.empty or not holdings_records:
        return ph_df

    non_today = ph_df[ph_df["date"] < today_ts]
    if non_today.empty:
        return ph_df

    last_hist = non_today["date"].max().normalize()
    yesterday = (today_ts - pd.Timedelta(days=1)).normalize()

    if last_hist >= yesterday:
        return ph_df  # already current, nothing to fill

    gap_start = last_hist + pd.Timedelta(days=1)
    gap_dates = pd.date_range(start=gap_start, end=yesterday, freq="B")
    if gap_dates.empty:
        return ph_df

    start_str = str(gap_start.date())

    # Build ticker → shares from Holdings; CASH uses txn-derived balance when available
    ticker_shares: dict[str, float] = {}
    static_value = 0.0  # holdings excluded from Yahoo Finance fetch (CUSIP / no-price tickers)
    cash_value = txn_cash if txn_cash is not None else 0.0
    for h in holdings_records:
        ticker = str(h.get("ticker", "")).strip()
        shares = float(h.get("shares_held", 0) or 0)
        if ticker == "CASH" and txn_cash is None:
            cash_value = float(h.get("current_value", 0) or 0)
        elif (ticker
              and ticker != "CASH"
              and shares > 0
              and not _CUSIP_RE_PY.match(ticker)
              and ticker not in _NO_PRICE_TICKERS_APP):
            ticker_shares[ticker] = shares
        elif ticker and ticker != "CASH" and shares > 0:
            # Can't fetch historical prices — use current value as a static estimate,
            # same approach as CASH. Prevents a daily jump at the live/backfill boundary.
            static_value += float(h.get("current_value", 0) or 0)

    # Fetch historical closes for each ticker in the gap window
    price_series: dict[str, pd.Series] = {}
    for ticker in ticker_shares:
        try:
            closes_df = _fetch_closes(ticker, start_str)
            if not closes_df.empty:
                closes_df = closes_df[closes_df["date"] >= pd.Timestamp(start_str)]
                closes_df = closes_df[closes_df["date"] <= yesterday]
                if not closes_df.empty:
                    price_series[ticker] = closes_df.set_index("date")["close"]
            _t.sleep(0.15)
        except Exception:
            pass

    # Compute daily portfolio totals for each gap business day
    new_rows = []
    for d in gap_dates:
        total = cash_value + static_value  # cash and non-priceable holdings are constant
        for ticker, shares in ticker_shares.items():
            if ticker in price_series:
                avail = price_series[ticker]
                avail = avail[avail.index <= d]
                if not avail.empty:
                    total += shares * float(avail.iloc[-1])
        if total > 0:
            new_rows.append({"date": d.normalize(), "total_value": round(total, 2)})

    if not new_rows:
        return ph_df

    gap_df = pd.DataFrame(new_rows)
    # Merge: prefer stored data over backfilled estimates (ph_df first in concat)
    extended = pd.concat([ph_df, gap_df], ignore_index=True)
    extended = (extended.drop_duplicates(subset=["date"])
                .sort_values("date").reset_index(drop=True))
    print(f"  [app] backfilled {len(new_rows)} history gap days "
          f"({start_str} → {str(yesterday.date())})")
    return extended


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

    def _stocks_val(holdings_records: list) -> float:
        """Sum live stock position values, excluding CASH."""
        return sum(float(h.get("current_value") or 0)
                   for h in holdings_records if h.get("ticker") != "CASH")

    def _holdings_cash(holdings_records: list) -> float:
        """Read cash from the Holdings CASH row — authoritative env-var value set at import time.
        Transaction-derived cash (_txn_cash) is intentionally not used: fees, sweeps, and
        withheld tax make it unreliable and cause the portfolio total to appear inflated."""
        for h in holdings_records:
            if h.get("ticker") == "CASH":
                return float(h.get("current_value") or 0)
        return 0.0

    # Read inputs from Sheets
    brk_ph   = _read_tab(sheet, "_PortfolioHistory",     _HISTORY_COLS,      _HISTORY_NUMERIC)
    ira_ph   = _read_tab(sheet, "_IRA_PortfolioHistory", _HISTORY_COLS,      _HISTORY_NUMERIC)
    brk_h    = _read_tab(sheet, "Holdings",              _HOLDINGS_COLS,     _HOLDINGS_NUMERIC)
    ira_h    = _read_tab(sheet, "IRA_Holdings",          _HOLDINGS_COLS,     _HOLDINGS_NUMERIC)
    brk_txns = _read_tab(sheet, "Transactions",          _TRANSACTIONS_COLS, _TRANSACTIONS_NUMERIC)
    ira_txns = _read_tab(sheet, "IRA_Transactions",      _TRANSACTIONS_COLS, _TRANSACTIONS_NUMERIC)

    brk_cash  = _holdings_cash(brk_h)
    ira_cash  = _holdings_cash(ira_h)
    brk_today = _stocks_val(brk_h) + brk_cash
    ira_today = _stocks_val(ira_h) + ira_cash

    brk_ph_df   = _backfill_history_gap(_ph_df(brk_ph, brk_today), brk_h, today_ts, txn_cash=brk_cash)
    ira_ph_df   = _backfill_history_gap(_ph_df(ira_ph, ira_today), ira_h, today_ts, txn_cash=ira_cash)
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
        # Portfolio histories with today's live value appended — used by the chart
        # so it always ends at the current portfolio value, not the last import date.
        "brk_history":     brk_ph_df.assign(date=brk_ph_df["date"].dt.strftime("%Y-%m-%d")).to_dict("records"),
        "ira_history":     ira_ph_df.assign(date=ira_ph_df["date"].dt.strftime("%Y-%m-%d")).to_dict("records"),
        "overall_history": overall_ph_df.assign(date=overall_ph_df["date"].dt.strftime("%Y-%m-%d")).to_dict("records"),
    }
    _RETURNS_CACHE    = result
    _RETURNS_CACHE_TS = now
    return result


app = Flask(__name__, static_folder="static")

# ---------------------------------------------------------------------------
# Column name maps: Sheets tab column → JSON field
# ---------------------------------------------------------------------------

# Column headers match those written by import_transactions.py (all lowercase/snake_case).
# Maps are identity (sheet column == JSON field) so the dict just lists which cols to keep.
_HOLDINGS_COLS = {
    "ticker": "ticker",
    "shares_held": "shares_held",
    "avg_cost_basis": "avg_cost_basis",
    "total_cost_basis": "total_cost_basis",
    "current_price": "current_price",
    "current_value": "current_value",
    "unrealized_pnl": "unrealized_pnl",
    "unrealized_pnl_pct": "unrealized_pnl_pct",
    "day_change_pct": "day_change_pct",
}

_HOLDINGS_NUMERIC = [
    "shares_held", "avg_cost_basis", "total_cost_basis",
    "current_price", "current_value", "unrealized_pnl",
    "unrealized_pnl_pct", "day_change_pct",
]

_TRANSACTIONS_COLS = {
    "date": "date",
    "ticker": "ticker",
    "action": "action",
    "shares": "shares",
    "price": "price",
    "amount": "amount",
    "description": "description",
}

_TRANSACTIONS_NUMERIC = ["shares", "price", "amount"]

_DIVIDENDS_COLS = {
    "date": "date",
    "ticker": "ticker",
    "amount": "amount",
    "type": "type",
}

_DIVIDENDS_NUMERIC = ["amount"]

_HISTORY_COLS = {
    "date": "date",
    "total_value": "total_value",
}

_HISTORY_NUMERIC = ["total_value"]

_BENCHMARKS_COLS = {
    "period": "period",
    "twr_pct": "twr_pct",
    "mwr_pct": "mwr_pct",
    "spy_pct": "spy_pct",
    "qqq_pct": "qqq_pct",
}

_BENCHMARKS_NUMERIC = ["twr_pct", "mwr_pct", "spy_pct", "qqq_pct"]


def _cast_numeric(records: list[dict], numeric_fields: list[str]) -> list[dict]:
    """Cast string values to float for known numeric fields."""
    result = []
    for row in records:
        r = dict(row)
        for field in numeric_fields:
            if field in r:
                try:
                    # Empty/unparseable cells become 0.0 — acceptable for a personal dashboard
                    r[field] = float(str(r[field]).replace(",", "").replace("%", "").replace("$", "") or 0)
                except (ValueError, TypeError):
                    r[field] = 0.0
        result.append(r)
    return result


def _df_to_records(df: pd.DataFrame, col_map: dict, numeric_fields: list[str]) -> list[dict]:
    """Rename columns per col_map, cast numerics, return list of dicts."""
    if df.empty:
        return []
    # Keep only columns that exist in the DataFrame
    existing = {k: v for k, v in col_map.items() if k in df.columns}
    df = df[list(existing.keys())].rename(columns=existing)
    records = df.to_dict("records")
    return _cast_numeric(records, numeric_fields)


def _read_tab(sheet, tab_name: str, col_map: dict, numeric_fields: list[str]) -> list[dict]:
    """Read a worksheet tab and return cleaned records. Returns [] if tab missing."""
    try:
        ws = sheet.worksheet(tab_name)
        df = read_tab_as_df(ws)
        return _df_to_records(df, col_map, numeric_fields)
    except gspread.WorksheetNotFound:
        return []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/data")
def api_data():
    try:
        sheet = get_sheet()
    except Exception as exc:
        return jsonify({"error": "Sheets unavailable", "details": str(exc)}), 503

    try:
        # Individual Brokerage
        holdings          = _read_tab(sheet, "Holdings",          _HOLDINGS_COLS,      _HOLDINGS_NUMERIC)
        transactions      = _read_tab(sheet, "Transactions",      _TRANSACTIONS_COLS,  _TRANSACTIONS_NUMERIC)
        dividends         = _read_tab(sheet, "Dividends",         _DIVIDENDS_COLS,     _DIVIDENDS_NUMERIC)
        _live              = _compute_live_returns(sheet)
        benchmarks         = _live["brokerage"]
        ira_benchmarks     = _live["ira"]
        portfolio_history  = _live["brk_history"]
        overall_benchmarks = _live["overall"]
        analytics_rows    = _read_tab(sheet, "_Analytics",        {"metric": "metric", "value": "value"}, [])

        # Roth IRA
        ira_holdings          = _read_tab(sheet, "IRA_Holdings",          _HOLDINGS_COLS,      _HOLDINGS_NUMERIC)
        ira_transactions      = _read_tab(sheet, "IRA_Transactions",      _TRANSACTIONS_COLS,  _TRANSACTIONS_NUMERIC)
        ira_dividends         = _read_tab(sheet, "IRA_Dividends",         _DIVIDENDS_COLS,     _DIVIDENDS_NUMERIC)
        ira_portfolio_history = _live["ira_history"]
        ira_analytics_rows    = _read_tab(sheet, "_IRA_Analytics",        {"metric": "metric", "value": "value"}, [])

        # Overall (combined)
        overall_portfolio_history = _live["overall_history"]
        overall_analytics_rows    = _read_tab(sheet, "_Overall_Analytics",        {"metric": "metric", "value": "value"}, [])
    except Exception as exc:
        return jsonify({"error": "Data read error", "details": str(exc)}), 503

    analytics         = {r["metric"]: r["value"] for r in analytics_rows}
    ira_analytics     = {r["metric"]: r["value"] for r in ira_analytics_rows}
    overall_analytics = {r["metric"]: r["value"] for r in overall_analytics_rows}

    def _float(d, key):
        try: return float(d.get(key, "") or 0)
        except: return None

    # Sector lookup (24-h cached)
    all_tickers = list({h["ticker"] for h in holdings + ira_holdings})
    try:
        sectors = _fetch_sectors(all_tickers)
    except Exception:
        sectors = {}

    # Fetch today's SPY and QQQ day change % via Yahoo Finance v8 API
    # Use period1/period2 (5-day window) — more reliable than range=1d which times out.
    # Day change = last close / second-to-last close - 1.
    import time as _time, datetime as _dt
    spy_day_chg = 0.0
    qqq_day_chg = 0.0
    try:
        def _day_chg(sym):
            p2 = int(_dt.datetime.now().timestamp()) + 86400
            p1 = p2 - 8 * 86400   # 8 calendar days → guarantees ≥2 trading days
            r = _requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
                f"?interval=1d&period1={p1}&period2={p2}",
                headers=_YF_HEADERS, timeout=10,
            )
            r.raise_for_status()
            result = r.json()["chart"]["result"][0]
            # Prefer meta fields (includes pre/post market) — fall back to close series
            meta = result["meta"]
            if meta.get("regularMarketPrice") and meta.get("previousClose"):
                return round((meta["regularMarketPrice"] / meta["previousClose"] - 1) * 100, 2)
            closes = result["indicators"]["adjclose"][0]["adjclose"]
            closes = [c for c in closes if c is not None]
            if len(closes) < 2:
                return 0.0
            return round((closes[-1] / closes[-2] - 1) * 100, 2)
        spy_day_chg = _day_chg("SPY")
        _time.sleep(0.2)
        qqq_day_chg = _day_chg("QQQ")
    except Exception:
        pass

    return jsonify({
        # Individual Brokerage
        "holdings":                holdings,
        "transactions":            transactions,
        "dividends":               dividends,
        "portfolio_history":       portfolio_history,
        "benchmarks":              benchmarks,
        "first_investment_date":   analytics.get("first_investment_date", ""),
        # Roth IRA
        "ira_holdings":            ira_holdings,
        "ira_transactions":        ira_transactions,
        "ira_dividends":           ira_dividends,
        "ira_portfolio_history":   ira_portfolio_history,
        "ira_benchmarks":          ira_benchmarks,
        "ira_first_investment_date": ira_analytics.get("first_investment_date", ""),
        # Overall combined
        "overall_portfolio_history":   overall_portfolio_history,
        "overall_benchmarks":          overall_benchmarks,
        # Risk metrics per account
        "risk": {
            "brokerage": {
                "vol_1y":  _float(analytics, "vol_1y"),
                "vol_all": _float(analytics, "vol_all"),
                "beta_1y": _float(analytics, "beta_1y"),
                "beta_all":_float(analytics, "beta_all"),
            },
            "ira": {
                "vol_1y":  _float(ira_analytics, "vol_1y"),
                "vol_all": _float(ira_analytics, "vol_all"),
                "beta_1y": _float(ira_analytics, "beta_1y"),
                "beta_all":_float(ira_analytics, "beta_all"),
            },
            "overall": {
                "vol_1y":  _float(overall_analytics, "vol_1y"),
                "vol_all": _float(overall_analytics, "vol_all"),
                "beta_1y": _float(overall_analytics, "beta_1y"),
                "beta_all":_float(overall_analytics, "beta_all"),
            },
        },
        "sectors":                     sectors,
        "spy_day_chg_pct":             spy_day_chg,
        "qqq_day_chg_pct":             qqq_day_chg,
        "as_of": datetime.now(timezone.utc).isoformat(),
    })


if __name__ == "__main__":
    app.run(debug=True, port=5001)
