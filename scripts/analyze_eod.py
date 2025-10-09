#!/usr/bin/env python3
"""
End-of-Day Scanner Analysis
Analyzes today's scanner log to identify the best stock picks we could have made.
Outputs a daily report with:
- Top movers (>8% gain)
- Entry/exit timing
- Missed opportunities
"""

import os
import re
import csv
from datetime import datetime, date
from collections import defaultdict
from typing import List, Dict, Tuple, Optional

# Paths
LOG_DIR = "logs"
OUTPUT_DIR = "output"
MISSED_CSV = os.path.join(OUTPUT_DIR, "missed.csv")
JOURNAL_CSV = os.path.join(OUTPUT_DIR, "journal.csv")

# Thresholds
MIN_GAIN_PCT = 8.0  # Minimum gain % to be considered
MIN_VOLUME = 1_000_000  # Minimum volume to avoid illiquid stocks


class StockAppearance:
    """Represents a single appearance of a stock in the scanner log"""
    def __init__(self, ticker: str, timestamp: str, price: float, change_pct: float,
                 volume: float, score: float):
        self.ticker = ticker
        self.timestamp = timestamp
        self.time = self._parse_time(timestamp)
        self.price = price
        self.change_pct = change_pct
        self.volume = volume
        self.score = score

    def _parse_time(self, timestamp: str) -> datetime:
        """Parse timestamp from log line"""
        # Format: 2025-10-08 15:36:22,193
        try:
            return datetime.strptime(timestamp[:19], "%Y-%m-%d %H:%M:%S")
        except:
            return datetime.now()


class StockTrajectory:
    """Tracks the full trajectory of a stock throughout the day"""
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.appearances: List[StockAppearance] = []
        self.first_price: Optional[float] = None
        self.first_time: Optional[datetime] = None
        self.peak_price: float = 0.0
        self.peak_time: Optional[datetime] = None
        self.last_price: Optional[float] = None
        self.last_time: Optional[datetime] = None
        self.max_volume: float = 0.0
        self.open_price: Optional[float] = None

    def add_appearance(self, appearance: StockAppearance):
        """Add a new appearance to the trajectory"""
        self.appearances.append(appearance)

        # Track first appearance
        if self.first_price is None:
            self.first_price = appearance.price
            self.first_time = appearance.time

        # Track peak
        if appearance.price > self.peak_price:
            self.peak_price = appearance.price
            self.peak_time = appearance.time

        # Track last
        self.last_price = appearance.price
        self.last_time = appearance.time

        # Track max volume
        if appearance.volume > self.max_volume:
            self.max_volume = appearance.volume

    def extract_open_price(self):
        """Try to extract the open price from appearances"""
        # Look for the first appearance that mentions an open price
        for app in self.appearances:
            if hasattr(app, 'open_price') and app.open_price:
                self.open_price = app.open_price
                return
        # Fallback: use first price as open
        self.open_price = self.first_price

    def calculate_gain(self) -> float:
        """Calculate % gain from first appearance to peak"""
        if not self.first_price or self.first_price == 0:
            return 0.0
        return ((self.peak_price - self.first_price) / self.first_price) * 100

    def calculate_open_to_peak_gain(self) -> float:
        """Calculate % gain from open to peak"""
        if not self.open_price or self.open_price == 0:
            return self.calculate_gain()
        return ((self.peak_price - self.open_price) / self.open_price) * 100

    def is_catchable(self) -> bool:
        """Determine if this stock was realistically catchable"""
        # Must have appeared before 2 PM
        if self.first_time and self.first_time.hour >= 14:
            return False

        # Must have sufficient volume
        if self.max_volume < MIN_VOLUME:
            return False

        # Peak must be at least 30 min after first appearance
        if self.first_time and self.peak_time:
            time_diff = (self.peak_time - self.first_time).total_seconds() / 60
            if time_diff < 5:  # Less than 5 min to catch
                return False

        return True

    def get_entry_window(self) -> Tuple[str, str, float, float]:
        """Get optimal entry window (time range and price range)"""
        if not self.first_time:
            return ("N/A", "N/A", 0.0, 0.0)

        # Entry window: first 10 appearances or first 30 minutes
        entry_apps = []
        cutoff_time = self.first_time.timestamp() + (30 * 60)  # 30 min

        for app in self.appearances[:10]:
            if app.time.timestamp() <= cutoff_time:
                entry_apps.append(app)

        if not entry_apps:
            entry_apps = [self.appearances[0]]

        start_time = entry_apps[0].time.strftime("%H:%M")
        end_time = entry_apps[-1].time.strftime("%H:%M")
        min_price = min(app.price for app in entry_apps)
        max_price = max(app.price for app in entry_apps)

        return (start_time, end_time, min_price, max_price)

    def get_exit_window(self) -> Tuple[str, str, float, float]:
        """Get optimal exit window (near peak)"""
        if not self.peak_time or not self.peak_price:
            return ("N/A", "N/A", 0.0, 0.0)

        # Exit window: +/- 2% of peak price
        peak_threshold = self.peak_price * 0.98
        exit_apps = [app for app in self.appearances if app.price >= peak_threshold]

        if not exit_apps:
            return (self.peak_time.strftime("%H:%M"), self.peak_time.strftime("%H:%M"),
                    self.peak_price, self.peak_price)

        start_time = exit_apps[0].time.strftime("%H:%M")
        end_time = exit_apps[-1].time.strftime("%H:%M")
        min_price = min(app.price for app in exit_apps)
        max_price = max(app.price for app in exit_apps)

        return (start_time, end_time, min_price, max_price)


def parse_scanner_log(log_path: str) -> Dict[str, StockTrajectory]:
    """Parse scanner log and extract stock trajectories"""
    trajectories = defaultdict(lambda: StockTrajectory(""))

    # Regex patterns for different log formats
    # Pattern 1: Top 5 logs with scores
    # Example: 2025-10-08 15:36:22,193 [INFO]    SNAP: score=149.9 chg=+2.4% last=8.38 open=8.18 vol=104.9M [active_30min_window]
    pattern1 = re.compile(
        r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}).*?'
        r'(\w+):\s+score=([\d.]+)\s+chg=([+-]?[\d.]+)%\s+last=([\d.]+)\s+(?:open=([\d.]+)\s+)?vol=([\d.]+)([KM])?'
    )

    # Pattern 2: Group Watchlist logs
    # Example: 2025-10-08 15:36:21,707 [INFO]    UPC: chg=+3.9% last=8.08 open=7.78 vol=22.3M
    pattern2 = re.compile(
        r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}).*?'
        r'(\w+):\s+chg=([+-]?[\d.]+)%\s+last=([\d.]+)\s+(?:open=([\d.]+)\s+)?vol=([\d.]+)([KM])?'
    )

    with open(log_path, 'r') as f:
        for line in f:
            # Try pattern 1 (with score)
            match = pattern1.search(line)
            if match:
                timestamp = match.group(1)
                ticker = match.group(2)
                score = float(match.group(3))
                change_pct = float(match.group(4))
                price = float(match.group(5))
                open_price = float(match.group(6)) if match.group(6) else None
                volume_num = float(match.group(7))
                volume_unit = match.group(8) if match.group(8) else ""

                volume = volume_num * 1_000_000 if volume_unit == "M" else volume_num * 1_000

                appearance = StockAppearance(ticker, timestamp, price, change_pct, volume, score)
                if open_price:
                    appearance.open_price = open_price

                if ticker not in trajectories:
                    trajectories[ticker] = StockTrajectory(ticker)
                trajectories[ticker].add_appearance(appearance)
                continue

            # Try pattern 2 (without score)
            match = pattern2.search(line)
            if match:
                timestamp = match.group(1)
                ticker = match.group(2)
                change_pct = float(match.group(3))
                price = float(match.group(4))
                open_price = float(match.group(5)) if match.group(5) else None
                volume_num = float(match.group(6))
                volume_unit = match.group(7) if match.group(7) else ""

                volume = volume_num * 1_000_000 if volume_unit == "M" else volume_num * 1_000

                appearance = StockAppearance(ticker, timestamp, price, change_pct, volume, 0.0)
                if open_price:
                    appearance.open_price = open_price

                if ticker not in trajectories:
                    trajectories[ticker] = StockTrajectory(ticker)
                trajectories[ticker].add_appearance(appearance)

    # Extract open prices
    for traj in trajectories.values():
        traj.extract_open_price()

    return trajectories


def identify_best_picks(trajectories: Dict[str, StockTrajectory]) -> List[StockTrajectory]:
    """Identify the best catchable picks from trajectories"""
    candidates = []

    for traj in trajectories.values():
        gain = traj.calculate_open_to_peak_gain()

        # Filter criteria
        if gain >= MIN_GAIN_PCT and traj.is_catchable():
            candidates.append(traj)

    # Sort by gain (descending)
    candidates.sort(key=lambda t: t.calculate_open_to_peak_gain(), reverse=True)

    return candidates


def write_daily_report(report_date: date, best_picks: List[StockTrajectory]):
    """Write daily EOD report to console and markdown file"""
    # Create reports subdirectory if it doesn't exist
    reports_dir = os.path.join(OUTPUT_DIR, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    report_path = os.path.join(reports_dir, f"eod_report_{report_date}.md")

    lines = []
    lines.append(f"# End-of-Day Analysis - {report_date}")
    lines.append("")
    lines.append(f"**Analysis Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Minimum Gain Threshold:** {MIN_GAIN_PCT}%")
    lines.append("")

    if not best_picks:
        lines.append("**No catchable opportunities found today** (min gain: {}%)".format(MIN_GAIN_PCT))
        print("No catchable opportunities found today.")
    else:
        lines.append(f"## Top {min(len(best_picks), 5)} Catchable Picks")
        lines.append("")

        for i, traj in enumerate(best_picks[:5], 1):
            gain = traj.calculate_open_to_peak_gain()
            entry_start, entry_end, entry_min, entry_max = traj.get_entry_window()
            exit_start, exit_end, exit_min, exit_max = traj.get_exit_window()

            lines.append(f"### #{i}: {traj.ticker} (+{gain:.1f}%)")
            lines.append("")
            lines.append(f"**Performance:**")
            lines.append(f"- Open: ${traj.open_price:.2f}")
            lines.append(f"- First Seen: {traj.first_time.strftime('%H:%M')} @ ${traj.first_price:.2f}")
            lines.append(f"- Peak: {traj.peak_time.strftime('%H:%M')} @ ${traj.peak_price:.2f}")
            lines.append(f"- Max Gain: **+{gain:.1f}%**")
            lines.append(f"- Volume: {traj.max_volume / 1_000_000:.1f}M")
            lines.append("")
            lines.append(f"**Entry Window:**")
            lines.append(f"- Time: {entry_start} - {entry_end}")
            lines.append(f"- Price Range: ${entry_min:.2f} - ${entry_max:.2f}")
            lines.append("")
            lines.append(f"**Exit Window:**")
            lines.append(f"- Time: {exit_start} - {exit_end}")
            lines.append(f"- Price Range: ${exit_min:.2f} - ${exit_max:.2f}")
            lines.append("")

            # Console output
            print(f"#{i}: {traj.ticker} (+{gain:.1f}%)")
            print(f"   Entry: {entry_start}-{entry_end} @ ${entry_min:.2f}-${entry_max:.2f}")
            print(f"   Exit:  {exit_start}-{exit_end} @ ${exit_min:.2f}-${exit_max:.2f}")
            print()

    # Write markdown report
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(report_path, 'w') as f:
        f.write("\n".join(lines))

    print(f"Report saved: {report_path}")


def append_to_missed_csv(report_date: date, best_picks: List[StockTrajectory]):
    """Append missed opportunities to missed.csv"""
    if not best_picks:
        return

    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Check if file exists, create with headers if not
    file_exists = os.path.isfile(MISSED_CSV)

    with open(MISSED_CSV, 'a', newline='') as f:
        fieldnames = [
            'date', 'ticker', 'open_price', 'first_seen_time', 'first_seen_price',
            'peak_time', 'peak_price', 'gain_pct', 'volume_m',
            'entry_window', 'exit_window', 'notes'
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        for traj in best_picks[:5]:  # Top 5 only
            gain = traj.calculate_open_to_peak_gain()
            entry_start, entry_end, entry_min, entry_max = traj.get_entry_window()
            exit_start, exit_end, exit_min, exit_max = traj.get_exit_window()

            writer.writerow({
                'date': report_date.strftime('%Y-%m-%d'),
                'ticker': traj.ticker,
                'open_price': f"{traj.open_price:.2f}" if traj.open_price else "",
                'first_seen_time': traj.first_time.strftime('%H:%M') if traj.first_time else "",
                'first_seen_price': f"{traj.first_price:.2f}" if traj.first_price else "",
                'peak_time': traj.peak_time.strftime('%H:%M') if traj.peak_time else "",
                'peak_price': f"{traj.peak_price:.2f}",
                'gain_pct': f"{gain:.1f}",
                'volume_m': f"{traj.max_volume / 1_000_000:.1f}",
                'entry_window': f"{entry_start}-{entry_end} @ ${entry_min:.2f}-${entry_max:.2f}",
                'exit_window': f"{exit_start}-{exit_end} @ ${exit_min:.2f}-${exit_max:.2f}",
                'notes': f"EOD Analysis - Best pick #{best_picks.index(traj) + 1}"
            })

    print(f"Appended {len(best_picks[:5])} missed opportunities to {MISSED_CSV}")


def load_journal_trades(report_date: date) -> List[Dict]:
    """Load trades from journal.csv for the given date"""
    trades = []

    if not os.path.isfile(JOURNAL_CSV):
        return trades

    with open(JOURNAL_CSV, 'r', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                trade_date = datetime.strptime(row['date'], '%Y-%m-%d').date()
                if trade_date == report_date:
                    trades.append(row)
            except:
                continue

    return trades


def compare_with_journal(report_date: date, best_picks: List[StockTrajectory], trades: List[Dict]):
    """Compare EOD best picks with actual journal trades"""
    if not trades:
        print("\n📝 No trades logged in journal for today")
        print(f"   To log trades: python scripts/log_trade.py TICKER ENTRY EXIT --shares N")
        return

    print("\n" + "="*60)
    print(f"📊 TRADING PERFORMANCE vs BEST PICKS ({report_date})")
    print("="*60)

    # Get best pick tickers
    best_tickers = {traj.ticker for traj in best_picks[:5]}

    for i, trade in enumerate(trades, 1):
        ticker = trade['ticker'].upper()
        entry = float(trade['entry_price']) if trade['entry_price'] else 0
        exit_price = float(trade['exit_price']) if trade['exit_price'] and trade['exit_price'] != '' else None
        shares = int(trade['shares']) if trade['shares'] else 0
        pl_pct = float(trade['pl_percent']) if trade['pl_percent'] else 0
        pl_dollar = float(trade['pl_dollar']) if trade['pl_dollar'] else 0

        print(f"\n#{i}: {ticker}")
        print(f"   Entry: ${entry:.2f} × {shares} shares")

        if exit_price:
            print(f"   Exit:  ${exit_price:.2f}")
            print(f"   P/L:   ${pl_dollar:.2f} ({pl_pct:+.1f}%)")

            # Check if this was a top pick
            if ticker in best_tickers:
                # Find the trajectory
                traj = next((t for t in best_picks if t.ticker == ticker), None)
                if traj:
                    max_gain = traj.calculate_open_to_peak_gain()
                    efficiency = (pl_pct / max_gain * 100) if max_gain > 0 else 0
                    print(f"   ✅ HIT! This was EOD pick #{best_picks.index(traj) + 1}")
                    print(f"   Max Possible: +{max_gain:.1f}% (you captured {efficiency:.0f}%)")
            else:
                print(f"   ℹ️  Not in EOD top 5")
        else:
            print(f"   Status: Still holding")

    # Show what was missed
    traded_tickers = {trade['ticker'].upper() for trade in trades}
    missed_tickers = best_tickers - traded_tickers

    if missed_tickers:
        print(f"\n⚠️  MISSED OPPORTUNITIES (not traded):")
        for traj in best_picks[:5]:
            if traj.ticker in missed_tickers:
                gain = traj.calculate_open_to_peak_gain()
                entry_start, entry_end, entry_min, entry_max = traj.get_entry_window()
                print(f"   {traj.ticker}: +{gain:.1f}% (entry: {entry_start}-{entry_end} @ ${entry_min:.2f}-${entry_max:.2f})")

    print("\n" + "="*60)


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Analyze end-of-day scanner results")
    parser.add_argument("--date", help="Date to analyze (YYYY-MM-DD), defaults to today")
    parser.add_argument("--min-gain", type=float, default=MIN_GAIN_PCT,
                        help=f"Minimum gain %% threshold (default: {MIN_GAIN_PCT})")
    parser.add_argument("--no-csv", action="store_true", help="Don't append to missed.csv")
    args = parser.parse_args()

    # Determine date
    if args.date:
        report_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        report_date = date.today()

    # Use threshold from args
    min_gain_threshold = args.min_gain

    # Find log file
    log_filename = f"scanner_{report_date}.log"
    log_path = os.path.join(LOG_DIR, log_filename)

    if not os.path.isfile(log_path):
        print(f"Error: Log file not found: {log_path}")
        return

    print(f"Analyzing scanner log: {log_path}")
    print(f"Minimum gain threshold: {min_gain_threshold}%")
    print()

    # Parse log
    trajectories = parse_scanner_log(log_path)
    print(f"Tracked {len(trajectories)} unique tickers")

    # Identify best picks (pass threshold to function)
    best_picks = [t for t in identify_best_picks(trajectories)
                  if t.calculate_open_to_peak_gain() >= min_gain_threshold]
    print(f"Found {len(best_picks)} catchable opportunities (>{min_gain_threshold}% gain)")
    print()

    # Write reports
    write_daily_report(report_date, best_picks)

    # Append to missed.csv
    if not args.no_csv:
        append_to_missed_csv(report_date, best_picks)

    # Load and compare with journal trades
    trades = load_journal_trades(report_date)
    compare_with_journal(report_date, best_picks, trades)


if __name__ == "__main__":
    main()
