# src/adapters/polygon_client.py
import os
import httpx
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()  # read .env

API_KEY = os.getenv("POLYGON_API_KEY")
if not API_KEY:
    raise RuntimeError("Missing POLYGON_API_KEY in .env")

BASE_URL = "https://api.polygon.io/v2"


class PolygonClient:
    def __init__(self, api_key: str = API_KEY, base_url: str = BASE_URL):
        self.api_key = api_key
        self.base_url = base_url
        self.session = httpx.Client(timeout=10.0)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _get(self, endpoint: str, params: dict = None):
        if params is None:
            params = {}
        params["apiKey"] = self.api_key
        url = f"{self.base_url}{endpoint}"
        r = self.session.get(url, params=params)
        r.raise_for_status()
        return r.json()

    # --- Public methods ---
    def get_snapshot(self, ticker: str):
        """Get latest snapshot for a ticker (delayed 15m on Starter)."""
        endpoint = f"/snapshot/locale/us/markets/stocks/tickers/{ticker.upper()}"
        data = self._get(endpoint)
        return {
            "ticker": ticker.upper(),
            "day": data["ticker"]["day"],
            "minute": data["ticker"]["min"],
            "prev_day": data["ticker"]["prevDay"],
            "todays_change": data["ticker"]["todaysChange"],
            "todays_change_pct": data["ticker"]["todaysChangePerc"],
            # provenance stamp
            "provider_used": "polygon",
            "delayed_data": 1,
            "latency_minutes": 15,
            "coverage_note": "full_sip",
        }

    def get_aggregates(
        self,
        ticker: str,
        from_date: str,
        to_date: str,
        multiplier: int = 1,
        timespan: str = "minute",
        limit: int = 50000,
        adjusted: bool = True,
        sort: str = "asc",
    ):
        """
        Get aggregates (bars) for ticker.
        from_date / to_date format: YYYY-MM-DD
        """
        endpoint = f"/aggs/ticker/{ticker.upper()}/range/{multiplier}/{timespan}/{from_date}/{to_date}"
        params = {
            "adjusted": str(adjusted).lower(),
            "sort": sort,
            "limit": limit,
        }
        data = self._get(endpoint, params=params)
        return {
            "ticker": ticker.upper(),
            "results": data.get("results", []),
            "count": data.get("resultsCount", 0),
            "status": data.get("status"),
            # provenance stamp
            "provider_used": "polygon",
            "delayed_data": 1,
            "latency_minutes": 15,
            "coverage_note": "full_sip",
        }
