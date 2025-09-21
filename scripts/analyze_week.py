import csv, os, argparse
from datetime import datetime, timedelta
from collections import defaultdict

JOURNAL_PATH_DEFAULT = "output/journal.csv"
SUMMARY_DIR = "output"

def week_bounds(reference_date=None):
    # default: last Monday..Sunday window containing reference (or today)
    today = datetime.today().date() if reference_date is None else reference_date
    monday = today - timedelta(days=today.weekday())          # this Monday
    sunday = monday + timedelta(days=6)
    return monday, sunday

def load_rows(path, start_date, end_date):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                d = datetime.strptime(row["date"], "%Y-%m-%d").date()
            except Exception:
                continue
            if start_date <= d <= end_date:
                rows.append(row)
    return rows

def floaty(x, default=0.0):
    try: return float(x)
    except: return default

def inty(x, default=0):
    try: return int(x)
    except: return default

def summarize(rows):
    n = len(rows)
    total_pl = sum(floaty(r["pl_dollar"]) for r in rows)
    wins = sum(1 for r in rows if floaty(r["pl_dollar"]) > 0)
    losses = sum(1 for r in rows if floaty(r["pl_dollar"]) < 0)
    breakeven = n - wins - losses
    win_rate = (wins / n * 100) if n else 0.0
    avg_pl = (total_pl / n) if n else 0.0
    avg_pl_pct = sum(floaty(r["pl_percent"]) for r in rows) / n if n else 0.0

    # best/worst
    best = max(rows, key=lambda r: floaty(r["pl_dollar"]), default=None)
    worst = min(rows, key=lambda r: floaty(r["pl_dollar"]), default=None)

    # per-ticker aggregates
    per_ticker = defaultdict(lambda: {"trades":0,"pl":0.0})
    for r in rows:
        t = r["ticker"].upper()
        per_ticker[t]["trades"] += 1
        per_ticker[t]["pl"] += floaty(r["pl_dollar"])

    return {
        "count": n,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "win_rate": round(win_rate, 2),
        "total_pl": round(total_pl, 2),
        "avg_pl": round(avg_pl, 2),
        "avg_pl_pct": round(avg_pl_pct, 2),
        "best": best,
        "worst": worst,
        "per_ticker": per_ticker,
    }

def write_markdown(summary_path, start, end, S):
    os.makedirs(os.path.dirname(summary_path), exist_ok=True)
    lines = []
    lines.append(f"# Weekly Summary ({start} to {end})")
    lines.append("")
    lines.append(f"- Trades: **{S['count']}**  |  Wins: **{S['wins']}**  |  Losses: **{S['losses']}**  |  Breakeven: **{S['breakeven']}**")
    lines.append(f"- Win rate: **{S['win_rate']}%**")
    lines.append(f"- Total P/L: **${S['total_pl']}**  |  Avg P/L: **${S['avg_pl']}**  |  Avg P/L %: **{S['avg_pl_pct']}%**")
    lines.append("")
    if S["best"]:
        lines.append(f"- Best: **{S['best']['ticker']}** ${float(S['best']['pl_dollar']):.2f}")
    if S["worst"]:
        lines.append(f"- Worst: **{S['worst']['ticker']}** ${float(S['worst']['pl_dollar']):.2f}")
    lines.append("")
    lines.append("## P/L by Ticker")
    if S["per_ticker"]:
        for t, v in sorted(S["per_ticker"].items(), key=lambda kv: kv[1]["pl"], reverse=True):
            lines.append(f"- {t}: trades={v['trades']}, P/L=${v['pl']:.2f}")
    else:
        lines.append("_No trades this week_")

    with open(summary_path, "w") as f:
        f.write("\n".join(lines))

def main():
    p = argparse.ArgumentParser(description="Weekly journal analyzer")
    p.add_argument("--journal", default=JOURNAL_PATH_DEFAULT, help="Path to journal.csv")
    p.add_argument("--start", help="Start date YYYY-MM-DD")
    p.add_argument("--end", help="End date YYYY-MM-DD")
    args = p.parse_args()

    if args.start and args.end:
        start = datetime.strptime(args.start, "%Y-%m-%d").date()
        end = datetime.strptime(args.end, "%Y-%m-%d").date()
    else:
        # default: the current week (Mon..Sun)
        start, end = week_bounds()

    rows = load_rows(args.journal, start, end)
    S = summarize(rows)

    # Console summary
    print(f"Weekly Summary ({start} to {end})")
    print(f"Trades: {S['count']} | Wins: {S['wins']} | Losses: {S['losses']} | Breakeven: {S['breakeven']}")
    print(f"Win rate: {S['win_rate']}%")
    print(f"Total P/L: ${S['total_pl']} | Avg P/L: ${S['avg_pl']} | Avg P/L %: {S['avg_pl_pct']}%")
    if S["best"]:
        print(f"Best: {S['best']['ticker']} ${float(S['best']['pl_dollar']):.2f}")
    if S["worst"]:
        print(f"Worst: {S['worst']['ticker']} ${float(S['worst']['pl_dollar']):.2f}")

    # Markdown file
    summary_path = os.path.join(SUMMARY_DIR, f"weekly_summary_{start}_to_{end}.md")
    write_markdown(summary_path, start, end, S)
    print(f"Saved {summary_path}")

if __name__ == "__main__":
    main()
