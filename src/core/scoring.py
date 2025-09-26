import logging
from datetime import datetime

def compute_gap_pct(snapshot: dict):
    """
    Returns gap % as percentage points (e.g., 3.25 means +3.25%).
    Prefers Polygon's todays_change_pct when present.
    Falls back to (last_price - prev_close) / prev_close * 100.
    """
    pct = snapshot.get("todays_change_pct")
    if isinstance(pct, (int, float)):
        return float(pct)

    lp = snapshot.get("last_price")
    pc = snapshot.get("prev_close")
    if isinstance(lp, (int, float)) and isinstance(pc, (int, float)) and pc:
        return (lp - pc) / pc * 100.0

    return None


def score_snapshots(snapshots: dict):
    """
    Converts raw snapshot dict {ticker: snapshot} into a list of dicts
    with computed gap_pct and other fields, sorted by gap_pct descending.
    Applies basic sanity filters to skip broken/garbage data.
    """
    scored = []
    for ticker, snap in snapshots.items():
        gap = compute_gap_pct(snap)
        if gap is None:
            continue

        # 🚨 Premarket sanity filters
        if gap <= -80 or gap >= 300:
            continue

        scored.append({
            "ticker": ticker,
            "gap_pct": float(gap),
            "last_price": snap.get("last_price"),
            "prev_close": snap.get("prev_close"),
            "volume": snap.get("volume", 0),
        })

    return sorted(scored, key=lambda x: x["gap_pct"], reverse=True)


def log_top_movers(scored, n=5, session="PRE", logger=None):
    """
    Logs the Top-N movers with consistent formatting.
    Adds prefix [PRE] or [POST].
    Highlights the Current Pick (highest gap %).
    """
    if logger is None:
        logger = logging.getLogger("scanner")

    now_ts = datetime.now().strftime("%H:%M:%S ET")

    if not scored:
        logger.info(f"[{session}] No movers to log at {now_ts}")
        return

    top = sorted(scored, key=lambda x: x.get("gap_pct", 0), reverse=True)[:n]

    logger.info(f"[{session}] Top {len(top)} movers by gap %:")
    for m in top:
        ticker = m.get("ticker", "N/A")
        price = m.get("last_price") or m.get("prev_close") or 0
        gap = round(m.get("gap_pct", 0), 2)
        logger.info(f"[{session}]   {ticker}: ${price} ({gap}%) @ {now_ts} [delayed 15m]")

    best = top[0]
    best_ticker = best.get("ticker", "N/A")
    best_price = best.get("last_price") or best.get("prev_close") or 0
    best_gap = round(best.get("gap_pct", 0), 2)
    logger.info(f"[{session}] 📌 Current Top Pick: {best_ticker} (${best_price}, {best_gap}%)")
