#!/usr/bin/env python3
"""
Manual Pick Override - Select alternative when automated pick is not tradeable

Usage:
  # See today's candidates
  python scripts/manual_pick.py --show

  # Override pick with alternative (e.g., if SPRB not tradeable, pick SOPA)
  python scripts/manual_pick.py SOPA

This will update today_pick.csv with your manual selection.
"""

import sys
import csv
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TODAY_PICK_CSV = ROOT / "output" / "today_pick.csv"

def show_picks():
    """Show current picks from today_pick.csv"""
    if not TODAY_PICK_CSV.exists():
        print("❌ No picks file found at:", TODAY_PICK_CSV)
        return

    with open(TODAY_PICK_CSV, 'r') as f:
        reader = csv.DictReader(f)
        picks = list(reader)

    if not picks:
        print("📋 No picks recorded yet")
        return

    print("📊 Today's Picks:")
    for i, pick in enumerate(picks, 1):
        ticker = pick.get('ticker', 'N/A')
        gap = pick.get('gap_pct', 'N/A')
        score = pick.get('score', 'N/A')
        final = pick.get('final_pick', 'FALSE')
        flag = "✅ FINAL" if final == "TRUE" else ""
        print(f"  {i}. {ticker} - gap={gap}%, score={score} {flag}")

def override_pick(ticker: str):
    """Override the pick with manual selection"""
    ticker = ticker.upper()

    print(f"🔄 Manually overriding pick to: {ticker}")
    print(f"⚠️  Note: This creates a placeholder entry. Add details manually or wait for next scan.")

    # Create manual entry
    row = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'time': datetime.now().strftime('%H:%M'),
        'ticker': ticker,
        'gap_pct': '',
        'rvol': '',
        'atr_stretch': '',
        'premarket_high': '',
        'open_price': '',
        'score': '',
        'final_pick': 'TRUE',
        'rationale': f'Manual override - automated pick not tradeable'
    }

    # Append to CSV
    with open(TODAY_PICK_CSV, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        writer.writerow(row)

    print(f"✅ Pick updated: {ticker}")
    print(f"📊 File: {TODAY_PICK_CSV}")

def main():
    if len(sys.argv) == 1 or '--show' in sys.argv:
        show_picks()
    elif len(sys.argv) == 2:
        ticker = sys.argv[1]
        if ticker.startswith('--'):
            print("Usage: python scripts/manual_pick.py [TICKER]")
            print("       python scripts/manual_pick.py --show")
        else:
            override_pick(ticker)
    else:
        print("Usage: python scripts/manual_pick.py [TICKER]")

if __name__ == "__main__":
    main()
