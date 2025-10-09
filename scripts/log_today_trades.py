#!/usr/bin/env python3
"""
Quick Trade Logger
Simplified interface to log today's trades to journal.csv
"""

import csv
import os
from datetime import date

JOURNAL_CSV = "output/journal.csv"


def log_trade(ticker: str, entry: float, exit_price: float, shares: int, notes: str = ""):
    """Log a completed trade to journal.csv"""

    # Calculate P/L
    total_cost = entry * shares
    pl_dollar = (exit_price - entry) * shares
    pl_percent = ((exit_price - entry) / entry) * 100

    # Prepare row
    trade_row = {
        'date': date.today().strftime('%Y-%m-%d'),
        'ticker': ticker.upper(),
        'side': 'long',
        'entry_price': f"{entry:.2f}",
        'exit_price': f"{exit_price:.2f}",
        'shares': shares,
        'total_cost': f"{total_cost:.2f}",
        'pl_dollar': f"{pl_dollar:.2f}",
        'pl_percent': f"{pl_percent:.2f}",
        'plan': notes,
        'actual': '',
        'notes': f"EOD logged - {date.today()}"
    }

    # Check if file exists
    file_exists = os.path.isfile(JOURNAL_CSV)

    # Append to journal
    with open(JOURNAL_CSV, 'a', newline='') as f:
        fieldnames = [
            'date', 'ticker', 'side', 'entry_price', 'exit_price', 'shares',
            'total_cost', 'pl_dollar', 'pl_percent', 'plan', 'actual', 'notes'
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        writer.writerow(trade_row)

    print(f"✅ Logged: {ticker} - Entry: ${entry:.2f} → Exit: ${exit_price:.2f} = {pl_percent:+.1f}% (${pl_dollar:+.2f})")


def main():
    print("="*60)
    print("📝 QUICK TRADE LOGGER")
    print("="*60)
    print()

    trades = []

    while True:
        print(f"\nTrade #{len(trades) + 1}")
        ticker = input("Ticker (or 'done' to finish): ").strip().upper()

        if ticker.lower() == 'done':
            break

        if not ticker:
            continue

        try:
            entry = float(input(f"Entry price for {ticker}: $"))
            exit_price = float(input(f"Exit price for {ticker}: $"))
            shares = int(input(f"Shares: "))
            notes = input("Notes (optional): ").strip()

            trades.append({
                'ticker': ticker,
                'entry': entry,
                'exit': exit_price,
                'shares': shares,
                'notes': notes
            })

            # Calculate preview
            pl_pct = ((exit_price - entry) / entry) * 100
            pl_dollar = (exit_price - entry) * shares

            print(f"   Preview: {ticker} ${entry:.2f} → ${exit_price:.2f} = {pl_pct:+.1f}% (${pl_dollar:+.2f})")

        except ValueError:
            print("❌ Invalid input. Try again.")
            continue

    if not trades:
        print("\nNo trades to log. Exiting.")
        return

    print("\n" + "="*60)
    print(f"📊 SUMMARY - {len(trades)} trade(s) to log")
    print("="*60)

    total_pl = 0
    for i, trade in enumerate(trades, 1):
        pl_dollar = (trade['exit'] - trade['entry']) * trade['shares']
        pl_pct = ((trade['exit'] - trade['entry']) / trade['entry']) * 100
        total_pl += pl_dollar

        print(f"{i}. {trade['ticker']}: ${trade['entry']:.2f} → ${trade['exit']:.2f} × {trade['shares']} shares = {pl_pct:+.1f}% (${pl_dollar:+.2f})")

    print(f"\nTotal P/L: ${total_pl:+.2f}")

    confirm = input("\nSave to journal? (y/n): ").strip().lower()

    if confirm == 'y':
        for trade in trades:
            log_trade(
                ticker=trade['ticker'],
                entry=trade['entry'],
                exit_price=trade['exit'],
                shares=trade['shares'],
                notes=trade['notes']
            )

        print(f"\n✅ {len(trades)} trade(s) saved to {JOURNAL_CSV}")
        print("\nRun EOD analysis to see how you did:")
        print("  python3 scripts/analyze_eod.py")
    else:
        print("\n❌ Cancelled. No trades saved.")


if __name__ == "__main__":
    main()
