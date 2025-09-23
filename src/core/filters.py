# src/core/filters.py

def is_tradeable(snapshot, cfg, ref_price):
    """
    Basic tradeable filter.

    Arguments:
    - snapshot: dict for a single ticker (with last_price, prev_close, etc.)
    - cfg: full config dict (scanner.yaml loaded)
    - ref_price: price to compare against (e.g., premarket high or prev_close)

    Returns:
    - True if the ticker is considered tradeable
    - False otherwise
    """

    try:
        # Get last known price (fallback to prev_close)
        price = snapshot.get("last_price") or snapshot.get("prev_close")
        volume = snapshot.get("volume") or 0

        if not price:
            return False

        # Example rule: skip penny stocks under $1
        if price < 1.0:
            return False

        # Example rule: skip illiquid names with no volume
        if volume == 0:
            return False

        # Example rule: if price < reference price by too much, skip
        if ref_price and price < 0.5 * ref_price:
            return False

        # If all checks passed → tradeable
        return True

    except Exception:
        return False
