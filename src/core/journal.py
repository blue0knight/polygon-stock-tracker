import csv, os
from datetime import datetime
from typing import Optional, Dict

JOURNAL_HEADERS = [
    "date","ticker","side","entry_price","exit_price","shares",
    "total_cost","pl_dollar","pl_percent","plan","actual","notes"
]

def ensure_file(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.isfile(path):
        with open(path, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=JOURNAL_HEADERS).writeheader()

def compute_pl(entry_price: float, exit_price: float, shares: int):
    total_cost = round(entry_price * shares, 2)
    pl_dollar = round((exit_price - entry_price) * shares, 2)
    pl_percent = round(((exit_price - entry_price) / entry_price) * 100, 2) if entry_price else 0.0
    return total_cost, pl_dollar, pl_percent

def record_trade(path: str, *,
                 date: Optional[str] = None,
                 ticker: str,
                 side: str,
                 entry_price: float,
                 exit_price: float,
                 shares: int,
                 plan: str = "",
                 actual: str = "",
                 notes: str = ""):
    """
    side: 'long' or 'short'
    date: ISO yyyy-mm-dd (default: today)
    """
    ensure_file(path)
    date = date or datetime.today().date().isoformat()
    total_cost, pl_dollar, pl_percent = compute_pl(entry_price, exit_price, shares)

    row = {
        "date": date,
        "ticker": ticker.upper(),
        "side": side,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "shares": shares,
        "total_cost": total_cost,
        "pl_dollar": pl_dollar,
        "pl_percent": pl_percent,
        "plan": plan,
        "actual": actual,
        "notes": notes,
    }
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=JOURNAL_HEADERS)
        w.writerow(row)
