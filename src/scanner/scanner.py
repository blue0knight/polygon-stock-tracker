from __future__ import annotations

# -------------------------------------------------------------------
# Scanner (final)
#  - Fetch → Enrich (incl. ATR) → Liquidity → Score → Final Pick
#  - Single CSV: today_pick.csv with FinalPick flag + rationale
#  - Debug mode via YAML (no code edits needed for weekends)
# -------------------------------------------------------------------

import os
import sys
import csv
import time
import yaml
import shutil
import logging
import pytz
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Core + adapters
from src.core.scoring import score_snapshots, log_top_movers
from src.core.output import write_watchlist
from src.adapters import polygon_adapter as pa
from src.adapters.polygon_adapter import fetch_snapshots


# -------------------------------------------------------------------
# Env / Config / Logger
# -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"
CONFIG_PATH = ROOT / "configs" / "scanner.yaml"

print(f"DEBUG: Expecting .env at {ENV_PATH}")
load_dotenv(ENV_PATH)

if not os.getenv("POLYGON_API_KEY"):
    raise RuntimeError(f"❌ POLYGON_API_KEY not loaded. Expected in {ENV_PATH}")
print("DEBUG: POLYGON_API_KEY loaded ✓")


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


## -------------------------------------------------------------------
## BLOCK: dated-logger  |  FILE: src/scanner/scanner.py  |  DATE: 2025-09-29
## PURPOSE: Write logs to logs/scanner_YYYY-MM-DD.log; prevent duplicate handlers
## NOTES:
##   - Uses cfg["output"]["log"] only to determine the directory.
##   - If cfg points to a file (e.g., logs/scanner.log), we keep that *directory*
##     and replace the filename with scanner_<today>.log.
## -------------------------------------------------------------------
def setup_logger(log_path: str) -> logging.Logger:
    # Resolve directory to place the dated log file
    log_path = Path(log_path)
    log_dir = log_path.parent if log_path.suffix else log_path
    log_dir.mkdir(parents=True, exist_ok=True)

    # Build dated filename
    today_str = datetime.now().strftime("%Y-%m-%d")
    dated_file = log_dir / f"scanner_{today_str}.log"

    logger = logging.getLogger("scanner")
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers on repeated invocations
    if not any(
        isinstance(h, logging.FileHandler)
        and getattr(h, "baseFilename", "") == str(dated_file)
        for h in logger.handlers
    ):
        fh = logging.FileHandler(dated_file, mode="a", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)

    return logger


# -------------------------------------------------------------------
# Time helpers
# -------------------------------------------------------------------
## -------------------------------------------------------------------
## BLOCK: premarket-cap-0930  |  FILE: src/scanner/scanner.py  |  DATE: 2025-09-29
## PURPOSE: Ensure premarket loop always stops at 09:30 ET, regardless of YAML end_time
## -------------------------------------------------------------------
## -------------------------------------------------------------------
## PATCH: premarket-window-respect-yaml
## FILE: src/scanner/scanner.py
## PURPOSE: Allow YAML end_time to extend beyond 09:30 if explicitly set.
## NOTES:
##   - Default behavior (no YAML override): still capped at 09:30.
##   - If YAML end_time > 09:30, we respect YAML (useful for testing / noon extension).
## -------------------------------------------------------------------
def within_premarket_window(cfg: dict) -> bool:
    tz = pytz.timezone("America/New_York")
    now = datetime.now(tz)

    # Times from YAML
    start_cfg = datetime.strptime(cfg["premarket"]["start_time"], "%H:%M").time()
    end_cfg   = datetime.strptime(cfg["premarket"]["end_time"], "%H:%M").time()

    # Default cap at 09:30
    cap0930 = datetime.strptime("09:30", "%H:%M").time()

    # Respect YAML if explicitly set later than 09:30
    effective_end = end_cfg if end_cfg > cap0930 else cap0930

    start_dt = tz.localize(datetime.combine(now.date(), start_cfg))
    end_dt   = tz.localize(datetime.combine(now.date(), effective_end))

    return start_dt <= now <= end_dt


def is_final_pick_time() -> bool:
    tz = pytz.timezone("America/New_York")
    return datetime.now(tz).strftime("%H:%M") == "09:50"


## -------------------------------------------------------------------
## BLOCK: open-selection-window  |  FILE: src/scanner/scanner.py
## PURPOSE: True only during the 09:30–09:35 ET selection window (configurable)
## -------------------------------------------------------------------
def within_open_selection_window(cfg: dict) -> bool:
    tz = pytz.timezone("America/New_York")
    now = datetime.now(tz)

    # Configurable window, default "09:30-09:35"
    win = (cfg.get("open_selection", {}) or {}).get("selection_window", "09:30-09:35")
    try:
        start_s, end_s = win.split("-")
        start_t = datetime.strptime(start_s.strip(), "%H:%M").time()
        end_t   = datetime.strptime(end_s.strip(), "%H:%M").time()
    except Exception:
        start_t = datetime.strptime("09:30", "%H:%M").time()
        end_t   = datetime.strptime("09:35", "%H:%M").time()

    start_dt = tz.localize(datetime.combine(now.date(), start_t))
    end_dt   = tz.localize(datetime.combine(now.date(), end_t))
    return start_dt <= now <= end_dt


## -------------------------------------------------------------------
## BLOCK: prefilter-top-gappers-v2  |  FILE: src/scanner/scanner.py  |  DATE: 2025-09-29
## PURPOSE: Rank by %Gap using robust snapshot fields:
##   - Prefer last_price; fallback to close (regular session close)
##   - Require prev_close > 0; enforce min_price on chosen price
##   - Adds basic diagnostics to help explain empty pools
## -------------------------------------------------------------------
def prefilter_top_gappers(snaps: list[dict], n: int = 100, min_price: float = 1.0) -> list[dict]:
    pool = []
    skipped_missing = 0
    skipped_price   = 0
    for s in snaps or []:
        # choose a price: last_price (preferred), else close
        last = s.get("last_price")
        close = s.get("close")
        price = last if last is not None else close

        prev = s.get("prev_close")
        if price is None or prev is None or prev <= 0:
            skipped_missing += 1
            continue
        try:
            price_f = float(price)
            prev_f  = float(prev)
        except Exception:
            skipped_missing += 1
            continue

        if price_f < float(min_price):
            skipped_price += 1
            continue

        try:
            gap = (price_f - prev_f) / prev_f * 100.0
        except Exception:
            skipped_missing += 1
            continue

        s2 = dict(s)
        s2["_gap_pct_snapshot"] = gap
        s2["_prefilter_price"]  = price_f  # for optional debugging
        pool.append(s2)

    pool.sort(key=lambda x: x.get("_gap_pct_snapshot", 0.0), reverse=True)

    # Optional: quick diagnostic line if pool ends up empty (uses global logger if present)
    try:
        logger = logging.getLogger("scanner")
        if not pool:
            logger.info(f"ℹ️ [Open] Prefilter diagnostics: skipped_missing={skipped_missing}, skipped_price={skipped_price}")
    except Exception:
        pass

    return pool[:n]


## -------------------------------------------------------------------
## BLOCK: group-watchlist-log  |  FILE: src/scanner/scanner.py
## PURPOSE: Log a configurable group watchlist using snapshot fields only
## NOTES: Logs only (no CSV, no enrichment). Fast: pure in-memory lookup.
## -------------------------------------------------------------------
def _fmt_num(x, d=2):
    try:
        return f"{float(x):.{d}f}"
    except Exception:
        return "?"

def _fmt_gap(p, prev):
    try:
        p, prev = float(p), float(prev)
        if prev <= 0:
            return "n/a"
        return f"{((p - prev) / prev) * 100.0:+.1f}%"
    except Exception:
        return "n/a"

def _fmt_vol(v):
    try:
        v = int(v or 0)
        if v >= 1_000_000:
            return f"{v/1_000_000:.1f}M"
        if v >= 1_000:
            return f"{v/1_000:.1f}K"
        return str(v)
    except Exception:
        return "0"

def log_group_watchlist(cfg: dict, snaps: list[dict], logger: logging.Logger) -> None:
    symbols = (cfg.get("group_watchlist") or [])
    if not symbols:
        return

    # build quick index by ticker
    by_sym = {}
    for s in snaps or []:
        sym = s.get("ticker")
        if sym:
            by_sym[sym] = s

    logger.info("📋 Group Watchlist:")
    for sym in symbols:
        s = by_sym.get(sym)
        if not s:
            logger.info(f"   {sym}: (no snapshot)")
            continue

        last = s.get("last_price")
        close = s.get("close")
        prev  = s.get("prev_close")
        price = last if last not in (None, 0) else close

        gap_str = _fmt_gap(price, prev) if (price and prev) else "n/a"
        last_str = _fmt_num(price, 2)
        prev_str = _fmt_num(prev, 2)
        vol_str  = _fmt_vol(s.get("volume"))

        logger.info(f"   {sym}: gap={gap_str} last={last_str} prev={prev_str} vol={vol_str}")

# -------------------------------------------------------------------
# CSV bootstrap / append
# -------------------------------------------------------------------
CSV_FIELDS = [
    "date",
    "time",
    "ticker",
    "gap_pct",
    "rvol",
    "atr_stretch",
    "premarket_high",
    "open_price",
    "score",
    "final_pick",
    "rationale",
]


def ensure_today_pick_ready(cfg: dict, reset: bool = True) -> Path:
    """Reset output/today_pick.csv from schemas/today_pick_template.csv (keeps headers correct)."""
    out_path = Path(cfg["output"].get("today_pick", "output/today_pick.csv"))
    tpl_path = ROOT / "schemas" / "today_pick_template.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if reset or not out_path.exists():
        shutil.copyfile(tpl_path, out_path)
    return out_path


def append_row(row: dict, cfg: dict) -> None:
    csv_path = Path(cfg["output"].get("today_pick", "output/today_pick.csv"))
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = csv_path.exists()
    with csv_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        # write row with only expected fields (order guaranteed by CSV_FIELDS)
        writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})


# -------------------------------------------------------------------
# Enrichment (adds prev_close, ATR, gap %, RVOL, ATR_Stretch)
# -------------------------------------------------------------------
from datetime import datetime
import pytz


def enrich_rows(
    snapshots: list[dict], trade_date: str, cfg: dict | None = None
) -> list[dict]:
    """
    snapshots: list of dicts from fetch_snapshots(); must include "ticker".
    Returns rows enriched for scoring & CSV output.
    """
    enriched: list[dict] = []
    for s in snapshots:
        tkr = s.get("ticker")
        if not tkr:
            continue

        prev_close = pa.get_previous_close(tkr)
        pm_high = pa.get_premarket_high(tkr, trade_date)
        atr_14 = pa.get_atr_14(tkr, trade_date)

        # Pull intraday/avg volumes from adapter
        intraday_vol = pa.get_intraday_volume(tkr, trade_date)
        avg_vol = pa.get_avg_daily_volume(tkr, lookback=20)

        # Prices: prefer snapshot last_price if present; fall back gracefully
        last_price = s.get("last_price") or prev_close or 0.0
        open_price = last_price  # TODO: replace with pa.get_open_price_0930 later

        gap_pct = (
            ((open_price - prev_close) / prev_close * 100.0) if prev_close else None
        )
        rvol = (intraday_vol / avg_vol) if avg_vol else None
        atr_stretch = ((last_price - prev_close) / atr_14) if atr_14 else None

        enriched.append(
            {
                "date": trade_date,
                "time": datetime.now().strftime("%H:%M"),
                "ticker": tkr,
                "premarket_high": pm_high,
                "open_price": open_price,
                "last_price": last_price,
                "intraday_volume": intraday_vol,
                "avg_daily_volume": avg_vol,
                "prev_close": prev_close,
                "gap_pct": round(gap_pct, 2) if gap_pct is not None else "",
                "rvol": round(rvol, 2) if rvol is not None else "",
                "atr_14": atr_14 if atr_14 else "",
                "atr_stretch": round(atr_stretch, 2) if atr_stretch is not None else "",
            }
        )
    return enriched


# -------------------------------------------------------------------
# Liquidity filters (session-aware)
# -------------------------------------------------------------------
def _dollar_volume(row: dict) -> float:
    try:
        return float(row.get("last_price", 0)) * int(row.get("intraday_volume", 0))
    except Exception:
        return 0.0


## -------------------------------------------------------------------
## BLOCK: liq-select-with-session  |  FILE: src/scanner/scanner.py  |  DATE: 2025-09-29
## PURPOSE: Return both thresholds and the session label ("premarket"/"regular")
## -------------------------------------------------------------------
def get_liquidity_cfg(cfg: dict) -> tuple[dict, str]:
    ny = pytz.timezone("America/New_York")
    now_et = datetime.now(ny)
    session = (
        "premarket"
        if (now_et.hour < 9 or (now_et.hour == 9 and now_et.minute < 30))
        else "regular"
    )

    liq_root = cfg.get("liquidity", {})
    if session in liq_root:
        return liq_root[session], session
    # Fallback if dual blocks not present
    return liq_root, session

## -------------------------------------------------------------------
## PATCH: liq-apply-session-log (FIX TUPLE UNPACK) 
## FILE: src/scanner/scanner.py
## PURPOSE: Unpack (liq_cfg, session) and log correctly
## -------------------------------------------------------------------
def apply_liquidity_filters(
    rows: list[dict], cfg: dict, logger: logging.Logger | None = None
) -> list[dict]:
    liq_cfg, session = get_liquidity_cfg(cfg)
    out: list[dict] = []
    dropped = {"missing_prices": 0, "price_floor": 0, "shares": 0, "avg": 0, "dollar": 0}

    for r in rows:
        last = r.get("last_price")
        prev = r.get("prev_close")

        if liq_cfg.get("require_prices", True) and (not last or not prev or prev == 0):
            dropped["missing_prices"] += 1
            continue
        if float(last or 0.0) < float(liq_cfg.get("min_price", 0.0)):
            dropped["price_floor"] += 1
            continue
        if int(r.get("intraday_volume", 0) or 0) < int(liq_cfg.get("min_intraday_shares", 0)):
            dropped["shares"] += 1
            continue
        if int(r.get("avg_daily_volume", 0) or 0) < int(liq_cfg.get("min_avg_daily_volume", 0)):
            dropped["avg"] += 1
            continue
        if _dollar_volume(r) < float(liq_cfg.get("min_dollar_volume", 0.0)):
            dropped["dollar"] += 1
            continue

        out.append(r)

    if logger:
        logger.info(f"💧 Liquidity gate ({session}): {len(out)}/{len(rows)} passed (dropped {dropped})")
    return out

# -------------------------------------------------------------------
# Main loop (premarket) and one-shot entrypoint
# -------------------------------------------------------------------
def _final_pick_row(base: dict, score: float, final: bool, rationale: str) -> dict:
    """Map a scored/enriched item to the CSV schema row."""
    return {
        "date": base.get("date", ""),
        "time": base.get("time", datetime.now().strftime("%H:%M")),
        "ticker": base.get("ticker", ""),
        "gap_pct": base.get("gap_pct", ""),
        "rvol": base.get("rvol", ""),
        "atr_stretch": base.get("atr_stretch", ""),
        "premarket_high": base.get("premarket_high", ""),
        "open_price": base.get("open_price", ""),
        "score": round(score, 3) if isinstance(score, (int, float)) else score,
        "final_pick": "TRUE" if final else "FALSE",
        "rationale": rationale or "",
    }


def _pick_winner(scored: list[dict]) -> dict | None:
    """Select winner as top-scored row (assumes score_snapshots returned 'score' on each)."""
    if not scored:
        return None
    return max(scored, key=lambda r: r.get("score", float("-inf")))

## -------------------------------------------------------------------
## BLOCK: scoring-adapter  |  FILE: src/scanner/scanner.py  |  DATE: 2025-09-29
## PURPOSE: Call core.scoring.score_snapshots safely and normalize output.
## RETURNS: (scored_rows_sorted, winner_row)
## -------------------------------------------------------------------
def score_and_pick(filtered: list[dict], cfg: dict, logger: logging.Logger) -> tuple[list[dict], dict | None]:
    def _local_score(row: dict) -> float:
        w = cfg.get("scoring_weights", {})
        w_gap = float(w.get("gap_percent", 0.4))
        w_rvol = float(w.get("rvol", 0.3))
        w_atr  = float(w.get("atr_stretch", 0.2))
        gap = float(row.get("gap_pct") or 0.0)
        rvol = float(row.get("rvol") or 0.0)
        atrs = float(row.get("atr_stretch") or 0.0)
        return (w_gap * gap) + (w_rvol * min(rvol, 5.0)) + (w_atr * min(atrs, 5.0))

    # Build the dict shape some score_snapshots implementations expect
    snap_dict = {r.get("ticker"): r for r in filtered if r.get("ticker")}
    if not snap_dict:
        return [], None

    scored_rows: list[dict] = []
    try:
        t0 = time.time()
        try:
            scored_out = score_snapshots(snap_dict)  # prefer single-arg API
        except TypeError:
            scored_out = score_snapshots(snap_dict, cfg.get("scoring_weights", {}))
        dt = time.time() - t0
        logger.info(f"🏎️ Scoring completed in {dt:.2f}s for {len(filtered)} candidates")

        # Normalize to list[dict] with 'score'
        if isinstance(scored_out, dict):
            for tkr, val in scored_out.items():
                base = snap_dict.get(tkr, {}).copy()
                if isinstance(val, dict):
                    base.update(val)
                    if "score" not in base and "score" in val:
                        base["score"] = val["score"]
                else:
                    base["score"] = float(val)
                scored_rows.append(base)

        elif isinstance(scored_out, list):
            for item in scored_out:
                if isinstance(item, dict):
                    tkr = item.get("ticker")
                    base = snap_dict.get(tkr, {}).copy() if tkr else {}
                    base.update(item)
                    if "score" not in base:
                        base["score"] = _local_score(base)
                    scored_rows.append(base)
                elif isinstance(item, (tuple, list)) and len(item) >= 2:
                    tkr, score_val = item[0], item[1]
                    base = snap_dict.get(tkr, {}).copy()
                    base["score"] = float(score_val) if score_val is not None else _local_score(base)
                    scored_rows.append(base)
        else:
            # Unknown return type: compute local scores
            for tkr, base in snap_dict.items():
                row = base.copy()
                row["score"] = _local_score(row)
                scored_rows.append(row)

    except Exception as e:
        logger.error(f"❌ Scoring adapter failed, using local scores: {e}", exc_info=True)
        for tkr, base in snap_dict.items():
            row = base.copy()
            row["score"] = _local_score(row)
            scored_rows.append(row)

    if not scored_rows:
        return [], None

    scored_rows.sort(key=lambda r: float(r.get("score") or 0.0), reverse=True)
    winner = scored_rows[0]
    return scored_rows, winner

## -------------------------------------------------------------------
## BLOCK: run-once-patched  |  FILE: src/scanner/scanner.py  |  DATE: 2025-09-29
## PURPOSE: Ensure apply_liquidity_filters sees full cfg (not cfg["liquidity"])
## NOTES:
##   - Fixes bug where all rows were dropped silently
##   - Now get_liquidity_cfg(cfg) can choose premarket vs regular
## -------------------------------------------------------------------
def run_once(cfg: dict, logger: logging.Logger, force_final_pick: bool = False) -> None:
    """Single pass (used by --once and by the loop)."""
    today = datetime.now().strftime("%Y-%m-%d")
    ensure_today_pick_ready(cfg, reset=False)  # keep file; created earlier

    # --- Debug mode: always inject dummy row, skip rest ---
    if cfg.get("debug", {}).get("enable", False):
        dbg = cfg["debug"]
        dummy = {
            "date": today,
            "time": datetime.now().strftime("%H:%M"),
            "ticker": dbg["dummy_ticker"],
            "gap_pct": dbg["dummy_gap"],
            "rvol": 1.0,
            "atr_stretch": 1.0,
            "premarket_high": 0,
            "open_price": dbg["dummy_price"],
        }
        row = _final_pick_row(
            dummy,
            score=dbg["dummy_score"],
            final=True,
            rationale=dbg.get("rationale", "Debug"),
        )
        append_row(row, cfg)
        logger.info(
            f"⚠️ Debug: Appended dummy Final Pick -> {cfg['output'].get('today_pick', 'output/today_pick.csv')}"
        )
        return

    # --- Normal path ---
    snaps = fetch_snapshots(limit=50000)
    logger.info(f"📡 Snapshots fetched: {len(snaps)} tickers")

    # CALL: group-watchlist (logs only)
    try:
        log_group_watchlist(cfg, snaps, logger)
    except Exception as e:
        logger.warning(f"[GROUP] failed to log watchlist: {e}")


    # --- NEW: Premarket short-circuit ---
    ny = pytz.timezone("America/New_York")
    now_et = datetime.now(ny)
    if now_et.hour < 9 or (now_et.hour == 9 and now_et.minute < 30):
        # Just compute raw %Gap from bulk feed
        def _best_price_from_snapshot(s: dict):
            # Order matters: last_price (extended ok) → day.c → day.o → day.h → day.l
            # We already mapped these into snapshot keys: last_price, close, open, high, low
            for k in ("last_price", "close", "open", "high", "low"):
                v = s.get(k)
                try:
                    v = float(v)
                    if v > 0:
                        return v
                except Exception:
                    pass
            return None

        top = []
        for s in snaps or []:
            prev = s.get("prev_close")
            price = _best_price_from_snapshot(s)
            try:
                prev = float(prev) if prev is not None else None
            except Exception:
                prev = None
            if price is None or prev is None or prev <= 0:
                continue
            try:
                gap = (price - prev) / prev * 100.0
                top.append((s.get("ticker", ""), gap))
            except Exception:
                continue



        if top5:
            pretty = ", ".join([f"{t} ({g:+.1f}%)" for t, g in top5])
            logger.info(f"🏁 Premarket Top 5 by %Gap: {pretty}")
            return  # 👈 exit early, normal case

        # -------------------------------------------------------------------
        # PATCH: premarket-fallback | FILE: src/scanner/scanner.py
        # DATE: 2025-09-30
        # PURPOSE: Guarantee "always shows something" premarket
        # -------------------------------------------------------------------
        fallback = []
        for s in snaps or []:
            # pick best available price
            price = None
            for k in ("last_price", "close", "open", "high", "low"):
                v = s.get(k)
                try:
                    v = float(v)
                    if v > 0:
                        price = v
                        break
                except Exception:
                    continue

            prev = s.get("prev_close")
            try:
                prev = float(prev) if prev is not None else None
            except Exception:
                prev = None

            if price is None or prev is None or prev <= 0:
                continue
            try:
                gap = (price - prev) / prev * 100.0
                fallback.append((s.get("ticker", ""), gap))
            except Exception:
                continue

        fallback.sort(key=lambda x: x[1], reverse=True)
        top5_fallback = fallback[:5]
        if top5_fallback:
            pretty = ", ".join([f"{t} ({g:+.1f}%)" for t, g in top5_fallback])
            logger.info(f"🏁 [Fallback] Premarket Top 5 by %Gap: {pretty}")
        else:
            logger.info("🏁 [Fallback] Premarket Top 5 by %Gap: (still empty)")
        return  # 👈 always exit after logging





    ## -------------------------------------------------------------------
    ## BLOCK: hybrid-snapshot-enrich  |  FILE: src/scanner/scanner.py  |  DATE: 2025-09-30
    ## PURPOSE: Combine fast fetch_snapshots() with per-ticker snapshots for top movers
    ## NOTES:
    ##   - Keeps performance (bulk scan of 11k+)
    ##   - Restores premarket coverage with Polygon per-ticker snapshot (lastTrade)
    ##   - Replaces `snaps` with enriched list for downstream logic
    ## -------------------------------------------------------------------
    rough = []
    for s in snaps:
        sym = s.get("ticker")
        prev = s.get("prev_close") or 0
        last = s.get("last_price") or 0
        if prev > 0 and last:
            rough_gap = (last - prev) / prev * 100.0
        else:
            rough_gap = 0
        rough.append((rough_gap, sym, prev, last))

    # Sort by rough gap and take top 500 for enrichment
    rough.sort(key=lambda r: r[0], reverse=True)
    top_syms = [sym for _, sym, _, _ in rough[:50]]

    logger.info(f"[HYBRID] Enriching top {len(top_syms)} tickers with per-ticker snapshots")

    enriched = []
    for sym in top_syms:
        try:
            snap = pa.get_snapshot(sym)  # per-ticker snapshot (extended hours included)
            prev = snap.get("prevDay", {}).get("close")
            pre  = snap.get("lastTrade", {}).get("p")
            if prev and pre:
                gap = (pre - prev) / prev * 100.0
                enriched.append({
                    "ticker": sym,
                    "gap_percent": gap,
                    "premarket_price": pre,
                    "prev_close": prev
                })
        except Exception as e:
            logger.warning(f"[HYBRID] Failed per-ticker snapshot for {sym}: {e}")

    # Replace snaps for downstream processing
    snaps = enriched

    logger.info("[HYBRID] Top 5 enriched gappers:")
    for s in snaps[:5]:
        logger.info(f"   {s['ticker']}: {s['premarket_price']} vs {s['prev_close']} gap={s['gap_percent']:.2f}%")
    ## -------------------------------------------------------------------
    ## END BLOCK: hybrid-snapshot-enrich
    ## -------------------------------------------------------------------
        

    # -------------------------------------------------------------------
    # BLOCK: gap-sanity-locals  |  FILE: src/scanner/scanner.py  |  DATE: 2025-09-30
    # PURPOSE: List available local variable names to locate snapshot universe
    # -------------------------------------------------------------------
    try:
        logger.info(f"[GAP-SANITY] Locals keys: {list(locals().keys())}")
    except Exception as e:
        logger.warning(f"[GAP-SANITY] Error listing locals: {e}")


    # -------------------------------------------------------------------
    # BLOCK: gap-sanity-lite  |  FILE: src/scanner/scanner.py  |  DATE: 2025-09-30
    # PURPOSE: Quick check: show first 2 entries from snaps (premarket feed)
    # -------------------------------------------------------------------
    try:
        logger.info(f"[GAP-SANITY] Type of snaps: {type(snaps)}")
        logger.info(f"[GAP-SANITY] Raw dump of first 2 snaps: {snaps[:2]}")
    except Exception as e:
        logger.warning(f"[GAP-SANITY] Error accessing snaps: {e}")



    # -------------------------------------------------------------------
    # BLOCK: debug-gap-sanity  |  FILE: src/scanner/scanner.py  |  DATE: 2025-09-30
    # PURPOSE: Log raw top gap leaders BEFORE filters to diagnose "(no candidates)"
    # ANCHOR: place right AFTER the "📡 Snapshots fetched:" log
    # NOTES:
    #   - Zero-impact: only runs when configs/scanner.yaml -> debug.enable = true
    #   - Auto-detects common universe variable names to avoid code churn
    # -------------------------------------------------------------------
    if cfg.get("debug", {}).get("enable"):
        try:
            _lx = locals()
            universe = (_lx.get("snapshots")
                        or _lx.get("all_tickers")
                        or _lx.get("universe")
                        or _lx.get("tickers"))
            if not universe:
                logger.warning("[DEBUG] Could not find universe list; expected one of: snapshots, all_tickers, universe, tickers")
            else:
                def _get(o, *names):
                    if isinstance(o, dict):
                        for n in names:
                            if n in o:
                                return o[n]
                    for n in names:
                        v = getattr(o, n, None)
                        if v is not None:
                            return v
                    return None

                def _to_f(x):
                    try:
                        return float(x)
                    except Exception:
                        return None

                rows = []
                for o in universe:
                    sym = _get(o, "symbol", "ticker", "sym")
                    prev = _to_f(_get(o, "prev_close", "previousClose", "prevClose", "close_yesterday"))
                    pre  = _to_f(_get(o, "premarket_price", "pre", "pre_market_price", "preMarketPrice", "last", "price"))
                    gap  = _get(o, "gap_percent", "gap", "gapPct")
                    gap  = _to_f(gap)
                    if gap is None and prev and pre and prev > 0:
                        gap = (pre - prev) / prev * 100.0
                    adv  = _to_f(_get(o, "avg_daily_volume", "avgVolume", "average_volume"))
                    sh   = _to_f(_get(o, "intraday_shares", "shares", "volume"))
                    dvol = _to_f(_get(o, "dollar_volume", "dollarVol", "dvol"))

                    # Only keep rows where we have some gap value
                    if gap is not None:
                        rows.append((gap, sym, pre, prev, sh, adv, dvol))

                if rows:
                    rows.sort(key=lambda r: r[0], reverse=True)
                    logger.info("[DEBUG] Raw top 10 by gap%% (pre-filters; computed if missing):")
                    for gap, sym, pre, prev, sh, adv, dvol in rows[:10]:
                        logger.info(f"   {sym}: gap={gap:.2f}% pre={pre} prev={prev} sh={sh} adv={adv} $vol={dvol}")
                else:
                    logger.info("[DEBUG] No rows with computable gap%% (premarket price / prev_close missing?)")
        except Exception as e:
            logger.exception(f"[DEBUG] gap-sanity block error: {e}")
    # -------------------------------------------------------------------


    # PREMARKET BRANCH: log Top-5 by %Gap only, skip enrichment/filters
    ny = pytz.timezone("America/New_York")
    now_et = datetime.now(ny)
    is_premarket = (now_et.hour < 9) or (now_et.hour == 9 and now_et.minute < 30)
    if is_premarket:
        # compute %Gap from snapshot fields only
        top = []
        for s in snaps:
            last = s.get("last_price")
            prev = s.get("prev_close")
            if last and prev and prev > 0:
                try:
                    gap = (float(last) - float(prev)) / float(prev) * 100.0
                    top.append((s.get("ticker", ""), gap))
                except Exception:
                    continue

        top.sort(key=lambda x: x[1], reverse=True)
        top5 = top[:5]
        if logger:
            if top5:
                pretty = ", ".join([f"{t} ({g:+.1f}%)" for t, g in top5])
                logger.info(f"🏁 Premarket Top 5 by %Gap: {pretty}")
            else:
                logger.info("🏁 Premarket Top 5 by %Gap: (no candidates)")

        return  # IMPORTANT: no enrichment/filters in premarket

    try:
        enriched = enrich_rows(snaps, today) if snaps else []
        if logger:
            logger.info(f"🧪 Enrichment produced {len(enriched)} rows")
    except Exception as e:
        logger.error(f"❌ Enrichment failed: {e}", exc_info=True)
        enriched = []

    try:
        filtered = apply_liquidity_filters(enriched, cfg, logger) if enriched else []
        if logger:
            logger.info(
                f"💧 Liquidity result: {len(filtered)} passed out of {len(enriched)}"
            )
    except Exception as e:
        logger.error(f"❌ Liquidity filter failed: {e}", exc_info=True)
        filtered = []

    # PATCH: pass full cfg, not cfg["liquidity"]
    filtered = apply_liquidity_filters(enriched, cfg, logger) if enriched else []

    if not filtered:
        logger.warning(
            "No tickers passed liquidity filters — skipping scoring/final pick."
        )
        return

    # Score + log movers
    scored = score_snapshots(filtered)
    log_top_movers(scored, n=5)

    # Watchlist
    write_watchlist(cfg["output"]["watchlist"], scored[:5], cfg["targets"])

    # Final pick decision
    do_final = force_final_pick or is_final_pick_time()
    if not do_final:
        return

    winner = _pick_winner(scored)
    if not winner:
        logger.warning("⚠️ No winner after scoring.")
        return

    row = _final_pick_row(
        winner,
        score=winner.get("score", ""),
        final=True,
        rationale="",
    )
    append_row(row, cfg)
    logger.info(f"[PRE] 📌 Final Pick: {row['ticker']} (score={row['score']})")

## -------------------------------------------------------------------
## BLOCK: open-selection-pass  |  FILE: src/scanner/scanner.py
## PURPOSE: One pass after 09:30 — enrich candidates, filter, score, write Pick of the Day
## -------------------------------------------------------------------
def run_open_selection_once(cfg: dict, logger: logging.Logger) -> None:
    # Only act inside the configured window
    if not within_open_selection_window(cfg):
        logger.info("Open selection window not active — skipping open selection pass.")
        return

    # Fetch full snapshots (cheap)
    snaps = fetch_snapshots(limit=50000)
    logger.info(f"📡 [Open] Snapshots fetched: {len(snaps)} tickers")

    # CALL: group-watchlist during open window (logs only)
    try:
        log_group_watchlist(cfg, snaps, logger)
    except Exception as e:
        logger.warning(f"[GROUP][Open] failed to log watchlist: {e}")


    # Candidate pool (Top-N by %Gap from snapshots)
    pool_n = int((cfg.get("open_selection", {}) or {}).get("candidate_pool_size", 100))
    candidates = prefilter_top_gappers(snaps, n=pool_n, min_price=1.0)
    logger.info(f"⚡ [Open] Candidate pool from snapshots (Top {pool_n} by %Gap): {len(candidates)}")

    if not candidates:
        logger.warning("[Open] No candidates available for selection.")
        return

    # Enrich only the candidates
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        enriched = enrich_rows(candidates, today)
        logger.info(f"🧪 [Open] Enrichment produced {len(enriched)} rows")
    except Exception as e:
        logger.error(f"❌ [Open] Enrichment failed: {e}", exc_info=True)
        return

    # Regular-session liquidity (pass full cfg so session logic selects 'regular')
    try:
        filtered = apply_liquidity_filters(enriched, cfg, logger)
        logger.info(f"💧 [Open] Liquidity result: {len(filtered)}/{len(enriched)} passed")
    except Exception as e:
        logger.error(f"❌ [Open] Liquidity filter failed: {e}", exc_info=True)
        return

    if not filtered:
        logger.warning("[Open] No survivors after liquidity — no Pick of the Day.")
        return

    # -------------------------------------------------------------------
    # BLOCK: open-scoring-with-fallback  |  DATE: 2025-09-29
    # PURPOSE: Robust scoring + CSV write with timing and fallback pick
    # -------------------------------------------------------------------
    try:
        t0 = time.time()
        scored = score_snapshots(filtered)
        dt = time.time() - t0
        logger.info(f"🏎️ [Open] Scoring completed in {dt:.2f}s for {len(filtered)} candidates")

        # Log top-5 (by score) for visibility
        log_top_movers(scored, n=5)

        winner = _pick_winner(scored)
        if not winner:
            raise RuntimeError("No winner returned by scoring")

    except Exception as e:
        logger.error(f"❌ [Open] Scoring failed, using fallback: {e}", exc_info=True)
        # Fallback selection: prefer highest RVOL, then highest $ volume, then highest %gap
        def _safe_float(x):
            try: return float(x)
            except Exception: return 0.0
        def _safe_int(x):
            try: return int(x)
            except Exception: return 0

        def _dollar_vol(r):
            return _safe_float(r.get("last_price")) * _safe_int(r.get("intraday_volume"))

        def _gap_pct(r):
            g = r.get("gap_pct")
            return _safe_float(g) if g not in (None, "") else 0.0

        try:
            winner = max(
                filtered,
                key=lambda r: (
                    _safe_float(r.get("rvol")),      # 1) RVOL
                    _dollar_vol(r),                  # 2) Dollar volume
                    _gap_pct(r)                      # 3) % gap
                ),
            )
            logger.info("[Open] Fallback selected winner by RVOL → $vol → %gap.")
        except Exception as ee:
            logger.error(f"❌ [Open] Fallback selection failed: {ee}", exc_info=True)
            return

    # Persist Pick of the Day (either scored or fallback)
    try:
        row = _final_pick_row(
            winner,
            score=winner.get("score", ""),  # may be empty under fallback
            final=True,
            rationale="Pick of the Day at open",
        )
        append_row(row, cfg)
        logger.info(
            f"🏅 [Open] Pick of the Day: {row['ticker']} (score={row['score']}) → "
            f"{cfg['output'].get('today_pick', 'output/today_pick.csv')}"
        )
    except Exception as e:
        logger.error(f"❌ [Open] Write to CSV failed: {e}", exc_info=True)
        return

def run() -> None:
    cfg = load_config()
    logger = setup_logger(cfg["output"]["log"])
    cadence = int(cfg["premarket"]["cadence_minutes"])

    # Always reset/seed today_pick with the template at process start
    ensure_today_pick_ready(cfg, reset=True)
    logger.info("Starting premarket scanner loop...")

    while within_premarket_window(cfg):
        try:
            run_once(cfg, logger, force_final_pick=False)
        except Exception as e:
            logger.error(f"❌ Error during scan tick: {e}", exc_info=True)
        time.sleep(cadence * 60)

    logger.info("Premarket window closed.")

    # Single open-selection pass (09:30–09:35 ET)
    run_open_selection_once(cfg, logger)

    logger.info("Scanner stopped.")

# -------------------------------------------------------------------
# Entrypoint
# -------------------------------------------------------------------
# -------------------------------------------------------------------
# Entrypoint
# -------------------------------------------------------------------
if __name__ == "__main__":
    cfg = load_config()

    # Seed CSV at start for both modes
    ensure_today_pick_ready(cfg, reset=True)

    if "--once" in sys.argv:
        logger = setup_logger(cfg["output"]["log"])
        force = "--final-pick-now" in sys.argv
        try:
            run_once(cfg, logger, force_final_pick=force)
        except Exception as e:
            logger.error(f"❌ Error in --once run: {e}", exc_info=True)
    else:
        # IMPORTANT: do NOT set up logger here; run() will do it
        run()

