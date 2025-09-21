"""
Quick test script to confirm Polygon adapter is fetching data.
Run:  python scripts/test_fetch.py
"""

from src.adapters.polygon_adapter import fetch_snapshots

def main():
    print("Testing Polygon snapshot fetcher...")
    tickers = fetch_snapshots(limit=5)   # small batch for clarity
    print(f"✅ Retrieved {len(tickers)} tickers")
    if tickers:
        print("Sample ticker:", tickers[0])

if __name__ == "__main__":
    main()
