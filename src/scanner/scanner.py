import logging
from datetime import datetime
import pytz


def score_snapshots(snapshots: dict):
    """
    Takes a dict of snapshots {ticker: snapshot} and returns
    a list of (ticker, pct_gain) sorted by % move (desc).
    """
    scored = []
    for ticker, snap in snapshots.items():
        try:
            last = snap.get("last_price") or 0
            prev = snap.get("prev_close") or 0
            if prev > 0:
                pct_gain = ((last - prev) / prev) * 100
                scored.append((ticker, pct_gain))
        except Exception:
            continue

    # Sort by % move descending
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def log_top_movers(scored, snapshots, n=5):
    """
    Logs the top n movers with price, % move, and timestamp.
    scored: [(ticker, pct_gain), ...] sorted desc
    snapshots: dict[ticker] = snapshot (with last_price/prev_close/timestamp)
    """
    logger = logging.getLogger("scanner")
    top = scored[:n]
    if not top:
        logger.warning("No movers available to log.")
        return

    logger.info(f"Top {n} movers:")
    for ticker, gain in top:
        snap = snapshots.get(ticker, {})
        price = snap.get("last_price") or snap.get("prev_close")
        ts = snap.get("timestamp") or snap.get("last_updated")

        # Convert timestamp if epoch ms → human-readable ET
        ts_str = None
        if ts:
            try:
                if isinstance(ts, (int, float)):
                    ts_dt = datetime.fromtimestamp(ts / 1000, tz=pytz.timezone("America/New_York"))
                    ts_str = ts_dt.strftime("%H:%M:%S")
                else:
                    ts_str = str(ts)
            except Exception:
                ts_str = str(ts)

        if price:
            if ts_str:
                logger.info(f"  {ticker}: ${price:.2f} ({gain:.2f}%) @ {ts_str} ET")
            else:
                logger.info(f"  {ticker}: ${price:.2f} ({gain:.2f}%)")
        else:
            if ts_str:
                logger.info(f"  {ticker}: ({gain:.2f}%) @ {ts_str} ET [no price]")
            else:
                logger.info(f"  {ticker}: ({gain:.2f}%) [no price]")
