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
from src.core.filters import is_tradeable


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
def within_window(cfg, section):
    tz = pytz.timezone("America/New_York")
    now = datetime.now(tz)

    start = datetime.combine(
        now.date(), datetime.strptime(cfg[section]["start_time"], "%H:%M").time()
    )
    end = datetime.combine(
        now.date(), datetime.strptime(cfg[section]["end_time"], "%H:%M").time()
    )

    start = tz.localize(start)
    end = tz.localize(end)

    return start <= now <= end


# --- Session loop ---
def run_session(cfg, logger, section):
    """
    Runs one session (premarket or postmarket).
    Adds [PRE] or [POST] tags in logs.
    """
    tag = "[PRE]" if section == "premarket" else "[POST]"
    cadence = int(cfg[section]["cadence_minutes"])
    logger.info(f"{tag} 📈 Starting {section} scanner loop...")

    while within_window(cfg, section):
        try:
            snapshots = fetch_snapshots(limit=50)

            if snapshots:
                logger.info(
                    f"{tag} Fetched {len(snapshots)} tickers, "
                    f"sample: {[s['ticker'] for s in snapshots[:3]]}"
                )
                snap_dict = {s["ticker"]: s for s in snapshots if "ticker" in s}
                scored = score_snapshots(snap_dict)
                log_top_movers(scored, snap_dict, n=5, tag=tag)

                top5 = scored[:5]
                write_watchlist(cfg["output"]["watchlist"], top5, cfg["targets"])
            else:
                logger.warning(f"{tag} No snapshots returned this cycle")

        except Exception as e:
            logger.error(f"{tag} ❌ Error during scan tick: {e}", exc_info=True)

        time.sleep(cadence * 60)

    logger.info(f"{tag} ✅ {section.capitalize()} scanner loop finished.")


# --- Main loop ---
def run():
    cfg = load_config()
    logger = setup_logger(cfg["output"]["log"])

    if within_window(cfg, "premarket"):
        run_session(cfg, logger, "premarket")

    if within_window(cfg, "postmarket"):
        run_session(cfg, logger, "postmarket")

    logger.info("Scanner fully stopped.")


# --- Entrypoint ---
if __name__ == "__main__":
    if "--once" in sys.argv:
        cfg = load_config()
        logger = setup_logger(cfg["output"]["log"])
        snapshots = fetch_snapshots(limit=50)

        if snapshots:
            print("Sample snapshot:", snapshots[0])  # debug
            logger.info(
                f"[ONCE] Fetched {len(snapshots)} tickers, "
                f"sample: {[s['ticker'] for s in snapshots[:3]]}"
            )
            snap_dict = {s["ticker"]: s for s in snapshots if "ticker" in s}
            scored = score_snapshots(snap_dict)
            log_top_movers(scored, snap_dict, n=5, tag="[ONCE]")

            top5 = scored[:5]
            write_watchlist(cfg["output"]["watchlist"], top5, cfg["targets"])
        else:
            logger.warning("[ONCE] No snapshots returned")
    else:
        run()
