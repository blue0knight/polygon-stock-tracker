"""
Filtering logic for tradeable candidates.
"""

def is_tradeable(snapshot: dict, cfg: dict, premarket_high: float) -> bool:
    """
    Decide if a ticker is tradeable based on rules.
    
    snapshot: dict from Polygon snapshot (last_price, prev_close, etc.)
    cfg: loaded YAML config
    premarket_high: float, premarket high price for the ticker
    """

    price = snapshot.get("last_price")
    if not price:
        return False

    # --- Rule 1: must be above premarket high + buffer ---
    buffer = cfg["buffer"]["breakout_buffer_pct"]
    if price < premarket_high * (1 + buffer):
        return False

    # --- Rule 2: skip if already past T2 ---
    t2 = cfg["targets"]["t2"]
    if price >= premarket_high * (1 + t2):
        return False

    # --- Rule 3: skip penny junk ---
    if price < 1.00:
        return False

    # --- Rule 4: volume placeholder (future feature) ---
    # Example: check snapshot.get("volume", 0)

    return True
