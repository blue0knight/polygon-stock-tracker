# src/core/scoring.py
import logging
from datetime import datetime
import pytz


def score_snapshots(snapshots: dict):
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

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def log_top_movers(scored, snapshots, n=5, tag=""):
    """
    Logs the top n movers with price, % move, and timestamp.
    Keeps [PRE]/[POST] tag in logs.
    """
    logger = logging.getLogger("scanner")
    top = scored[:n]
    if not top:
        logger.warning(f"{tag} No movers available to log.")
        return

    logger.info(f"{tag} Top {n} movers by gap %:")
    tz = pytz.timezone("America/New_York")

    for ticker, gain in top:
        snap = snapshots.get(ticker, {})
        price = snap.get("last_price") or snap.get("prev_close")

        # ✅ prefer minute_ts (Polygon bar timestamp), fallback to others
        ts = (
            snap.get("minute_ts")
            or snap.get("timestamp")
            or snap.get("updated")
            or snap.get("last_updated")
        )

        ts_str = None
        if ts:
            try:
                if isinstance(ts, (int, float)):  # epoch ms
                    ts_dt = datetime.fromtimestamp(ts / 1000, tz=tz)
                    ts_str = ts_dt.strftime("%H:%M:%S")
                else:
                    ts_str = str(ts)
            except Exception:
                ts_str = str(ts)

        if price and ts_str:
            logger.info(f"{tag}   {ticker}: ${price:.2f} ({gain:.2f}%) @ {ts_str} ET")
        elif price:
            logger.info(f"{tag}   {ticker}: ${price:.2f} ({gain:.2f}%)")
        elif ts_str:
            logger.info(f"{tag}   {ticker}: ({gain:.2f}%) @ {ts_str} ET [no price]")
        else:
            logger.info(f"{tag}   {ticker}: ({gain:.2f}%) [no price]")
