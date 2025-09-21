import os
import sys
import time
import yaml
import logging
from datetime import datetime, timedelta
import pytz

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

    start = datetime.combine(now.date(), datetime.strptime(cfg["premarket"]["start_time"], "%H:%M").time())
    end = datetime.combine(now.date(), datetime.strptime(cfg["premarket"]["end_time"], "%H:%M").time())

    start = tz.localize(start)
    end = tz.localize(end)

    return start <= now <= end

# --- Main loop skeleton ---
def run():
    cfg = load_config()
    logger = setup_logger(cfg["output"]["log"])

    cadence = int(cfg["premarket"]["cadence_minutes"])
    logger.info("Starting premarket scanner loop...")

    while within_premarket_window(cfg):
        try:
            # TODO: Fetch tickers from Polygon
            # TODO: Compute gap %, RVOL, ATR stretch
            # TODO: Score & rank Top 5
            # TODO: Write watchlist.csv & validate schema
            logger.info("Scanner tick executed (data fetch + scoring not yet implemented)")
        except Exception as e:
            logger.error(f"Error during scan tick: {e}", exc_info=True)

        time.sleep(cadence * 60)

    logger.info("Premarket window closed. Scanner stopped.")

if __name__ == "__main__":
    run()
