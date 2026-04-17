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
- Holdings tab: shares and cost basis reflect current positions with live GOOGLEFINANCE prices
- Historical tab: new daily rows added up to today
- Dividends tab: new dividend rows appended
- Dashboard tab: summary totals updated

## Notes
- It is safe to re-run the script multiple times — it deduplicates by (date, ticker, action, shares, amount)
- The Historical tab fetch (yfinance) is slow on first run (~30-60 seconds) but fast on subsequent runs since it only fetches new dates
- If you see a GOOGLEFINANCE error for a ticker, it may be delisted or have changed symbol
- SPAXX (Fidelity money market) dividends appear in the Dividends tab but SPAXX is excluded from Holdings
- yfinance version must be 1.x or higher (requirements.txt pins 0.2.40 but the script upgraded to 1.2.1 during setup — run `pip install yfinance --upgrade` if you see yfinance errors)
