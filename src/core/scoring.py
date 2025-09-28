from __future__ import annotations

## -------------------------------------------------------------------
## Imports
## -------------------------------------------------------------------
from dataclasses import dataclass
from typing import Dict, List, Iterable, Optional
from datetime import datetime, time
from zoneinfo import ZoneInfo
import math
import logging
import pytz

NY = ZoneInfo("America/New_York")

## -------------------------------------------------------------------
## Candidate Model
## -------------------------------------------------------------------
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

## -------------------------------------------------------------------
## Time / Helper Functions
## -------------------------------------------------------------------
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

## -------------------------------------------------------------------
## Filters + Scoring
## -------------------------------------------------------------------
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
    return max(0.0, min(gap_pct, 100.0))

def score_rvol(rvol: float) -> float:
    return min(max(rvol, 0.0), 5.0) * 10.0  # Cap at 5x, scale so 5x == 50

def score_atr_stretch(stretch: float, threshold: float = 2.0) -> float:
    if stretch >= threshold:
        return 0.0
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

## -------------------------------------------------------------------
## Final Pick Selection
## -------------------------------------------------------------------
def select_final_pick(
    candidates: Iterable[Candidate],
    *,
    weights: Dict[str, float],
    min_liquidity: int,
) -> Optional[Dict[str, object]]:
    """Applies filters + scoring and returns a dict representing the winning row for CSV."""
    scored: List[Dict[str, object]] = []

    for c in candidates:
        if not passes_filters(c, min_liquidity=min_liquidity):
            continue

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

    scored.sort(key=lambda r: r["FinalScore"], reverse=True)
    return scored[0]

## -------------------------------------------------------------------
## Snapshot Scoring + Logging
## -------------------------------------------------------------------
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
    return sorted(rows, key=lambda r: r["gap_pct"], reverse=True)

def log_top_movers(scored, snapshots=None, n=5, tag=""):
    """
    Logs the top n movers with price, % move, and timestamp.
    Adds session tag ([PRE], [POST], [ONCE]).
    """
    logger = logging.getLogger("scanner")
    top = scored[:n]
    if not top:
        logger.warning(f"{tag} No movers available to log.")
        return

    logger.info(f"{tag} Top {n} movers by gap %:")
    tz = pytz.timezone("America/New_York")

    for row in top:
        if isinstance(row, tuple):
            # origin/main format: (ticker, gain)
            ticker, gain = row
            snap = snapshots.get(ticker, {}) if snapshots else {}
            price = snap.get("last_price") or snap.get("prev_close")
            ts = snap.get("timestamp") or snap.get("updated")
        else:
            # HEAD format: dict row
            ticker = row["ticker"]
            gain = row["gap_pct"]
            price = row.get("last_price") or row.get("prev_close")
            ts = None

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
