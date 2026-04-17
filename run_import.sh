#!/bin/bash
# Wrapper for launchd — runs the portfolio import script daily at market close.
# Logs go to .tmp/import.log (last 500 lines kept to avoid unbounded growth).

PROJECT="/Users/spencerlin/Desktop/Claude Code Projects/Stock Portfolio Dashboard"
PYTHON="/usr/local/bin/python3.10"
LOG="$PROJECT/.tmp/import.log"

cd "$PROJECT" || exit 1

echo "--- $(date) ---" >> "$LOG"
"$PYTHON" tools/import_transactions.py >> "$LOG" 2>&1

# Keep log file from growing unbounded
tail -500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
