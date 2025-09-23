import logging

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

def log_top_movers(scored, snapshots, n=5):
    logger = logging.getLogger("scanner")
    top = scored[:n]
    if not top:
        logger.warning("No movers available to log.")
        return
    logger.info(f"Top {n} movers:")
    for ticker, gain in top:
        snap = snapshots.get(ticker, {})
        price = snap.get("last_price") or snap.get("prev_close")
        if price:
            logger.info(f"  {ticker}: ${price:.2f} ({gain:.2f}%)")
        else:
            logger.info(f"  {ticker}: ({gain:.2f}%) [no price]")
