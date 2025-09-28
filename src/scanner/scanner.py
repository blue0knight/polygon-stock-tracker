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

def setup_logger(log_path: str) -> logging.Logger:
    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_file),
        filemode="a",
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=logging.INFO
    )
    return logging.getLogger("scanner")


# -------------------------------------------------------------------
# Time helpers
# -------------------------------------------------------------------
def within_premarket_window(cfg: dict) -> bool:
    tz = pytz.timezone("America/New_York")
    now = datetime.now(tz)
    start = datetime.combine(
        now.date(), datetime.strptime(cfg["premarket"]["start_time"], "%H:%M").time()
    )
    end = datetime.combine(
        now.date(), datetime.strptime(cfg["premarket"]["end_time"], "%H:%M").time()
    )
    return tz.localize(start) <= now <= tz.localize(end)

def is_final_pick_time() -> bool:
    tz = pytz.timezone("America/New_York")
    return datetime.now(tz).strftime("%H:%M") == "09:50"


# -------------------------------------------------------------------
# CSV bootstrap / append
# -------------------------------------------------------------------
CSV_FIELDS = [
    "date","time","ticker","gap_pct","rvol","atr_stretch",
    "premarket_high","open_price","score","final_pick","rationale",
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
def enrich_rows(snapshots: list[dict], trade_date: str) -> list[dict]:
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
        pm_high    = pa.get_premarket_high(tkr, trade_date)
        atr_14     = pa.get_atr_14(tkr, trade_date)

        # Pull intraday/avg volumes from adapter (safer than relying on snapshot shape)
        intraday_vol = pa.get_intraday_volume(tkr, trade_date)
        avg_vol      = pa.get_avg_daily_volume(tkr, lookback=20)

        # Prices: prefer snapshot last_price if present; fall back gracefully
        last_price = s.get("last_price") or prev_close or 0.0
        open_price = last_price  # until we wire explicit 09:30 open

        gap_pct = ((open_price - prev_close) / prev_close * 100.0) if prev_close else None
        rvol    = (intraday_vol / avg_vol) if avg_vol else None
        atr_stretch = ((last_price - prev_close) / atr_14) if atr_14 else None

        enriched.append({
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
        })
    return enriched


# -------------------------------------------------------------------
# Liquidity filters
# -------------------------------------------------------------------
def _dollar_volume(row: dict) -> float:
    try:
        return float(row.get("last_price", 0)) * int(row.get("intraday_volume", 0))
    except Exception:
        return 0.0

def apply_liquidity_filters(rows: list[dict], liq_cfg: dict, logger: logging.Logger | None = None) -> list[dict]:
    out: list[dict] = []
    dropped = {"missing_prices":0, "price_floor":0, "shares":0, "avg":0, "dollar":0}

    for r in rows:
        last = r.get("last_price")
        prev = r.get("prev_close")
        if liq_cfg["require_prices"] and (not last or not prev or prev == 0):
            dropped["missing_prices"] += 1; continue
        if float(last or 0.0) < float(liq_cfg["min_price"]):
            dropped["price_floor"] += 1; continue
        if int(r.get("intraday_volume", 0) or 0) < int(liq_cfg["min_intraday_shares"]):
            dropped["shares"] += 1; continue
        if int(r.get("avg_daily_volume", 0) or 0) < int(liq_cfg["min_avg_daily_volume"]):
            dropped["avg"] += 1; continue
        if _dollar_volume(r) < float(liq_cfg["min_dollar_volume"]):
            dropped["dollar"] += 1; continue
        out.append(r)

    if logger:
        logger.info(f"💧 Liquidity gate: {len(out)}/{len(rows)} passed (dropped {dropped})")
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
        row = _final_pick_row(dummy, score=dbg["dummy_score"], final=True, rationale=dbg.get("rationale", "Debug"))
        append_row(row, cfg)
        logger.info(f"⚠️ Debug: Appended dummy Final Pick -> {cfg['output'].get('today_pick', 'output/today_pick.csv')}")
        return

    # --- Normal path ---
    snaps = fetch_snapshots(limit=50)
    enriched = enrich_rows(snaps, today) if snaps else []
    filtered = apply_liquidity_filters(enriched, cfg["liquidity"], logger) if enriched else []

    if not filtered:
        logger.warning("No tickers passed liquidity filters — skipping scoring/final pick.")
        return

    # Score + log movers
    scored = score_snapshots(filtered, cfg["scoring_weights"])
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

    row = _final_pick_row(winner, score=winner.get("score", ""), final=True, rationale="")
    append_row(row, cfg)
    logger.info(f"[PRE] 📌 Final Pick: {row['ticker']} (score={row['score']})")

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

    logger.info("Premarket window closed. Scanner stopped.")

# -------------------------------------------------------------------
# Entrypoint
# -------------------------------------------------------------------
if __name__ == "__main__":
    cfg = load_config()
    logger = setup_logger(cfg["output"]["log"])

    # Seed CSV at start for both modes
    ensure_today_pick_ready(cfg, reset=True)

    if "--once" in sys.argv:
        force = "--final-pick-now" in sys.argv
        try:
            run_once(cfg, logger, force_final_pick=force)
        except Exception as e:
            logger.error(f"❌ Error in --once run: {e}", exc_info=True)
    else:
        run()
