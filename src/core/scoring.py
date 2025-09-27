from __future__ import annotations

## -------------------------------------------------------------------
## Imports
## -------------------------------------------------------------------
from dataclasses import dataclass
from typing import Dict, List, Iterable, Optional
from datetime import datetime, time
from zoneinfo import ZoneInfo
import math

NY = ZoneInfo("America/New_York")

@dataclass
class Candidate:
    date: str                 # "YYYY-MM-DD"
    ticker: str
    premarket_high: float
    open_price: float
    last_price: float         # current price at evaluation
    intraday_volume: int
    avg_daily_volume: float   # e.g., 20D average
    prev_close: float
    has_catalyst: bool
    atr_14: float             # computed ATR(14)
    # Optional extras if you already have them in your pipeline
    gap_pct: Optional[float] = None
    rvol: Optional[float] = None
    atr_stretch: Optional[float] = None

def is_after_935_et(now: Optional[datetime] = None) -> bool:
    """Return True iff current ET time is >= 09:35:00."""
    now = now or datetime.now(tz=NY)
    return now.astimezone(NY).time() >= time(9, 35, 0)

def compute_gap_pct(prev_close: float, ref_price: float) -> float:
    """Gap % vs previous close using a reference price (e.g., last/indicative)."""
    if prev_close <= 0:
        return 0.0
    return (ref_price - prev_close) / prev_close * 100.0

def compute_rvol(intraday_volume: int, avg_daily_volume: float) -> float:
    """Relative volume (simple ratio)."""
    if avg_daily_volume <= 0:
        return 0.0
    return intraday_volume / avg_daily_volume

def compute_atr_stretch(current_price: float, prev_close: float, atr_value: float) -> float:
    """How many ATRs above previous close the current price is."""
    if atr_value <= 0:
        return 0.0
    return (current_price - prev_close) / atr_value

def passes_filters(c: Candidate, min_liquidity: int) -> bool:
    """Final-pick pre-filters: time, above PMH, liquidity."""
    if not is_after_935_et():
        return False
    if c.last_price <= c.premarket_high:  # must be trading above PMH
        return False
    if c.intraday_volume < min_liquidity:
        return False
    return True

def score_gap(gap_pct: float) -> float:
    # Cap at 100 to avoid 200% junk from dominating
    return max(0.0, min(gap_pct, 100.0))

def score_rvol(rvol: float) -> float:
    # Cap at 5x, scale so 5x == 50 points
    return min(max(rvol, 0.0), 5.0) * 10.0

def score_atr_stretch(stretch: float, threshold: float = 2.0) -> float:
    # If >= threshold (e.g., 2 ATR), return 0. Else a decreasing curve.
    if stretch >= threshold:
        return 0.0
    # normalize: stretch==0 => 100; stretch==threshold => 0
    return max(0.0, 1.0 - (stretch / threshold)) * 100.0

def score_catalyst(has_catalyst: bool) -> float:
    return 100.0 if has_catalyst else 0.0

def calculate_final_score(
    *,
    gap_pct: float,
    rvol: float,
    atr_stretch: float,
    has_catalyst: bool,
    weights: Dict[str, float],
) -> float:
    gap_score = score_gap(gap_pct)
    rvol_score = score_rvol(rvol)
    atr_score = score_atr_stretch(atr_stretch, threshold=max(0.0001, weights.get("atr_threshold", 2.0)))
    catalyst_score = score_catalyst(has_catalyst)

    return (
        gap_score   * weights.get("gap_percent", 0.4) +
        rvol_score  * weights.get("rvol", 0.3) +
        atr_score   * weights.get("atr_stretch", 0.2) +
        catalyst_score * weights.get("catalyst", 0.1)
    )

def select_final_pick(
    candidates: Iterable[Candidate],
    *,
    weights: Dict[str, float],
    min_liquidity: int,
) -> Optional[Dict[str, object]]:
    """
    Applies filters + scoring and returns a dict representing the winning row for CSV.
    Returns None if no valid candidate.
    """
    scored: List[Dict[str, object]] = []

    for c in candidates:
        if not passes_filters(c, min_liquidity=min_liquidity):
            continue

        # Derive metrics if not pre-populated
        gap_pct = c.gap_pct if c.gap_pct is not None else compute_gap_pct(c.prev_close, c.last_price)
        rvol = c.rvol if c.rvol is not None else compute_rvol(c.intraday_volume, c.avg_daily_volume)
        atr_stretch = c.atr_stretch if c.atr_stretch is not None else compute_atr_stretch(c.last_price, c.prev_close, c.atr_14)

        final_score = calculate_final_score(
            gap_pct=gap_pct,
            rvol=rvol,
            atr_stretch=atr_stretch,
            has_catalyst=c.has_catalyst,
            weights=weights,
        )

        reason_bits = []
        if c.last_price > c.premarket_high:
            reason_bits.append("Above PMH")
        if rvol >= 1.5:
            reason_bits.append(f"RVOL {rvol:.2f}x")
        if c.has_catalyst:
            reason_bits.append("Catalyst")
        reason = ", ".join(reason_bits) or "Rules satisfied"

        scored.append({
            "Date": c.date,
            "Ticker": c.ticker,
            "PremarketHigh": round(c.premarket_high, 4),
            "OpenPrice": round(c.open_price, 4),
            "PickPrice": round(c.last_price, 4),
            "GapPct": round(gap_pct, 2),
            "RVOL": round(rvol, 2),
            "ATRStretch": round(atr_stretch, 2),
            "Catalyst": bool(c.has_catalyst),
            "FinalScore": round(final_score, 2),
            "Reason": reason,
        })

    if not scored:
        return None

    # Highest final score wins
    scored.sort(key=lambda r: r["FinalScore"], reverse=True)
    return scored[0]

def score_snapshots(snap_dict: Dict[str, Dict]) -> List[Dict]:
    """Very simple scoring passthrough for compatibility with scanner."""
    rows = []
    for tkr, snap in snap_dict.items():
        rows.append({
            "ticker": tkr,
            "last_price": snap.get("last_price"),
            "prev_close": snap.get("prev_close"),
            "gap_pct": compute_gap_pct(snap.get("prev_close", 0) or 0, snap.get("last_price", 0) or 0),
            "volume": snap.get("volume", 0),
        })
    # Sort descending by gap_pct
    return sorted(rows, key=lambda r: r["gap_pct"], reverse=True)

def log_top_movers(rows: List[Dict], n: int = 5):
    """Log top N movers for debug/visibility."""
    print(f"Top {n} movers:")
    for r in rows[:n]:
        print(f"  {r['ticker']}: {r['gap_pct']:.2f}% gap, vol {r['volume']}")
