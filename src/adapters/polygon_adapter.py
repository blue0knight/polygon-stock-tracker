from __future__ import annotations

## -------------------------------------------------------------------
## Imports
## -------------------------------------------------------------------
import os
import requests
from typing import List, Dict
from dotenv import load_dotenv

BASE_URL = "https://api.polygon.io"

## -------------------------------------------------------------------
## Polygon Snapshot Fetcher
##  - fetch_snapshots(): gets batch tickers for scanner
## -------------------------------------------------------------------
def fetch_snapshots(limit=50):
    """
    Fetch a batch of US stock snapshots from Polygon and normalize
    them for the scanner.
    """
    api_key = os.getenv("POLYGON_API_KEY")  # <-- Lazy load here
    if not api_key:
        raise RuntimeError("❌ No POLYGON_API_KEY found in environment or .env file")

    url = f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers"
    params = {"apiKey": api_key, "limit": limit}
    resp = requests.get(url, params=params)

    if resp.status_code == 401:
        raise RuntimeError("❌ Unauthorized: Check your Polygon API key or subscription tier")

    if resp.status_code != 200:
        raise RuntimeError(f"❌ Polygon API error {resp.status_code}: {resp.text}")

    data = resp.json()

    results = []
    for t in data.get("tickers", [])[:limit]:
        results.append({
            "ticker": t["ticker"],
            "last_price": t.get("lastTrade", {}).get("p"),
            "prev_close": t.get("prevDay", {}).get("c"),
            "todays_change": t.get("todaysChange"),
            "todays_change_pct": t.get("todaysChangePerc"),
            "volume": t.get("day", {}).get("v"),

            # --- NEW: timestamps (epoch ms) ---
            "minute_ts": t.get("min", {}).get("t"),
            "day_ts": t.get("day", {}).get("t"),

            "provider_used": "polygon",
            "delayed_data": 1,
            "latency_minutes": 15,
            "coverage_note": "full_sip",
        })
    return results

## -------------------------------------------------------------------
## Final Pick: Gap % Helpers
##  - get_previous_close()
##  - get_premarket_high()
## -------------------------------------------------------------------
def get_previous_close(ticker: str) -> float:
    """Return previous day's official close."""
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("❌ No POLYGON_API_KEY found in environment or .env file")

    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/prev"
    params = {"adjusted": "true", "apiKey": api_key}
    resp = requests.get(url, params=params)

    if resp.status_code != 200:
        raise RuntimeError(f"❌ Polygon API error {resp.status_code}: {resp.text}")

    data = resp.json()
    results = data.get("results", [])
    if not results:
        return 0.0
    return results[0].get("c", 0.0)

import calendar

def to_unix_ms(dt):
    return int(calendar.timegm(dt.utctimetuple()) * 1000)

def get_premarket_high(ticker: str, date: str) -> float:
    """Return max high prior to 09:30 ET for the given date (Polygon intraday bars)."""
    import pytz
    from datetime import datetime

    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("❌ No POLYGON_API_KEY found in environment or .env file")

    ny = pytz.timezone("America/New_York")

    # Premarket window
    start_dt = ny.localize(datetime.strptime(f"{date} 04:00:00", "%Y-%m-%d %H:%M:%S"))
    end_dt = ny.localize(datetime.strptime(f"{date} 09:29:00", "%Y-%m-%d %H:%M:%S"))

    # Convert to epoch ms
    start_ms = to_unix_ms(start_dt.astimezone(pytz.UTC))
    end_ms = to_unix_ms(end_dt.astimezone(pytz.UTC))

    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{start_ms}/{end_ms}"

    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": api_key}

    print(f"DEBUG URL: {url}")  # 👈 sanity check

    resp = requests.get(url, params=params)
    if resp.status_code != 200:
        raise RuntimeError(f"❌ Polygon API error {resp.status_code}: {resp.text}")

    data = resp.json()
    bars = data.get("results", [])
    if not bars:
        return 0.0

    highs = [bar.get("h", 0.0) for bar in bars]
    return max(highs) if highs else 0.0

## -------------------------------------------------------------------
## Final Pick: Relative Volume Helpers
##  - get_intraday_volume()
##  - get_avg_daily_volume()
##  - get_historical_bars()
## -------------------------------------------------------------------
def get_intraday_volume(ticker: str, date: str) -> int:
    """Return cumulative intraday volume so far for date."""
    from datetime import datetime
    import pytz

    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("❌ No POLYGON_API_KEY found in environment or .env file")

    tz = pytz.timezone("America/New_York")
    now = datetime.now(tz)

    # Convert to UTC timestamps for polygon
    start = datetime.combine(now.date(), datetime.min.time()).astimezone(tz)
    end = now

    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{start_ms}/{end_ms}"
    params = {"adjusted": "true", "apiKey": api_key}

    resp = requests.get(url, params=params)
    if resp.status_code != 200:
        raise RuntimeError(f"❌ Polygon API error {resp.status_code}: {resp.text}")

    data = resp.json()
    total_vol = sum([bar.get("v", 0) for bar in data.get("results", [])])
    return int(total_vol)

def get_avg_daily_volume(ticker: str, lookback: int = 20) -> float:
    """
    Return mean of last N daily volumes (excluding today).
    Uses Polygon daily aggregates.
    """
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("❌ No POLYGON_API_KEY found in environment or .env file")

    from datetime import date as date_cls, timedelta

    end_date = date_cls.today()
    start_date = end_date - timedelta(days=lookback * 2)  # buffer for weekends/holidays

    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{end_date}"
    params = {
        "adjusted": "true",
        "sort": "desc",
        "limit": lookback + 5,
        "apiKey": api_key,
    }
    resp = requests.get(url, params=params)

    if resp.status_code != 200:
        raise RuntimeError(f"❌ Polygon API error {resp.status_code}: {resp.text}")

    data = resp.json()
    bars = data.get("results", [])
    if not bars:
        return 0.0

    # Exclude today (latest bar)
    volumes = [bar.get("v", 0) for bar in bars[1:lookback+1] if "v" in bar]

    if not volumes:
        return 0.0

    return sum(volumes) / len(volumes)

def get_historical_bars(ticker: str, lookback: int = 20) -> List[Dict]:
    """
    Return list of dicts with OHLCV for the last N trading days.
    Shape:
      [
        {"date": "YYYY-MM-DD", "open": float, "high": float, "low": float, "close": float, "volume": int},
        ...
      ]
    """
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("❌ No POLYGON_API_KEY found in environment or .env file")

    from datetime import date as date_cls, timedelta

    end_date = date_cls.today()
    start_date = end_date - timedelta(days=lookback * 2)  # buffer for weekends/holidays

    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{end_date}"
    params = {
        "adjusted": "true",
        "sort": "desc",
        "limit": lookback,
        "apiKey": api_key,
    }
    resp = requests.get(url, params=params)

    if resp.status_code != 200:
        raise RuntimeError(f"❌ Polygon API error {resp.status_code}: {resp.text}")

    data = resp.json()
    bars = data.get("results", [])
    if not bars:
        return []

    results: List[Dict] = []
    from datetime import datetime
    for bar in bars:
        ts = datetime.utcfromtimestamp(bar["t"] / 1000).strftime("%Y-%m-%d")
        results.append({
            "date": ts,
            "open": bar.get("o", 0.0),
            "high": bar.get("h", 0.0),
            "low": bar.get("l", 0.0),
            "close": bar.get("c", 0.0),
            "volume": bar.get("v", 0),
        })

    return list(reversed(results))  # oldest → newest

## -------------------------------------------------------------------
## Final Pick: Catalyst Helpers
##  - has_recent_news()
##  - has_earnings_today()
## -------------------------------------------------------------------
def has_recent_news(ticker: str, days: int = 1) -> bool:
    """
    Return True if there is at least one news item in the last N days.
    Uses Polygon reference/news API.
    """
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("❌ No POLYGON_API_KEY found in environment or .env file")

    from datetime import datetime, timedelta

    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=days)

    url = f"{BASE_URL}/v2/reference/news"
    params = {
        "ticker": ticker,
        "published_utc.gte": str(start_date),
        "published_utc.lte": str(end_date),
        "apiKey": api_key,
    }
    resp = requests.get(url, params=params)

    if resp.status_code != 200:
        raise RuntimeError(f"❌ Polygon API error {resp.status_code}: {resp.text}")

    data = resp.json()
    articles = data.get("results", [])
    return len(articles) > 0

def has_earnings_today(ticker: str, date: str) -> bool:
    """
    Return True if earnings are scheduled for the given date.
    Uses Polygon stock financials / events API.
    """
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("❌ No POLYGON_API_KEY found in environment or .env file")

    url = f"{BASE_URL}/vX/reference/earnings/{ticker}"  # placeholder endpoint
    params = {"apiKey": api_key}
    resp = requests.get(url, params=params)

    # Note: Polygon’s earnings endpoint depends on subscription tier.
    # Replace `vX` with the correct version if you have access (vX placeholder).
    if resp.status_code != 200:
        return False

    data = resp.json()
    results = data.get("results", [])
    for ev in results:
        if ev.get("date") == date:
            return True
    return False

## -------------------------------------------------------------------
## Local Test Harness
## -------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import os
    from pathlib import Path
    from dotenv import load_dotenv
    from datetime import date as date_cls

    # --- Load .env so POLYGON_API_KEY or other secrets are available ---
    ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(ENV_PATH)

    # --- CLI args ---
    parser = argparse.ArgumentParser(description="Quick function test harness")
    parser.add_argument("--ticker", default="AAPL", help="Ticker symbol to test")
    parser.add_argument("--date", default=str(date_cls.today()), help="Date (YYYY-MM-DD)")
    parser.add_argument("--func", default="demo", help="Which function to run")
    args = parser.parse_args()

    print(f"DEBUG: .env path = {ENV_PATH}")
    print(f"DEBUG: POLYGON_API_KEY present? {'yes' if os.getenv('POLYGON_API_KEY') else 'no'}")

    # --- Dispatch ---
    if args.func == "demo":
        print(f"Demo: ticker={args.ticker}, date={args.date}")
    elif args.func == "earnings":
        result = has_earnings_today(args.ticker, args.date)
        print(f"has_earnings_today({args.ticker}, {args.date}) -> {result}")
    elif args.func == "prevclose":
        result = get_previous_close(args.ticker)
        print(f"get_previous_close({args.ticker}) -> {result}")
    elif args.func == "pmhigh":
        result = get_premarket_high(args.ticker, args.date)
        print(f"get_premarket_high({args.ticker}, {args.date}) -> {result}")
    elif args.func == "volume":
        result = get_intraday_volume(args.ticker, args.date)
        print(f"get_intraday_volume({args.ticker}, {args.date}) -> {result}")
    elif args.func == "avgvol":
        result = get_avg_daily_volume(args.ticker, lookback=20)
        print(f"get_avg_daily_volume({args.ticker}, 20) -> {result}")
    elif args.func == "bars":
        result = get_historical_bars(args.ticker, lookback=5)
        print(f"get_historical_bars({args.ticker}, 5) -> {result}")
    else:
        print(f"Unknown function: {args.func}")
