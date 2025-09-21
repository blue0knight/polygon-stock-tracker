import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

def calculate_gap(prev_close: float, last_price: float) -> float:
    """Calculate gap % from previous close to current last price."""
    if not prev_close or prev_close <= 0:
        return 0.0
    return ((last_price - prev_close) / prev_close) * 100


def score_snapshots(snapshots: Dict[str, Dict]) -> List[Tuple[str, float]]:
    """
    Given snapshot data keyed by ticker, calculate gap % for each.
    snapshots format:
      {
        "AAPL": {"prevClose": 220.5, "lastTrade": 225.1},
        "TSLA": {"prevClose": 270.2, "lastTrade": 263.9},
        ...
      }
    Returns a list of (ticker, gap%) sorted by gap % desc.
    """
    scored = []
    for ticker, data in snapshots.items():
        prev = data.get("prevClose")
        last = data.get("lastTrade")
        if prev is None or last is None:
            continue
        gap = calculate_gap(prev, last)
        scored.append((ticker, gap))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def top_movers(scored: List[Tuple[str, float]], n: int = 5) -> List[Tuple[str, float]]:
    """Return the top N tickers by gap %."""
    return scored[:n]


def log_top_movers(scored: List[Tuple[str, float]], n: int = 5):
    """Log the top N movers."""
    movers = top_movers(scored, n)
    logger.info("Top %d movers by gap %%:", n)
    for ticker, gap in movers:
        logger.info("  %s: %.2f%%", ticker, gap)
