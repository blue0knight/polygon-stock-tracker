import csv
import os
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

WATCHLIST_HEADERS = [
    "date", "ticker", "entry_price", "shares", "total_cost",
    "exit_price", "pl_dollar", "pl_percent",
    "t1", "t2", "stretch"
]

def write_watchlist(filepath: str, movers: List[Tuple[str, float]], targets: dict):
    """
    Write top movers into watchlist CSV using template headers.
    
    movers: list of (ticker, gap%) from scoring
    targets: dict of target levels {t1, t2, stretch}
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    file_exists = os.path.isfile(filepath)

    with open(filepath, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=WATCHLIST_HEADERS)

        if not file_exists:
            writer.writeheader()

        for ticker, gap in movers:
            row = {
                "date": __import__("datetime").date.today().isoformat(),
                "ticker": ticker,
                "entry_price": "",
                "shares": "",
                "total_cost": "",
                "exit_price": "",
                "pl_dollar": "",
                "pl_percent": "",
                "t1": targets.get("t1", ""),
                "t2": targets.get("t2", ""),
                "stretch": targets.get("stretch", "")
            }
            writer.writerow(row)

    logger.info("✅ Wrote %d movers into %s", len(movers), filepath)
