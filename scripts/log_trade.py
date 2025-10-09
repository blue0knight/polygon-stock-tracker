#!/usr/bin/env python3
"""
Quick trade logging script for manual entry/exit recording.

Usage:
  # Log entry (no exit yet)
  python scripts/log_trade.py RELI 1.05 --shares 100 --notes "Scanner pick - good timing"

  # Log exit (update existing entry)
  python scripts/log_trade.py RELI 1.05 1.25 --shares 100 --notes "Sold at resistance"

  # Log complete trade (entry + exit)
  python scripts/log_trade.py TSHA 4.68 4.75 --shares 50 --notes "Late entry, quick scalp"
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.journal import record_trade

JOURNAL_PATH = ROOT / "output" / "journal.csv"

def main():
    parser = argparse.ArgumentParser(description="Log a trade to journal.csv")
    parser.add_argument("ticker", help="Stock ticker symbol")
    parser.add_argument("entry", type=float, help="Entry price")
    parser.add_argument("exit", type=float, nargs="?", default=None, help="Exit price (optional)")
    parser.add_argument("--shares", type=int, default=100, help="Number of shares (default: 100)")
    parser.add_argument("--date", help="Trade date (YYYY-MM-DD, default: today)")
    parser.add_argument("--notes", default="", help="Trade notes")
    parser.add_argument("--plan", default="Scanner pick", help="Trade plan (default: Scanner pick)")

    args = parser.parse_args()

    # If no exit price, this is an open position - use entry price as placeholder
    exit_price = args.exit if args.exit else args.entry

    record_trade(
        str(JOURNAL_PATH),
        ticker=args.ticker,
        side="long",
        entry_price=args.entry,
        exit_price=exit_price,
        shares=args.shares,
        date=args.date,
        plan=args.plan,
        notes=args.notes
    )

    if args.exit:
        pl_pct = ((exit_price - args.entry) / args.entry) * 100
        pl_dollar = (exit_price - args.entry) * args.shares
        print(f"✅ Trade logged: {args.ticker} @ ${args.entry} → ${exit_price} ({pl_pct:+.2f}%, ${pl_dollar:+.2f})")
    else:
        print(f"📝 Position logged: {args.ticker} @ ${args.entry} ({args.shares} shares) - OPEN")

    print(f"📊 Journal: {JOURNAL_PATH}")

if __name__ == "__main__":
    main()
