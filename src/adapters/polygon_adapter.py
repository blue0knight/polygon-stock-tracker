from __future__ import annotations

## -------------------------------------------------------------------
## Polygon Adapter
##  - Snapshot fetch
##  - Premarket high
##  - ATR(14) calculation
## -------------------------------------------------------------------
import os
import requests
import calendar
from datetime import datetime, timedelta
import pytz

BASE_URL = "https://api.polygon.io"

def _require_api_key():
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("❌ No POLYGON_API_KEY found in environment or .env file")
    return api_key

def to_unix_ms(dt):
    return int(calendar.timegm(dt.utctimetuple()) * 1000)


## -------------------------------------------------------------------
## Snapshots Adapter
## -------------------------------------------------------------------
def fetch_snapshots(limit: int = 50) -> list[dict]:
    """
    Fetch latest snapshot data for US stocks from Polygon.
    Returns a list of dicts with ticker + basic prices.
    """
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("❌ No POLYGON_API_KEY found in environment or .env file")

    url = f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers"
    params = {"limit": limit, "apiKey": api_key}

    resp = requests.get(url, params=params)
    if resp.status_code != 200:
        raise RuntimeError(f"❌ Polygon API error {resp.status_code}: {resp.text}")

    data = resp.json()
    tickers = data.get("tickers", [])
    out = []

    for t in tickers:
        out.append({
            "ticker": t.get("ticker"),
            "last_price": t.get("lastTrade", {}).get("p"),   # last trade price
            "prev_close": t.get("prevDay", {}).get("c"),     # previous close
            "volume": t.get("day", {}).get("v"),             # today's volume
            "open": t.get("day", {}).get("o"),               # today's open
            "high": t.get("day", {}).get("h"),
            "low": t.get("day", {}).get("l"),
            "close": t.get("day", {}).get("c"),
        })

    return out

## -------------------------------------------------------------------
## Previous Close
## -------------------------------------------------------------------
def get_previous_close(ticker: str) -> float:
    api_key = _require_api_key()
    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/prev"
    resp = requests.get(url, params={"adjusted": "true", "apiKey": api_key})
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return results[0].get("c", 0.0) if results else 0.0

## -------------------------------------------------------------------
## Premarket High
## -------------------------------------------------------------------
def get_premarket_high(ticker: str, date: str) -> float:
    api_key = _require_api_key()
    ny = pytz.timezone("America/New_York")
    start_dt = ny.localize(datetime.strptime(f"{date} 04:00:00", "%Y-%m-%d %H:%M:%S"))
    end_dt = ny.localize(datetime.strptime(f"{date} 09:29:00", "%Y-%m-%d %H:%M:%S"))
    start_ms = to_unix_ms(start_dt.astimezone(pytz.UTC))
    end_ms = to_unix_ms(end_dt.astimezone(pytz.UTC))

    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{start_ms}/{end_ms}"
    resp = requests.get(url, params={"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": api_key})
    resp.raise_for_status()
    bars = resp.json().get("results", [])
    highs = [bar.get("h", 0.0) for bar in bars]
    return max(highs) if highs else 0.0

## -------------------------------------------------------------------
## ATR(14) Calculation
## -------------------------------------------------------------------
def get_atr_14(ticker: str, trade_date: str) -> float:
    """
    Compute 14-day ATR using Polygon daily bars up to trade_date.
    Falls back to 1.0 if insufficient data.
    """
    try:
        api_key = _require_api_key()
        # look back ~20 days to compute ATR(14)
        end = datetime.strptime(trade_date, "%Y-%m-%d")
        start = end - timedelta(days=30)
        url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
        resp = requests.get(url, params={"adjusted": "true", "sort": "asc", "limit": 50, "apiKey": api_key})
        resp.raise_for_status()
        bars = resp.json().get("results", [])
        if len(bars) < 15:
            return 1.0  # not enough history

        trs = []
        for i in range(1, len(bars)):
            high = bars[i].get("h", 0.0)
            low = bars[i].get("l", 0.0)
            prev_close = bars[i-1].get("c", 0.0)
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)

        atr = sum(trs[-14:]) / 14
        return round(atr, 2) if atr > 0 else 1.0
    except Exception:
        return 1.0
