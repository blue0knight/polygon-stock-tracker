import os
import requests

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
BASE_URL = "https://api.polygon.io"

def fetch_snapshots(limit=50):
    """
    Fetch a batch of US stock snapshots from Polygon and normalize
    them for the scanner.
    """
    if not POLYGON_API_KEY:
        raise RuntimeError("❌ No POLYGON_API_KEY found in environment or .env file")

    url = f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers"
    params = {"apiKey": POLYGON_API_KEY, "limit": limit}
    resp = requests.get(url, params=params)

    if resp.status_code == 401:
        raise RuntimeError("❌ Unauthorized: Check your Polygon API key or subscription tier")

    if resp.status_code != 200:
        raise RuntimeError(f"❌ Polygon API error {resp.status_code}: {resp.text}")

    data = resp.json()

    results = []
    for item in data.get("tickers", []):
        results.append({
            "ticker": item["ticker"],
            "last_price": item.get("lastTrade", {}).get("p"),
            "prev_close": item.get("prevDay", {}).get("c"),
            "todays_change": item.get("todaysChange"),
            "todays_change_pct": item.get("todaysChangePerc"),
            "volume": item.get("day", {}).get("v"),
            # provenance stamps
            "provider_used": "polygon",
            "delayed_data": 1,
            "latency_minutes": 15,
            "coverage_note": "full_sip"
        })
    return results
