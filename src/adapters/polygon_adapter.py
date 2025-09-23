import os
import requests
from dotenv import load_dotenv

# Always load .env from project root
ENV_PATH = os.path.join(os.path.dirname(__file__), "../../.env")
load_dotenv(dotenv_path=ENV_PATH)

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
BASE_URL = "https://api.polygon.io"


def fetch_snapshots(limit=50):
    """
    Fetch a batch of US stock snapshots from Polygon and normalize
    them for the scanner. Filters to common stocks with usable data.
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

    # 🔍 DEBUG — inspect what Polygon actually gave us
    print(f"Raw keys: {list(data.keys())}")
    print(f"Sample raw item: {data.get('tickers', [])[0] if data.get('tickers') else 'NO TICKERS'}")

    results = []
    for item in data.get("tickers", []):
        last_price = None
        if "min" in item and "c" in item["min"]:
            last_price = item["min"]["c"]  # last minute close
        elif "day" in item and "c" in item["day"]:
            last_price = item["day"]["c"]  # fallback if min missing

        results.append({
            "ticker": item["ticker"],
            "last_price": last_price,
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

