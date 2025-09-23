import os
import requests
from dotenv import load_dotenv

load_dotenv()

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
BASE_URL = "https://api.polygon.io"


def fetch_snapshots(limit=50):
    if not POLYGON_API_KEY:
        raise RuntimeError("❌ No POLYGON_API_KEY found in environment or .env file")

    url = f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers"
    resp = requests.get(url, params={"apiKey": POLYGON_API_KEY})
    resp.raise_for_status()
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
