## -------------------------------------------------------------------
## Imports
## -------------------------------------------------------------------
import os
import sys
import time
import yaml
import logging
import pytz
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from dotenv import load_dotenv

from src.core.scoring import Candidate, select_final_pick, score_snapshots, log_top_movers
from src.core.output import write_final_pick, write_watchlist
from src.adapters.polygon_adapter import fetch_snapshots

## -------------------------------------------------------------------
## Environment Setup
##  - Loads .env for POLYGON_API_KEY
## -------------------------------------------------------------------
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
print(f"DEBUG: Expecting .env at {ENV_PATH}")

load_dotenv(ENV_PATH)

print(f"DEBUG: POLYGON_API_KEY after load_dotenv = {os.getenv('POLYGON_API_KEY')}")
if not os.getenv("POLYGON_API_KEY"):
    raise RuntimeError(f"❌ POLYGON_API_KEY not loaded. Expected in {ENV_PATH}")

from dotenv import load_dotenv

# Resolve project root (2 levels up from this file)
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_PATH)

if not os.getenv("POLYGON_API_KEY"):
    raise RuntimeError(f"❌ POLYGON_API_KEY not loaded. Expected in {ENV_PATH}")

## -------------------------------------------------------------------
## Config Loader
## -------------------------------------------------------------------
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../../configs/scanner.yaml")

def load_config(path=CONFIG_PATH):
    with open(path, "r") as f:
        return yaml.safe_load(f)

## -------------------------------------------------------------------
## Logger Setup
## -------------------------------------------------------------------
def setup_logger(log_path):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logging.basicConfig(
        filename=log_path,
        filemode="a",
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=logging.INFO
    )
    return logging.getLogger("scanner")

## -------------------------------------------------------------------
## Time Helpers
## -------------------------------------------------------------------
def within_premarket_window(cfg):
    tz = pytz.timezone("America/New_York")
    now = datetime.now(tz)

    start = datetime.combine(
        now.date(), datetime.strptime(cfg["premarket"]["start_time"], "%H:%M").time()
    )
    end = datetime.combine(
        now.date(), datetime.strptime(cfg["premarket"]["end_time"], "%H:%M").time()
    )

    start = tz.localize(start)
    end = tz.localize(end)

    return start <= now <= end

def is_final_pick_time():
    tz = pytz.timezone("America/New_York")
    now = datetime.now(tz)
    return now.strftime("%H:%M") == "09:50"

## -------------------------------------------------------------------
## Final Pick Utility
##  - Converts rows into Candidate objects
##  - Applies select_final_pick()
##  - Writes result to output/final_pick.csv
## -------------------------------------------------------------------
def finalize_pick_from_rows(rows, weights, min_liquidity):
    """
    rows: iterable of dicts from your today_pick feed or in-memory scan, containing at least:
      date, ticker, premarket_high, open_price, last_price, intraday_volume,
      avg_daily_volume, prev_close, has_catalyst, atr_14
    """
    candidates = []
    for r in rows:
        candidates.append(Candidate(
            date=r["date"],
            ticker=r["ticker"],
            premarket_high=float(r["premarket_high"]),
            open_price=float(r["open_price"]),
            last_price=float(r["last_price"]),
            intraday_volume=int(r["intraday_volume"]),
            avg_daily_volume=float(r["avg_daily_volume"]),
            prev_close=float(r["prev_close"]),
            has_catalyst=bool(r.get("has_catalyst", False)),
            atr_14=float(r["atr_14"]),
            # If you already have these computed upstream, pass them through:
            gap_pct=r.get("gap_pct"),
            rvol=r.get("rvol"),
            atr_stretch=r.get("atr_stretch"),
        ))

    winner = select_final_pick(
        candidates,
        weights=weights,
        min_liquidity=min_liquidity,
    )
    if winner:
        write_final_pick(winner, path="output/final_pick.csv")
        return winner
    return None

## -------------------------------------------------------------------
## Row Enrichment Utility
##  - Takes simple scored snapshots
##  - Adds premarket high, intraday vol, catalysts, etc.
## -------------------------------------------------------------------
from src.adapters import polygon_adapter as pa

def enrich_rows(rows, trade_date: str):
    enriched = []
    for r in rows:
        tkr = r["ticker"]
        enriched.append({
            "date": trade_date,
            "ticker": tkr,
            "premarket_high": pa.get_premarket_high(tkr, trade_date),
            "open_price": r.get("last_price") or r.get("prev_close"),  # fallback
            "last_price": r.get("last_price") or 0,
            "intraday_volume": pa.get_intraday_volume(tkr, trade_date),
            "avg_daily_volume": pa.get_avg_daily_volume(tkr, lookback=20),
            "prev_close": r.get("prev_close") or 0,
            "has_catalyst": (
                pa.has_recent_news(tkr, days=1)
                or pa.has_earnings_today(tkr, trade_date)
            ),
            "atr_14": 1.0,  # placeholder until ATR calc wired
            "gap_pct": r.get("gap_pct"),
        })
    return enriched

def _get_liq_cfg(cfg):
    """Backwards-compatible loader: prefers cfg['liquidity'], falls back to top-level min_liquidity."""
    liq = (cfg or {}).get("liquidity", {}) or {}
    return {
        "min_intraday_shares": int(liq.get("min_intraday_shares", cfg.get("min_liquidity", 100_000))),
        "min_avg_daily_volume": int(liq.get("min_avg_daily_volume", 0)),
        "min_dollar_volume": float(liq.get("min_dollar_volume", 0)),
        "min_price": float(liq.get("min_price", 0)),
        "require_prices": bool(liq.get("require_prices", True)),
    }

def _dollar_volume(row):
    last = row.get("last_price") or row.get("last")
    vol = row.get("intraday_volume", 0) or 0
    try:
        return float(last) * int(vol)
    except Exception:
        return 0.0

## -------------------------------------------------------------------
## Liquidity Filters
## -------------------------------------------------------------------
## - Loads liquidity thresholds from config (with fallback to min_liquidity)
## - Computes dollar volume
## - Drops rows missing prices or failing liquidity rules
## - Logs stats on dropped vs passed
## -------------------------------------------------------------------
def apply_liquidity_filters(rows: list[dict], liq_cfg: dict, logger=None) -> list[dict]:
    """
    Filter enriched rows based on liquidity & data quality.
    Requires fields typically set by enrich_rows:
      - last_price (or last)
      - prev_close
      - intraday_volume
      - avg_daily_volume
    """
    if not rows:
        return []

    min_shares = liq_cfg["min_intraday_shares"]
    min_avg   = liq_cfg["min_avg_daily_volume"]
    min_px    = liq_cfg["min_price"]
    min_dv    = liq_cfg["min_dollar_volume"]
    need_px   = liq_cfg["require_prices"]

    out = []
    dropped_stats = {"missing_prices":0, "price_floor":0, "shares":0, "avg":0, "dollar":0}

    for r in rows:
        last = r.get("last_price") or r.get("last")
        prev = r.get("prev_close")
        if need_px and (not last or not prev or prev == 0):
            dropped_stats["missing_prices"] += 1
            continue

        try:
            last_f = float(last) if last is not None else 0.0
        except Exception:
            last_f = 0.0

        if last_f < min_px:
            dropped_stats["price_floor"] += 1
            continue

        shares = int(r.get("intraday_volume", 0) or 0)
        if shares < min_shares:
            dropped_stats["shares"] += 1
            continue

        avg = int(r.get("avg_daily_volume", 0) or 0)
        if avg < min_avg:
            dropped_stats["avg"] += 1
            continue

        dv = _dollar_volume(r)
        if dv < min_dv:
            dropped_stats["dollar"] += 1
            continue

        out.append(r)

    if logger:
        before, after = len(rows), len(out)
        logger.info(f"💧 Liquidity gate: {after}/{before} passed "
                    f"(dropped missing_prices={dropped_stats['missing_prices']}, "
                    f"price_floor={dropped_stats['price_floor']}, shares={dropped_stats['shares']}, "
                    f"avg={dropped_stats['avg']}, dollar={dropped_stats['dollar']})")
    return out

## -------------------------------------------------------------------
## Scanner Main Loop
##  - Runs continuous premarket scanning until window closes
##  - Fetches snapshots → scores → enriches → applies liquidity filters
##  - Logs movers, writes watchlist, and auto-selects final pick at 09:50
## -------------------------------------------------------------------
def run():
    cfg = load_config()
    logger = setup_logger(cfg["output"]["log"])

    cadence = int(cfg["premarket"]["cadence_minutes"])
    logger.info("Starting premarket scanner loop...")

    while within_premarket_window(cfg):
        try:
            snapshots = fetch_snapshots(limit=50)

            if snapshots:
                logger.info(f"Fetched {len(snapshots)} tickers, sample: {[s['ticker'] for s in snapshots[:3]]}")
                snap_dict = {s["ticker"]: s for s in snapshots if "ticker" in s}
                scored = score_snapshots(snap_dict)
                log_top_movers(scored, n=5)

                # --- Enrich rows for liquidity & final pick ---
                today = datetime.now().strftime("%Y-%m-%d")
                enriched = enrich_rows(scored, today)

                ## -------------------------------------------------------------------
                ## Liquidity Filter Application (Loop)
                ## -------------------------------------------------------------------
                liq_cfg = _get_liq_cfg(cfg)
                filtered = apply_liquidity_filters(enriched, liq_cfg, logger=logger)

                # --- Final Pick (auto at 09:50) ---
                if is_final_pick_time() and filtered:
                    winner = finalize_pick_from_rows(
                        filtered,
                        cfg["scoring_weights"],
                        liq_cfg["min_intraday_shares"],  # backward-compatible param
                    )
                    if winner:
                        logger.info(
                            f"[PRE] 📌 Final Pick of the Day (09:50 ET): "
                            f"{winner['Ticker']} (${winner['PickPrice']}, {winner['GapPct']}%)"
                        )

                # --- Write watchlist (top 5 scored for visibility) ---
                top5 = scored[:5]
                write_watchlist(cfg["output"]["watchlist"], top5, cfg["targets"])
            else:
                logger.warning("No snapshots returned this cycle")

        except Exception as e:
            logger.error(f"❌ Error during scan tick: {e}", exc_info=True)

        time.sleep(cadence * 60)

    logger.info("Premarket window closed. Scanner stopped.")

## -------------------------------------------------------------------
## Entrypoint
##  - Supports one-off run (--once) with optional --final-pick-now
##  - Otherwise runs continuous premarket loop
##  - Applies enrichment + liquidity filters before final pick
## -------------------------------------------------------------------
if __name__ == "__main__":
    if "--once" in sys.argv:
        cfg = load_config()
        logger = setup_logger(cfg["output"]["log"])
        snapshots = fetch_snapshots(limit=50)

        if snapshots:
            print("Sample snapshot:", snapshots[0])  # console debug
            logger.info(f"Fetched {len(snapshots)} tickers, sample: {[s['ticker'] for s in snapshots[:3]]}")
            snap_dict = {s["ticker"]: s for s in snapshots if "ticker" in s}
            scored = score_snapshots(snap_dict)
            log_top_movers(scored, n=5)

            # --- Enrich rows for final pick ---
            today = datetime.now().strftime("%Y-%m-%d")
            enriched = enrich_rows(scored, today)

            ## -------------------------------------------------------------------
            ## Liquidity Filter Application (Entrypoint)
            ## -------------------------------------------------------------------
            liq_cfg = _get_liq_cfg(cfg)
            filtered = apply_liquidity_filters(enriched, liq_cfg, logger=logger)

            # --- Final Pick (manual trigger or at 09:50) ---
            force_final_pick = "--final-pick-now" in sys.argv
            if (force_final_pick or is_final_pick_time()) and filtered:
                winner = finalize_pick_from_rows(
                    filtered,
                    cfg["scoring_weights"],
                    liq_cfg["min_intraday_shares"],  # backward-compatible param
                )
                if winner:
                    logger.info(
                        f"[PRE] 📌 Final Pick of the Day: "
                        f"{winner['Ticker']} (${winner['PickPrice']}, {winner['GapPct']}%)"
                    )

            # --- Write watchlist (top 5 scored for visibility) ---
            top5 = scored[:5]
            write_watchlist(cfg["output"]["watchlist"], top5, cfg["targets"])
        else:
            logger.warning("No snapshots returned")
    else:
        run()



