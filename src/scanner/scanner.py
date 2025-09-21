# --- Imports ---
import os
import sys
import time
import yaml
import logging
from datetime import datetime
import pytz

from src.adapters.polygon_adapter import fetch_snapshots
from src.core.scoring import score_snapshots, log_top_movers
from src.core.output import write_watchlist


# --- Load config ---
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../../configs/scanner.yaml")

def load_config(path=CONFIG_PATH):
    with open(path, "r") as f:
        return yaml.safe_load(f)


# --- Logging setup ---
def setup_logger(log_path):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logging.basicConfig(
        filename=log_path,
        filemode="a",
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=logging.INFO
    )
    return logging.getLogger("scanner")


# --- Time helpers ---
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


# --- Main loop ---
# --- Main loop ---
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

                top5 = scored[:5]
                write_watchlist(cfg["output"]["watchlist"], top5, cfg["targets"])
            else:
                logger.warning("No snapshots returned this cycle")

            # TODO: Add RVOL, ATR stretch
            # TODO: Validate schema

        except Exception as e:
            logger.error(f"❌ Error during scan tick: {e}", exc_info=True)

        time.sleep(cadence * 60)

    logger.info("Premarket window closed. Scanner stopped.")


# --- Entrypoint ---
if __name__ == "__main__":
    if "--once" in sys.argv:
        cfg = load_config()
        logger = setup_logger(cfg["output"]["log"])
        snapshots = fetch_snapshots(limit=50)

        if snapshots:
            print("Sample snapshot:", snapshots[0]) # debug
            logger.info(f"Fetched {len(snapshots)} tickers, sample: {[s['ticker'] for s in snapshots[:3]]}")
            snap_dict = {s["ticker"]: s for s in snapshots if "ticker" in s}
            scored = score_snapshots(snap_dict)
            log_top_movers(scored, n=5)

            top5 = scored[:5]
            write_watchlist(cfg["output"]["watchlist"], top5, cfg["targets"])
        else:
            logger.warning("No snapshots returned")
    else:
        run()

