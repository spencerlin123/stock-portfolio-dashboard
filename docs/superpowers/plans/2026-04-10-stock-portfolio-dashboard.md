# Stock Portfolio Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Google Sheets portfolio dashboard that imports Fidelity transaction CSV exports, derives current holdings and P&L, fetches historical prices via yfinance, and displays live prices via GOOGLEFINANCE().

**Architecture:** A Python tool (`tools/import_transactions.py`) reads one or more Fidelity CSVs from `.tmp/`, parses and normalizes them, deduplicates against existing Sheets data, then writes to five tabs: Transactions, Holdings, Historical, Dividends, and Dashboard. Live current prices are handled by GOOGLEFINANCE() formulas written into the Holdings tab by the tool. Historical close prices are fetched via `yfinance`.

**Tech Stack:** Python 3, pandas, gspread, google-auth, yfinance, Google Sheets API v4

---

## File Map

| File | Responsibility |
|---|---|
| `tools/fidelity_parser.py` | Parse raw Fidelity CSV → normalized DataFrame |
| `tools/portfolio_calculator.py` | Derive Holdings (shares, avg cost basis) from Transactions |
| `tools/sheets_client.py` | Thin wrapper: authenticate, read/write named tabs |
| `tools/import_transactions.py` | Entry point: orchestrates parse → deduplicate → write |
| `tests/test_fidelity_parser.py` | Unit tests for CSV parsing logic |
| `tests/test_portfolio_calculator.py` | Unit tests for Holdings derivation logic |
| `requirements.txt` | Python dependencies |
| `workflows/update_portfolio.md` | SOP for running the import |

---

## Task 1: Project dependencies and test scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `tests/__init__.py`
- Create: `tests/test_fidelity_parser.py` (scaffold only)
- Create: `tests/test_portfolio_calculator.py` (scaffold only)

- [ ] **Step 1: Create requirements.txt**

```
pandas==2.2.3
gspread==6.1.2
google-auth==2.29.0
google-auth-oauthlib==1.2.0
yfinance==0.2.40
pytest==8.1.1
```

- [ ] **Step 2: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: all packages install without errors.

- [ ] **Step 3: Create test scaffolding**

```bash
touch tests/__init__.py tests/test_fidelity_parser.py tests/test_portfolio_calculator.py
```

- [ ] **Step 4: Verify pytest discovers tests**

```bash
pytest tests/ -v
```

Expected: `no tests ran` — 0 errors, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt tests/
git commit -m "chore: add dependencies and test scaffolding"
```

---

## Task 2: Fidelity CSV parser

**Files:**
- Create: `tools/fidelity_parser.py`
- Modify: `tests/test_fidelity_parser.py`

The Fidelity CSV format observed in the actual files:
- Columns: `Run Date, Action, Symbol, Description, Type, Price ($), Quantity, Commission ($), Fees ($), Accrued Interest ($), Amount ($), Cash Balance ($), Settlement Date`
- Some files start with a UTF-8 BOM (`\ufeff`) and/or a blank line before the header row
- `Action` is verbose: `"YOU BOUGHT TESLA INC COM (TSLA) (Cash)"` — ticker is in parens before `(Cash)`
- `Quantity` is positive for buys, negative for sells, `0.000` for dividends/transfers
- `Amount ($)` is negative for buys (cash out), positive for sells/dividends (cash in)
- Rows to **include**: actions containing `YOU BOUGHT`, `YOU SOLD`, `DIVIDEND RECEIVED`, `REINVESTMENT`
- Rows to **skip**: `Electronic Funds Transfer`, `FOREIGN TAX PAID`, `SPAXX` symbol (money market — not a real equity position; keep its dividends but exclude it from Holdings)

- [ ] **Step 1: Write failing tests**

`tests/test_fidelity_parser.py`:
```python
import pandas as pd
import pytest
from tools.fidelity_parser import parse_fidelity_csv, extract_action_type

RAW_BUY = (
    "Run Date,Action,Symbol,Description,Type,Price ($),Quantity,"
    "Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date\n"
    '10/19/2023,"YOU BOUGHT TESLA INC COM (TSLA) (Cash)",TSLA,"TESLA INC COM",'
    "Cash,219.04,15,,,,-3285.59,37.54,10/23/2023\n"
)

RAW_SELL = (
    "Run Date,Action,Symbol,Description,Type,Price ($),Quantity,"
    "Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date\n"
    '11/30/2023,"YOU SOLD GAMESTOP CORPORATION COM USD0.001 CL... (GME) (Cash)",'
    'GME,"GAMESTOP CORPORATION COM USD0.001 CLASS",Cash,14.91,-100,,0.02,,1491,1544.16,12/04/2023\n'
)

RAW_DIVIDEND = (
    "Run Date,Action,Symbol,Description,Type,Price ($),Quantity,"
    "Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date\n"
    '12/27/2024,"DIVIDEND RECEIVED META PLATFORMS INC CLASS A COMMON STOCK (META) (Cash)",'
    'META,"META PLATFORMS INC CLASS A COMMON STOCK",Cash,,0.000,,,,17.38,17.88,\n'
)

RAW_TRANSFER = (
    "Run Date,Action,Symbol,Description,Type,Price ($),Quantity,"
    "Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date\n"
    '10/20/2023,"Electronic Funds Transfer Received (Cash)", ,"No Description",Cash,,0.000,,,,3519,3556.54,\n'
)

RAW_WITH_BOM = "\ufeff\n" + RAW_BUY


def test_extract_action_type_buy():
    assert extract_action_type("YOU BOUGHT TESLA INC COM (TSLA) (Cash)") == "BUY"


def test_extract_action_type_sell():
    assert extract_action_type("YOU SOLD GAMESTOP CORPORATION (GME) (Cash)") == "SELL"


def test_extract_action_type_dividend():
    assert extract_action_type("DIVIDEND RECEIVED META PLATFORMS (META) (Cash)") == "DIVIDEND"


def test_extract_action_type_unknown():
    assert extract_action_type("Electronic Funds Transfer Received (Cash)") is None


def test_parse_buy_row(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text(RAW_BUY)
    df = parse_fidelity_csv(str(f))
    assert len(df) == 1
    row = df.iloc[0]
    assert row["ticker"] == "TSLA"
    assert row["action"] == "BUY"
    assert row["shares"] == 15.0
    assert row["price"] == 219.04
    assert row["amount"] == -3285.59
    assert str(row["date"]) == "2023-10-19"


def test_parse_sell_row(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text(RAW_SELL)
    df = parse_fidelity_csv(str(f))
    assert len(df) == 1
    row = df.iloc[0]
    assert row["ticker"] == "GME"
    assert row["action"] == "SELL"
    assert row["shares"] == -100.0


def test_parse_dividend_row(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text(RAW_DIVIDEND)
    df = parse_fidelity_csv(str(f))
    assert len(df) == 1
    row = df.iloc[0]
    assert row["action"] == "DIVIDEND"
    assert row["amount"] == 17.38


def test_transfer_rows_excluded(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text(RAW_TRANSFER)
    df = parse_fidelity_csv(str(f))
    assert len(df) == 0


def test_bom_and_blank_line_handled(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text(RAW_WITH_BOM)
    df = parse_fidelity_csv(str(f))
    assert len(df) == 1
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_fidelity_parser.py -v
```

Expected: `ModuleNotFoundError: No module named 'tools.fidelity_parser'`

- [ ] **Step 3: Implement `tools/fidelity_parser.py`**

```python
import re
import pandas as pd


# Map verbose action strings to normalized types
_ACTION_PATTERNS = {
    "BUY": r"YOU BOUGHT",
    "SELL": r"YOU SOLD",
    "DIVIDEND": r"DIVIDEND RECEIVED",
    "REINVESTMENT": r"REINVESTMENT",
}

# Tickers to exclude from Holdings (money market / cash equivalents)
_CASH_EQUIVALENTS = {"SPAXX", "FZFXX", "FDIC", "FCASH"}


def extract_action_type(action_str: str) -> str | None:
    """Return normalized action type from verbose Fidelity action string, or None to skip."""
    for action_type, pattern in _ACTION_PATTERNS.items():
        if re.search(pattern, action_str, re.IGNORECASE):
            return action_type
    return None


def parse_fidelity_csv(filepath: str) -> pd.DataFrame:
    """
    Parse a Fidelity transaction history CSV.

    Handles:
    - UTF-8 BOM at start of file
    - Blank lines before the header row
    - Verbose Action column (extracts action type)
    - Filters out transfers, foreign tax, and unknown action types

    Returns a DataFrame with columns:
        date, ticker, action, shares, price, amount, description
    """
    # Read raw text to strip BOM and find header line
    with open(filepath, encoding="utf-8-sig") as f:
        lines = f.readlines()

    # Drop blank lines before header
    lines = [l for l in lines if l.strip()]

    # Re-parse from cleaned content
    from io import StringIO
    content = "".join(lines)
    raw = pd.read_csv(StringIO(content))

    # Normalize column names: strip spaces and special chars
    raw.columns = [c.strip() for c in raw.columns]

    records = []
    for _, row in raw.iterrows():
        action_raw = str(row.get("Action", "")).strip()
        action_type = extract_action_type(action_raw)
        if action_type is None:
            continue

        ticker = str(row.get("Symbol", "")).strip()
        if not ticker:
            continue

        records.append({
            "date": pd.to_datetime(row["Run Date"], format="%m/%d/%Y").date(),
            "ticker": ticker,
            "action": action_type,
            "shares": float(row["Quantity"]) if str(row.get("Quantity", "")).strip() else 0.0,
            "price": float(row["Price ($)"]) if str(row.get("Price ($)", "")).strip() else None,
            "amount": float(row["Amount ($)"]) if str(row.get("Amount ($)", "")).strip() else 0.0,
            "description": str(row.get("Description", "")).strip(),
        })

    if not records:
        return pd.DataFrame(columns=["date", "ticker", "action", "shares", "price", "amount", "description"])

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df
```

- [ ] **Step 4: Create `tools/__init__.py`**

```bash
touch tools/__init__.py
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
pytest tests/test_fidelity_parser.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/__init__.py tools/fidelity_parser.py tests/test_fidelity_parser.py
git commit -m "feat: add Fidelity CSV parser with normalization and filtering"
```

---

## Task 3: Portfolio calculator

**Files:**
- Create: `tools/portfolio_calculator.py`
- Modify: `tests/test_portfolio_calculator.py`

Derives current open Holdings from a complete Transactions DataFrame. Uses weighted average cost basis. Excludes cash equivalents (SPAXX etc.) from Holdings. Returns separate DataFrames for Holdings and Dividends.

- [ ] **Step 1: Write failing tests**

`tests/test_portfolio_calculator.py`:
```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_portfolio_calculator.py -v
```

Expected: `ModuleNotFoundError: No module named 'tools.portfolio_calculator'`

- [ ] **Step 3: Implement `tools/portfolio_calculator.py`**

```python
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
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_portfolio_calculator.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all 15 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/portfolio_calculator.py tests/test_portfolio_calculator.py
git commit -m "feat: add portfolio calculator for holdings and dividends derivation"
```

---

## Task 4: Google Sheets client and OAuth setup

**Files:**
- Create: `tools/sheets_client.py`
- Modify: `.env` (add GOOGLE_SHEET_ID)

This task sets up Google Sheets API authentication and a thin wrapper for reading/writing tabs. OAuth credentials (`credentials.json`) must already exist — see setup note below.

**Google Cloud Setup (one-time, manual):**
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project → Enable **Google Sheets API** and **Google Drive API**
3. Create OAuth 2.0 credentials → Desktop app → Download as `credentials.json`
4. Place `credentials.json` in the project root
5. Create a new Google Sheet → copy the Sheet ID from the URL (the long string between `/d/` and `/edit`)
6. Add `GOOGLE_SHEET_ID=<your_sheet_id>` to `.env`

- [ ] **Step 1: Verify credentials.json exists**

```bash
ls credentials.json
```

Expected: file exists. If not, complete the Google Cloud Setup above first.

- [ ] **Step 2: Add GOOGLE_SHEET_ID to .env**

Edit `.env`:
```
GOOGLE_SHEET_ID=your_actual_sheet_id_here
```

- [ ] **Step 3: Implement `tools/sheets_client.py`**

```python
import os
import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
_TOKEN_PATH = "token.json"
_CREDS_PATH = "credentials.json"


def get_sheet():
    """Authenticate and return the Google Sheet specified by GOOGLE_SHEET_ID in .env."""
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise ValueError("GOOGLE_SHEET_ID not set in .env")

    creds = None
    if os.path.exists(_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(_TOKEN_PATH, _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(_CREDS_PATH, _SCOPES)
            creds = flow.run_local_server(port=0)
        with open(_TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    client = gspread.authorize(creds)
    return client.open_by_key(sheet_id)


def get_or_create_tab(sheet, tab_name: str, headers: list[str]) -> gspread.Worksheet:
    """Return existing tab or create it with the given headers in row 1."""
    try:
        ws = sheet.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=tab_name, rows=1000, cols=len(headers))
        ws.append_row(headers)
    return ws


def read_tab_as_df(ws: gspread.Worksheet):
    """Read all rows from a worksheet into a pandas DataFrame."""
    import pandas as pd
    data = ws.get_all_records()
    return pd.DataFrame(data) if data else pd.DataFrame()


def overwrite_tab(ws: gspread.Worksheet, headers: list[str], rows: list[list]):
    """Clear tab and write headers + rows."""
    ws.clear()
    ws.append_row(headers)
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
```

- [ ] **Step 4: Test authentication manually**

```bash
cd "/Users/spencerlin/Desktop/Claude Code Projects/Stock Portfolio Dashboard"
python -c "
from dotenv import load_dotenv
load_dotenv()
from tools.sheets_client import get_sheet
sheet = get_sheet()
print('Connected to:', sheet.title)
"
```

Expected: browser opens for OAuth consent → `Connected to: <your sheet name>`

Note: add `python-dotenv` to `requirements.txt` and run `pip install python-dotenv` if the above fails on `dotenv`.

- [ ] **Step 5: Update requirements.txt**

Add line:
```
python-dotenv==1.0.1
```

Run:
```bash
pip install python-dotenv
```

- [ ] **Step 6: Commit**

```bash
git add tools/sheets_client.py requirements.txt
git commit -m "feat: add Google Sheets client with OAuth authentication"
```

---

## Task 5: Main import script — Transactions tab

**Files:**
- Create: `tools/import_transactions.py`

First slice of the import script: parse all CSVs in `.tmp/`, deduplicate, and write new rows to the Transactions tab.

- [ ] **Step 1: Create `tools/import_transactions.py`**

```python
#!/usr/bin/env python3
"""
Import Fidelity transaction CSVs from .tmp/ into Google Sheets.

Usage:
    python tools/import_transactions.py

Reads all .csv files from .tmp/, deduplicates against existing Transactions
tab, and updates Holdings, Historical, and Dividends tabs.
"""
import os
import glob
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from tools.fidelity_parser import parse_fidelity_csv
from tools.portfolio_calculator import calculate_holdings, calculate_dividends
from tools.sheets_client import get_sheet, get_or_create_tab, read_tab_as_df, overwrite_tab

_TMP_DIR = ".tmp"

_TRANSACTION_HEADERS = ["date", "ticker", "action", "shares", "price", "amount", "description"]
_HOLDINGS_HEADERS = ["ticker", "shares_held", "avg_cost_basis", "total_cost_basis",
                     "current_price", "current_value", "unrealized_pnl", "unrealized_pnl_pct", "day_change_pct"]
_DIVIDENDS_HEADERS = ["date", "ticker", "amount", "type"]
_HISTORICAL_HEADERS = ["date", "ticker", "shares_held", "close_price", "position_value"]


def load_all_csvs() -> pd.DataFrame:
    """Parse all CSV files in .tmp/ and return combined DataFrame."""
    pattern = os.path.join(_TMP_DIR, "*.csv")
    files = glob.glob(pattern)
    if not files:
        raise FileNotFoundError(f"No CSV files found in {_TMP_DIR}/")
    print(f"Found {len(files)} CSV file(s)")
    frames = [parse_fidelity_csv(f) for f in files]
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates()
    combined = combined.sort_values("date").reset_index(drop=True)
    print(f"  {len(combined)} transactions parsed (after dedup within CSVs)")
    return combined


def deduplicate_against_sheet(new_df: pd.DataFrame, existing_df: pd.DataFrame) -> pd.DataFrame:
    """Return only rows in new_df not already present in existing_df."""
    if existing_df.empty:
        return new_df
    key_cols = ["date", "ticker", "action", "shares", "amount"]
    existing_df["date"] = pd.to_datetime(existing_df["date"], errors="coerce")
    new_df["date"] = pd.to_datetime(new_df["date"], errors="coerce")
    for col in ["shares", "amount"]:
        existing_df[col] = pd.to_numeric(existing_df[col], errors="coerce")
        new_df[col] = pd.to_numeric(new_df[col], errors="coerce")
    merged = new_df.merge(existing_df[key_cols].drop_duplicates(), on=key_cols, how="left", indicator=True)
    new_only = merged[merged["_merge"] == "left_only"].drop(columns=["_merge"])
    return new_only.reset_index(drop=True)


def write_transactions(ws, all_transactions: pd.DataFrame):
    """Append new transactions to the Transactions tab."""
    existing = read_tab_as_df(ws)
    new_rows = deduplicate_against_sheet(all_transactions, existing)
    if new_rows.empty:
        print("  No new transactions to add.")
        return
    print(f"  Writing {len(new_rows)} new transaction rows...")
    rows = []
    for _, r in new_rows.iterrows():
        rows.append([
            str(r["date"])[:10],
            r["ticker"],
            r["action"],
            r["shares"],
            r["price"] if pd.notna(r.get("price")) else "",
            r["amount"],
            r["description"],
        ])
    ws.append_rows(rows, value_input_option="USER_ENTERED")
    print("  Transactions tab updated.")


def write_holdings(ws, all_transactions: pd.DataFrame):
    """Recompute and overwrite Holdings tab from full transaction history."""
    holdings = calculate_holdings(all_transactions)
    print(f"  Writing {len(holdings)} holdings...")
    rows = []
    for _, r in holdings.iterrows():
        ticker = r["ticker"]
        shares = r["shares_held"]
        avg_cost = r["avg_cost_basis"]
        total_cost = r["total_cost_basis"]
        # GOOGLEFINANCE formula for live price
        price_formula = f'=GOOGLEFINANCE("{ticker}","price")'
        current_value_formula = f"={shares}*{price_formula[1:]}"  # =shares*GOOGLEFINANCE(...)
        unrealized_pnl_formula = f"=F{len(rows)+2}-{total_cost}"
        unrealized_pnl_pct_formula = f"=G{len(rows)+2}/{total_cost}"
        day_change_formula = f'=GOOGLEFINANCE("{ticker}","changepct")'
        rows.append([
            ticker,
            shares,
            avg_cost,
            total_cost,
            price_formula,
            f"={shares}*E{len(rows)+2}",
            f"=F{len(rows)+2}-{total_cost}",
            f"=G{len(rows)+2}/{total_cost}",
            day_change_formula,
        ])
    overwrite_tab(ws, _HOLDINGS_HEADERS, rows)
    print("  Holdings tab updated.")


def write_dividends(ws, all_transactions: pd.DataFrame):
    """Recompute and overwrite Dividends tab."""
    divs = calculate_dividends(all_transactions)
    print(f"  Writing {len(divs)} dividend rows...")
    rows = [[str(r["date"])[:10], r["ticker"], r["amount"], r["type"]] for _, r in divs.iterrows()]
    overwrite_tab(ws, _DIVIDENDS_HEADERS, rows)
    print("  Dividends tab updated.")


def main():
    print("=== Stock Portfolio Dashboard Import ===")
    print("\n[1/5] Parsing CSV files...")
    all_txns = load_all_csvs()

    print("\n[2/5] Connecting to Google Sheets...")
    sheet = get_sheet()

    print("\n[3/5] Updating Transactions tab...")
    txn_ws = get_or_create_tab(sheet, "Transactions", _TRANSACTION_HEADERS)
    write_transactions(txn_ws, all_txns)

    # Re-read full transactions (existing + new) for calculations
    print("\n[4/5] Recomputing Holdings and Dividends...")
    all_txns_in_sheet = read_tab_as_df(txn_ws)
    all_txns_in_sheet["date"] = pd.to_datetime(all_txns_in_sheet["date"], errors="coerce")
    for col in ["shares", "price", "amount"]:
        all_txns_in_sheet[col] = pd.to_numeric(all_txns_in_sheet[col], errors="coerce")

    holdings_ws = get_or_create_tab(sheet, "Holdings", _HOLDINGS_HEADERS)
    write_holdings(holdings_ws, all_txns_in_sheet)

    divs_ws = get_or_create_tab(sheet, "Dividends", _DIVIDENDS_HEADERS)
    write_dividends(divs_ws, all_txns_in_sheet)

    print("\n[5/5] Done. Open your Google Sheet to see the results.")
    print(f"  Sheet: https://docs.google.com/spreadsheets/d/{os.environ['GOOGLE_SHEET_ID']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run against real data (dry run first)**

```bash
cd "/Users/spencerlin/Desktop/Claude Code Projects/Stock Portfolio Dashboard"
python -c "
from dotenv import load_dotenv; load_dotenv()
from tools.fidelity_parser import parse_fidelity_csv
import glob, pandas as pd
files = glob.glob('.tmp/*.csv')
frames = [parse_fidelity_csv(f) for f in files]
df = pd.concat(frames).drop_duplicates().sort_values('date')
print(df.shape)
print(df['action'].value_counts())
print(df['ticker'].value_counts().head(10))
"
```

Expected: prints row counts and action/ticker breakdowns — no errors.

- [ ] **Step 3: Run full import**

```bash
python tools/import_transactions.py
```

Expected output:
```
=== Stock Portfolio Dashboard Import ===
[1/5] Parsing CSV files...
Found 4 CSV file(s)
  NNN transactions parsed (after dedup within CSVs)
[2/5] Connecting to Google Sheets...
[3/5] Updating Transactions tab...
  Writing NNN new transaction rows...
  Transactions tab updated.
[4/5] Recomputing Holdings and Dividends...
  Writing N holdings...
  Holdings tab updated.
  Writing N dividend rows...
  Dividends tab updated.
[5/5] Done.
```

Open the Sheet and verify:
- Transactions tab has rows with correct dates, tickers, actions
- Holdings tab has current positions with GOOGLEFINANCE() formulas showing live prices
- Dividends tab has dividend rows

- [ ] **Step 4: Commit**

```bash
git add tools/import_transactions.py
git commit -m "feat: add main import script for transactions, holdings, and dividends"
```

---

## Task 6: Historical tab — portfolio value over time

**Files:**
- Modify: `tools/import_transactions.py` (add `write_historical` function)

Uses `yfinance` to fetch historical close prices for each ticker from first transaction date to today, then builds a per-day portfolio value timeline.

- [ ] **Step 1: Add `write_historical` to `tools/import_transactions.py`**

Add this function before `main()`:

```python
def write_historical(ws, all_transactions: pd.DataFrame):
    """
    Build portfolio value over time using yfinance historical close prices.
    Skips dates already present in the Historical tab.
    """
    import yfinance as yf

    buys_sells = all_transactions[all_transactions["action"].isin(["BUY", "SELL"])].copy()
    if buys_sells.empty:
        print("  No buy/sell transactions — skipping Historical tab.")
        return

    # Existing dates already written
    existing = read_tab_as_df(ws)
    existing_dates = set(existing["date"].astype(str).tolist()) if not existing.empty else set()

    start_date = buys_sells["date"].min().date()
    end_date = pd.Timestamp.today().date()
    all_dates = pd.date_range(start=start_date, end=end_date, freq="B")  # Business days only

    tickers = [t for t in buys_sells["ticker"].unique() if t not in _CASH_EQUIVALENTS]
    if not tickers:
        return

    print(f"  Fetching historical prices for {len(tickers)} tickers via yfinance...")
    price_data = yf.download(tickers, start=str(start_date), end=str(end_date), auto_adjust=True, progress=False)

    # yfinance returns MultiIndex if multiple tickers, single-level if one
    if len(tickers) == 1:
        close_prices = price_data[["Close"]].rename(columns={"Close": tickers[0]})
    else:
        close_prices = price_data["Close"]

    rows = []
    # Compute cumulative shares held per ticker per day
    for date in all_dates:
        date_str = str(date.date())
        if date_str in existing_dates:
            continue
        txns_to_date = buys_sells[buys_sells["date"] <= date]
        for ticker in tickers:
            ticker_txns = txns_to_date[txns_to_date["ticker"] == ticker]
            if ticker_txns.empty:
                continue
            buys = ticker_txns[ticker_txns["action"] == "BUY"]["shares"].sum()
            sells = abs(ticker_txns[ticker_txns["action"] == "SELL"]["shares"].sum())
            shares = round(buys - sells, 6)
            if shares <= 0:
                continue
            # Get close price
            if ticker not in close_prices.columns:
                continue
            price_series = close_prices[ticker]
            try:
                close = price_series.asof(date)
                if pd.isna(close):
                    continue
            except Exception:
                continue
            rows.append([
                date_str,
                ticker,
                shares,
                round(float(close), 4),
                round(shares * float(close), 2),
            ])

    if rows:
        print(f"  Writing {len(rows)} historical rows...")
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    else:
        print("  Historical tab already up to date.")
    print("  Historical tab updated.")
```

- [ ] **Step 2: Wire `write_historical` into `main()`**

Replace the `[4/5]` section in `main()` with:

```python
    print("\n[4/5] Recomputing Holdings, Historical, and Dividends...")
    all_txns_in_sheet = read_tab_as_df(txn_ws)
    all_txns_in_sheet["date"] = pd.to_datetime(all_txns_in_sheet["date"], errors="coerce")
    for col in ["shares", "price", "amount"]:
        all_txns_in_sheet[col] = pd.to_numeric(all_txns_in_sheet[col], errors="coerce")

    holdings_ws = get_or_create_tab(sheet, "Holdings", _HOLDINGS_HEADERS)
    write_holdings(holdings_ws, all_txns_in_sheet)

    hist_ws = get_or_create_tab(sheet, "Historical", _HISTORICAL_HEADERS)
    write_historical(hist_ws, all_txns_in_sheet)

    divs_ws = get_or_create_tab(sheet, "Dividends", _DIVIDENDS_HEADERS)
    write_dividends(divs_ws, all_txns_in_sheet)
```

- [ ] **Step 3: Run import and verify Historical tab**

```bash
python tools/import_transactions.py
```

Expected: Historical tab populates with daily rows per ticker. Note: this will take ~30-60 seconds on first run (yfinance fetching 2+ years of data).

Open the Sheet → Historical tab should have rows with date, ticker, shares, close price, and position value.

- [ ] **Step 4: Commit**

```bash
git add tools/import_transactions.py
git commit -m "feat: add historical portfolio value tab via yfinance"
```

---

## Task 7: Dashboard tab with summary formulas

**Files:**
- Modify: `tools/import_transactions.py` (add `write_dashboard` function)

Writes summary statistics and chart-ready data to a Dashboard tab using Google Sheets formulas that reference the other tabs.

- [ ] **Step 1: Add `write_dashboard` to `tools/import_transactions.py`**

Add after `write_dividends`:

```python
_DASHBOARD_HEADERS = ["metric", "value"]

def write_dashboard(ws):
    """Write summary metrics to Dashboard tab using cross-tab formulas."""
    rows = [
        ["Total Portfolio Value", "=SUM(Holdings!F:F)"],
        ["Total Cost Basis", "=SUM(Holdings!D:D)"],
        ["Total Unrealized P&L ($)", "=SUM(Holdings!G:G)"],
        ["Total Unrealized P&L (%)", "=B3/B2"],
        ["Total Dividend Income", "=SUM(Dividends!C:C)"],
        ["Number of Positions", '=COUNTA(Holdings!A:A)-1'],
    ]
    overwrite_tab(ws, _DASHBOARD_HEADERS, rows)
    print("  Dashboard tab updated.")
```

- [ ] **Step 2: Wire `write_dashboard` into `main()`**

Add to the end of the `[4/5]` section in `main()`:

```python
    dashboard_ws = get_or_create_tab(sheet, "Dashboard", _DASHBOARD_HEADERS)
    write_dashboard(dashboard_ws)
```

- [ ] **Step 3: Run import and verify Dashboard**

```bash
python tools/import_transactions.py
```

Open the Sheet → Dashboard tab should show total portfolio value, cost basis, unrealized P&L, dividend income, and position count — all updating live as GOOGLEFINANCE() refreshes.

- [ ] **Step 4: Commit**

```bash
git add tools/import_transactions.py
git commit -m "feat: add Dashboard tab with summary metrics and formula references"
```

---

## Task 8: Update workflow doc

**Files:**
- Create: `workflows/update_portfolio.md`

- [ ] **Step 1: Write workflow**

`workflows/update_portfolio.md`:
```markdown
# Update Portfolio Dashboard

## Objective
Import new Fidelity transactions into the Google Sheets dashboard so all tabs reflect the latest data.

## Required Inputs
- Fidelity transaction history CSV (downloaded from Fidelity)

## Steps

### 1. Download transaction CSV from Fidelity
1. Log into fidelity.com
2. Go to **Accounts & Trade → Transaction History**
3. Select your account
4. Set the date range: set start date to the day after your last import (or use a broad range — the script deduplicates)
5. Click **Download** → select **CSV** format
6. Save the file to `.tmp/` in this project directory

### 2. Run the import script
```bash
cd "/Users/spencerlin/Desktop/Claude Code Projects/Stock Portfolio Dashboard"
python tools/import_transactions.py
```

### 3. Verify the output
- Transactions tab: new rows appended at the bottom
- Holdings tab: shares and cost basis reflect current positions
- Historical tab: new daily rows added up to today
- Dividends tab: new dividend rows appended
- Dashboard tab: totals updated

## Notes
- It is safe to re-run the script multiple times — it deduplicates by (date, ticker, action, shares, amount)
- The Historical tab fetch (yfinance) is slow on first run (~30-60 seconds) but fast on subsequent runs since it only fetches new dates
- If you see a `GOOGLEFINANCE` error for a ticker, it may be delisted or have changed symbol
- SPAXX (Fidelity money market) dividends appear in the Dividends tab but SPAXX is excluded from Holdings
```

- [ ] **Step 2: Commit**

```bash
git add workflows/update_portfolio.md
git commit -m "docs: add update_portfolio workflow SOP"
```

---

## Self-Review Notes

- **Spec coverage:**
  - ✅ Google Sheets as dashboard
  - ✅ GOOGLEFINANCE() for live prices (Holdings tab)
  - ✅ Fidelity CSV import via Python tool
  - ✅ Deduplication on re-run
  - ✅ Transactions tab
  - ✅ Holdings tab with unrealized P&L
  - ✅ Historical tab (portfolio value over time)
  - ✅ Dividends tab
  - ✅ Dashboard summary tab
  - ✅ yfinance for historical close prices
  - ✅ Workflow SOP
  - ✅ SPAXX excluded from holdings

- **Data flow clarification:** `write_holdings` uses GOOGLEFINANCE() formulas in column E (current_price) and derives columns F–H from it. Row index references in formula strings are computed as `len(rows)+2` to account for the header row.

- **SPAXX handling:** SPAXX dividends are kept in the Dividends tab (they represent real income). SPAXX is excluded from Holdings since it is a money market fund, not an equity position.
