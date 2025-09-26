import csv
from datetime import datetime
import os
from typing import Any, Dict, Iterable, Optional, Tuple

def _normalize_mover(m: Any) -> Optional[Dict[str, Any]]:
    """
    Accepts a mover in several shapes and normalizes to:
    {"ticker": str, "gap_pct": float, "volume": int}
    Returns None if it can't be normalized.
    """
    # Case 1: already a dict
    if isinstance(m, dict):
        ticker = m.get("ticker") or m.get("symbol")
        gap = m.get("gap_pct") or m.get("gap") or m.get("percent")
        vol = m.get("volume") or m.get("vol") or 0
        if ticker is not None and gap is not None:
            return {"ticker": str(ticker), "gap_pct": float(gap), "volume": int(vol or 0)}
        return None

    # Case 2: tuple/list variants
    if isinstance(m, (tuple, list)):
        # ("TICKER", {"gap_pct": ..., "volume": ...})
        if len(m) >= 2 and isinstance(m[0], str) and isinstance(m[1], dict):
            d = m[1]
            gap = d.get("gap_pct") or d.get("gap") or d.get("percent")
            vol = d.get("volume") or d.get("vol") or 0
            if gap is not None:
                return {"ticker": m[0], "gap_pct": float(gap), "volume": int(vol or 0)}
            return None

        # ("TICKER", 292.12 [, 123456])
        if len(m) >= 2 and isinstance(m[0], str) and isinstance(m[1], (int, float)):
            ticker = m[0]
            gap = float(m[1])
            vol = int(m[2]) if len(m) >= 3 and isinstance(m[2], (int, float)) else 0
            return {"ticker": ticker, "gap_pct": gap, "volume": vol}

        # ({...},) weird cases
        if len(m) >= 1 and isinstance(m[0], dict):
            return _normalize_mover(m[0])

    # Unknown shape
    return None


def write_watchlist(path: str, movers: Iterable[Any], targets=None) -> None:
    """
    Writes Top-5 movers to CSV with schema:
    date, ticker, gap_pct, volume, timestamp

    - Accepts movers as dicts OR tuples.
    - Deduplicates by ticker (last occurrence in the batch wins).
    - Appends to file; writes header if file doesn't exist.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    now_ts = datetime.now().strftime("%H:%M:%S")

    # Normalize & dedupe
    seen: Dict[str, Dict[str, Any]] = {}
    for m in movers:
        nm = _normalize_mover(m)
        if not nm:
            continue
        # Skip rows with missing/absurd gap_pct
        gap = nm.get("gap_pct")
        if gap is None:
            continue
        # You can tighten these guards if needed
        if gap <= -99.9 or gap >= 1000:
            continue
        seen[nm["ticker"]] = nm  # last wins

    # Nothing to write
    if not seen:
        return

    rows = []
    for tkr, r in seen.items():
        rows.append({
            "date": today,
            "ticker": tkr,
            "gap_pct": round(float(r.get("gap_pct", 0.0)), 2),
            "volume": int(r.get("volume", 0) or 0),
            "timestamp": now_ts
        })

    header = ["date", "ticker", "gap_pct", "volume", "timestamp"]

    # Detect existing header
    try:
        with open(path, "r") as f:
            first_line = f.readline().strip()
            has_header = first_line.lower().startswith("date,")
    except FileNotFoundError:
        has_header = False

    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if not has_header:
            writer.writeheader()
        writer.writerows(rows)
