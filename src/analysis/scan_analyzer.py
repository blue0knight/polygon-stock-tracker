#!/usr/bin/env python3
"""
Scan History Analyzer - Learn from intraday scanner data

Purpose:
- Identify patterns in successful picks (when did winners first appear?)
- Calibrate scoring (what scores correlate with actual runners?)
- Detect false positives (which high-scorers faded?)
- Optimize entry timing (when to enter vs when stock peaks?)

Usage:
  python -m src.analysis.scan_analyzer logs/scanner_2025-10-03.log
"""

import re
from datetime import datetime
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

class ScanAnalyzer:
    """Analyze scanner log files to extract insights"""

    def __init__(self, log_path: str):
        self.log_path = Path(log_path)
        self.scan_history = defaultdict(list)  # {ticker: [(time, score, gap, price, vol), ...]}
        self.top5_appearances = defaultdict(int)  # {ticker: count}

    def parse_log(self):
        """Extract Top 5 entries from scanner log"""
        pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[INFO\]\s+(\w+): score=(\d+\.\d+) gap=([+-]?\d+\.\d+)% last=(\d+\.\d+) prev=(\d+\.\d+) vol=([\d.]+[KM]?)'

        with open(self.log_path, 'r') as f:
            for line in f:
                match = re.search(pattern, line)
                if match:
                    timestamp_str, ticker, score, gap, last, prev, vol = match.groups()
                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')

                    # Parse volume (convert K/M to numbers)
                    vol_num = float(vol.replace('M', '').replace('K', ''))
                    if 'M' in vol:
                        vol_num *= 1_000_000
                    elif 'K' in vol:
                        vol_num *= 1_000

                    self.scan_history[ticker].append({
                        'time': timestamp,
                        'score': float(score),
                        'gap': float(gap),
                        'price': float(last),
                        'prev': float(prev),
                        'volume': vol_num
                    })
                    self.top5_appearances[ticker] += 1

    def get_first_appearance(self, ticker: str) -> Dict:
        """Get when ticker first appeared in Top 5"""
        if ticker in self.scan_history:
            return self.scan_history[ticker][0]
        return None

    def get_peak_price(self, ticker: str) -> Tuple[float, datetime]:
        """Get highest price and when it occurred"""
        if ticker not in self.scan_history:
            return None, None

        peak = max(self.scan_history[ticker], key=lambda x: x['price'])
        return peak['price'], peak['time']

    def analyze_ticker(self, ticker: str):
        """Full analysis of a specific ticker's scanner activity"""
        if ticker not in self.scan_history:
            return f"{ticker}: Not found in scanner history"

        history = self.scan_history[ticker]
        first = history[0]
        peak_price, peak_time = self.get_peak_price(ticker)

        report = f"""
{'='*60}
{ticker} - Scanner Activity Analysis
{'='*60}

📊 Overview:
  - Appearances in Top 5: {self.top5_appearances[ticker]}
  - First seen: {first['time'].strftime('%H:%M:%S')}
  - Entry price at first scan: ${first['price']:.2f}
  - Peak price: ${peak_price:.2f} @ {peak_time.strftime('%H:%M:%S')}
  - Gain from first scan: {((peak_price - first['price']) / first['price'] * 100):+.2f}%

📈 Score Evolution:
"""
        for i, scan in enumerate(history, 1):
            time_str = scan['time'].strftime('%H:%M')
            report += f"  {i}. {time_str} | score={scan['score']:.1f} | ${scan['price']:.2f} | gap={scan['gap']:+.1f}%\n"

        return report

    def find_best_performers(self, min_gain: float = 10.0) -> List[str]:
        """Find tickers that gained min_gain% from first appearance to peak"""
        performers = []
        for ticker in self.scan_history:
            first_price = self.scan_history[ticker][0]['price']
            peak_price, _ = self.get_peak_price(ticker)
            gain_pct = ((peak_price - first_price) / first_price) * 100

            if gain_pct >= min_gain:
                performers.append((ticker, gain_pct, first_price, peak_price))

        return sorted(performers, key=lambda x: x[1], reverse=True)

    def summarize(self):
        """Print summary of scan activity"""
        print(f"\n📊 Scanner Log Analysis: {self.log_path.name}")
        print(f"{'='*60}\n")

        print(f"📋 Total unique tickers in Top 5: {len(self.scan_history)}")

        # Find best performers
        performers = self.find_best_performers(min_gain=10.0)
        if performers:
            print(f"\n🚀 Top Performers (10%+ gain from first scan):")
            for ticker, gain, first, peak in performers[:10]:
                print(f"  {ticker}: ${first:.2f} → ${peak:.2f} ({gain:+.1f}%)")

        # Find most frequently appearing
        top_frequent = sorted(self.top5_appearances.items(), key=lambda x: x[1], reverse=True)[:5]
        print(f"\n👁️ Most Frequent Top 5 Appearances:")
        for ticker, count in top_frequent:
            print(f"  {ticker}: {count} times")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m src.analysis.scan_analyzer logs/scanner_YYYY-MM-DD.log")
        print("       python -m src.analysis.scan_analyzer logs/scanner_YYYY-MM-DD.log TICKER")
        sys.exit(1)

    log_file = sys.argv[1]
    analyzer = ScanAnalyzer(log_file)
    analyzer.parse_log()

    if len(sys.argv) == 3:
        # Analyze specific ticker
        ticker = sys.argv[2].upper()
        print(analyzer.analyze_ticker(ticker))
    else:
        # Show summary
        analyzer.summarize()
