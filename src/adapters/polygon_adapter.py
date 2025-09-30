# -------------------------------------------------------------------
# FILE: src/adapters/polygon_adapter.py
# DATE: 2025-09-29
# PURPOSE: Polygon adapter for snapshots, premarket high, ATR(14),
#          intraday volume, average daily volume, and 09:30 open price.
# NOTES:
#   - Requires POLYGON_API_KEY in environment or .env
#   - All network calls have basic error handling & timeouts
#   - Timezone-aware calculations (America/New_York)
# -------------------------------------------------------------------
from __future__ import annotations

import os
import calendar
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

import pytz
import requests

BASE_URL = "https://api.polygon.io"
HTTP_TIMEOUT = 30  # seconds


# ---------------------------- helpers --------------------------------
def _require_api_key() -> str:
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("❌ No POLYGON_API_KEY found in environment or .env file")
    return api_key


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "polygon-stock-tracker/1.0"})
    s.mount("https://", requests.adapters.HTTPAdapter(max_retries=3))
    return s



def to_unix_ms(dt: datetime) -> int:
    """Convert aware datetime -> unix epoch milliseconds (UTC)."""
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware")
    return int(calendar.timegm(dt.utctimetuple()) * 1000)


def _today_ny() -> datetime:
    return datetime.now(pytz.timezone("America/New_York"))


# ------------------------- snapshots adapter --------------------------
def fetch_snapshots(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Fetch latest snapshot data for US stocks from Polygon.
    Returns a list of dicts with ticker + basic prices.
    """
    api_key = _require_api_key()
    url = f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers"
    params = {"limit": limit, "apiKey": api_key}

    with _session() as s:
        resp = s.get(url, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

    tickers = data.get("tickers", []) or []
    out: List[Dict[str, Any]] = []
    for t in tickers:
        out.append(
            {
                "ticker": t.get("ticker"),
                "last_price": t.get("lastTrade", {}).get("p"),
                "prev_close": t.get("prevDay", {}).get("c"),
                "volume": t.get("day", {}).get("v"),   # today's volume (exchange session)
                "open": t.get("day", {}).get("o"),
                "high": t.get("day", {}).get("h"),
                "low": t.get("day", {}).get("l"),
                "close": t.get("day", {}).get("c"),
            }
        )
    return out


## -------------------------------------------------------------------
## BLOCK: get-snapshot-single  |  FILE: src/adapters/polygon_adapter.py  |  DATE: 2025-09-30
## PURPOSE: Fetch single-ticker snapshot (for hybrid enrichment)
## NOTES:
##   - Returns raw JSON from Polygon, trimmed to common fields
##   - Compatible with bulk fetch_snapshots shape
## -------------------------------------------------------------------
def get_snapshot(ticker: str) -> Dict[str, Any]:
    api_key = _require_api_key()
    url = f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"

    with _session() as s:
        resp = s.get(url, params={"apiKey": api_key}, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json() or {}

    t = data.get("ticker", {})
    if not t:
        return {}

    return {
        "ticker": t.get("ticker"),
        "last_price": t.get("lastTrade", {}).get("p"),
        "prev_close": t.get("prevDay", {}).get("c"),
        "volume": t.get("day", {}).get("v"),
        "open": t.get("day", {}).get("o"),
        "high": t.get("day", {}).get("h"),
        "low": t.get("day", {}).get("l"),
        "close": t.get("day", {}).get("c"),
    }
## -------------------------------------------------------------------


# --------------------------- previous close ---------------------------
def get_previous_close(ticker: str) -> float:
    api_key = _require_api_key()
    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/prev"
    params = {"adjusted": "true", "apiKey": api_key}

    with _session() as s:
        resp = s.get(url, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        results = resp.json().get("results", []) or []

    return results[0].get("c", 0.0) if results else 0.0


# --------------------------- premarket high ---------------------------
def get_premarket_high(ticker: str, date: str) -> float:
    """
    Highest price between 04:00:00 and 09:29:59 ET for the given trade date.
    Uses 1-minute aggregates with UNIX ms range.
    """
    api_key = _require_api_key()
    ny = pytz.timezone("America/New_York")
    start_dt = ny.localize(datetime.strptime(f"{date} 04:00:00", "%Y-%m-%d %H:%M:%S"))
    end_dt = ny.localize(datetime.strptime(f"{date} 09:29:59", "%Y-%m-%d %H:%M:%S"))

    start_ms = to_unix_ms(start_dt.astimezone(pytz.UTC))
    end_ms = to_unix_ms(end_dt.astimezone(pytz.UTC))

    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{start_ms}/{end_ms}"
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": api_key}

    with _session() as s:
        resp = s.get(url, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        bars = resp.json().get("results", []) or []

    highs = [bar.get("h", 0.0) for bar in bars]
    return max(highs) if highs else 0.0


# ------------------------------ ATR(14) -------------------------------
def get_atr_14(ticker: str, trade_date: str) -> float:
    """
    Compute 14-day ATR using Polygon daily bars up to `trade_date`.
    Falls back to 1.0 if insufficient data or on error.
    """
    try:
        api_key = _require_api_key()
        end = datetime.strptime(trade_date, "%Y-%m-%d")
        start = end - timedelta(days=40)  # generous buffer for 14 obs

        url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
        params = {"adjusted": "true", "sort": "asc", "limit": 200, "apiKey": api_key}

        with _session() as s:
            resp = s.get(url, params=params, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            bars = resp.json().get("results", []) or []

        if len(bars) < 15:
            return 1.0  # not enough history

        trs: List[float] = []
        for i in range(1, len(bars)):
            high = float(bars[i].get("h", 0.0) or 0.0)
            low = float(bars[i].get("l", 0.0) or 0.0)
            prev_close = float(bars[i - 1].get("c", 0.0) or 0.0)
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)

        atr = sum(trs[-14:]) / 14
        return round(atr, 4) if atr > 0 else 1.0
    except Exception:
        return 1.0


# --------------------------- intraday volume --------------------------
def get_intraday_volume(ticker: str, trade_date: str) -> int:
    """
    Return cumulative intraday volume from 04:00 ET up to 'now' ET for trade_date.
    Uses 1-minute aggregates; sums 'v' across bars.
    Falls back to 0 on error or no data.
    """
    try:
        api_key = _require_api_key()
        ny = pytz.timezone("America/New_York")

        start_dt = ny.localize(datetime.strptime(f"{trade_date} 04:00:00", "%Y-%m-%d %H:%M:%S"))
        now_ny = _today_ny()
        # If you're querying a past date intraday volume, cap at that day's 20:00 to avoid future bars
        end_dt = now_ny if trade_date == now_ny.strftime("%Y-%m-%d") else ny.localize(
            datetime.strptime(f"{trade_date} 20:00:00", "%Y-%m-%d %H:%M:%S")
        )

        start_ms = to_unix_ms(start_dt.astimezone(pytz.UTC))
        end_ms = to_unix_ms(end_dt.astimezone(pytz.UTC))

        url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{start_ms}/{end_ms}"
        params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": api_key}

        with _session() as s:
            resp = s.get(url, params=params, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            bars = resp.json().get("results", []) or []

        return int(sum(int(bar.get("v", 0) or 0) for bar in bars))
    except Exception:
        return 0


# ------------------------ average daily volume ------------------------
def get_avg_daily_volume(ticker: str, lookback: int = 20) -> int:
    """
    Return average daily volume over the most recent `lookback` sessions.
    Falls back to 0 on error or if no data.
    """
    try:
        api_key = _require_api_key()
        end = datetime.utcnow().date()
        start = end - timedelta(days=max(lookback * 3, 90))  # buffer for market-closed days

        url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
        params = {"adjusted": "true", "sort": "desc", "limit": lookback, "apiKey": api_key}

        with _session() as s:
            resp = s.get(url, params=params, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            bars = resp.json().get("results", []) or []

        if not bars:
            return 0

        vols = [int(bar.get("v", 0) or 0) for bar in bars[:lookback]]
        return int(sum(vols) / len(vols)) if vols else 0
    except Exception:
        return 0


# --------------------------- 09:30 open price -------------------------
def get_open_price_0930(ticker: str, trade_date: str) -> float:
    """
    Fetch the true 09:30:00 ET open price for `trade_date` using 1-min bars.
    If the 09:30 bar is missing, returns 0.0.
    """
    api_key = _require_api_key()
    ny = pytz.timezone("America/New_York")

    start_dt = ny.localize(datetime.strptime(f"{trade_date} 09:30:00", "%Y-%m-%d %H:%M:%S"))
    end_dt = ny.localize(datetime.strptime(f"{trade_date} 09:31:00", "%Y-%m-%d %H:%M:%S"))

    start_ms = to_unix_ms(start_dt.astimezone(pytz.UTC))
    end_ms = to_unix_ms(end_dt.astimezone(pytz.UTC))

    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{start_ms}/{end_ms}"
    params = {"adjusted": "true", "sort": "asc", "limit": 5, "apiKey": api_key}

    with _session() as s:
        resp = s.get(url, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        bars = resp.json().get("results", []) or []

    if not bars:
        return 0.0

    # The first bar in this window should be 09:30
    first_bar = bars[0]
    return float(first_bar.get("o", 0.0) or 0.0)
