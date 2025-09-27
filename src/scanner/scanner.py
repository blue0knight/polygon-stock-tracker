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
from src.core.scoring import Candidate, select_final_pick
from src.core.output import write_final_pick
from src.adapters.polygon_adapter import fetch_snapshots
from src.core.scoring import score_snapshots, log_top_movers
from src.core.output import write_watchlist
from dotenv import load_dotenv

## -------------------------------------------------------------------
## Environment Setup
##  - Loads .env for POLYGON_API_KEY
## -------------------------------------------------------------------
from pathlib import Path
from dotenv import load_dotenv
import os

# Resolve project root (2 levels up from this file)
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


## -------------------------------------------------------------------
## Scanner Main Loop
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

                # --- Final Pick (auto at 09:50) ---
                if is_final_pick_time() and scored:
                    winner = finalize_pick_from_rows(
                        scored,
                        cfg["scoring_weights"],
                        cfg["min_liquidity"],
                    )
                    if winner:
                        logger.info(
                            f"[PRE] 📌 Final Pick of the Day (09:50 ET): "
                            f"{winner['Ticker']} (${winner['PickPrice']}, {winner['GapPct']}%)"
                        )

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

            # --- Final Pick (manual trigger or at 09:50) ---
            force_final_pick = "--final-pick-now" in sys.argv
            if (force_final_pick or is_final_pick_time()) and enriched:
                winner = finalize_pick_from_rows(
                    enriched,
                    cfg["scoring_weights"],
                    cfg["min_liquidity"],
                )
                if winner:
                    logger.info(
                        f"[PRE] 📌 Final Pick of the Day: "
                        f"{winner['Ticker']} (${winner['PickPrice']}, {winner['GapPct']}%)"
                    )

            # --- Write watchlist ---
            top5 = scored[:5]
            write_watchlist(cfg["output"]["watchlist"], top5, cfg["targets"])
        else:
            logger.warning("No snapshots returned")
    else:
        run()



