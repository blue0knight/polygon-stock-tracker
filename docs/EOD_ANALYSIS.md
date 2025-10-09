# End-of-Day Analysis System

Automated system to analyze daily scanner logs and identify the best trading opportunities we could have caught.

---

## Overview

The EOD (End-of-Day) analysis script automatically:
1. Parses the day's scanner log
2. Tracks every stock's price trajectory throughout the day
3. Identifies "catchable" opportunities (stocks that appeared in scanner before major move)
4. Calculates optimal entry/exit windows
5. Generates daily reports and appends to `missed.csv`

---

## Quick Start

### Manual Analysis (run after 4 PM ET)

```bash
# Analyze today's log
python3 scripts/analyze_eod.py

# Analyze specific date
python3 scripts/analyze_eod.py --date YYYY-MM-DD

# Change minimum gain threshold (default: 8%)
python3 scripts/analyze_eod.py --min-gain 10.0

# Don't append to missed.csv (just generate report)
python3 scripts/analyze_eod.py --no-csv
```

### Automated Daily Run

```bash
# Run the shell script (automatically uses today's date)
./scripts/run_eod_analysis.sh
```

---

## What Gets Generated

### 1. Console Output
```
#1: TICKER1 (+XX.X%)
   Entry: HH:MM-HH:MM @ $XX.XX-$XX.XX
   Exit:  HH:MM-HH:MM @ $XX.XX-$XX.XX

#2: TICKER2 (+XX.X%)
   Entry: HH:MM-HH:MM @ $XX.XX-$XX.XX
   Exit:  HH:MM-HH:MM @ $XX.XX-$XX.XX
```

### 2. Daily Markdown Report
**Location:** `output/eod_report_YYYY-MM-DD.md`

Full analysis with:
- Stock performance (open, peak, gain %)
- Entry window (time range + price range)
- Exit window (time range + price range)
- Volume data

### 3. Missed Opportunities CSV
**Location:** `output/missed.csv`

Appends top 5 picks daily for historical tracking and weekly review.

**Columns:**
- `date`, `ticker`, `open_price`
- `first_seen_time`, `first_seen_price`
- `peak_time`, `peak_price`
- `gain_pct`, `volume_m`
- `entry_window`, `exit_window`, `notes`

---

## How It Works

### Stock Filtering

A stock is considered "catchable" if:
1. **Appeared in scanner before 2 PM** (not late-day runners)
2. **Volume > 1M shares** (liquid enough to trade)
3. **Peak at least 5 min after first appearance** (time to react)
4. **Gain ≥ 8%** from open to peak (worth the trade)

### Entry Window Calculation

Entry window = first 30 minutes OR first 10 scanner appearances (whichever is shorter)

**Why:** Gives reasonable time to identify and enter the trade without chasing.

### Exit Window Calculation

Exit window = all times when price was within 2% of peak

**Why:** Realistic exit zone; you don't need to nail the exact top.

### Example Analysis

**Sample Stock:**
```
Open: $X.XX
First seen: HH:MM @ $X.XX
Peak: HH:MM @ $X.XX (+XX.X%)

Entry Window: HH:MM-HH:MM @ $X.XX-$X.XX
  → XX-minute window to enter
  → Could enter anywhere in price range

Exit Window: HH:MM-HH:MM @ $X.XX-$X.XX
  → XX-minute window to exit near peak
  → Multiple chances to sell above entry price
```

---

## Automation Setup

### Option 1: Cron Job (Mac/Linux)

Run at 4:05 PM ET every weekday:

```bash
# Open crontab
crontab -e

# Add this line (adjust timezone if needed)
5 16 * * 1-5 /Users/blue0knight/Documents/code/polygon-stock-tracker/scripts/run_eod_analysis.sh >> /Users/blue0knight/Documents/code/polygon-stock-tracker/logs/eod_cron.log 2>&1
```

**Time conversion:**
- 4:05 PM ET = `5 16` in cron (if your system is in ET)
- Adjust hour for your timezone (e.g., PST: `5 13`)

### Option 2: Manual Daily Habit

Add to your end-of-day routine:
```bash
cd ~/Documents/code/polygon-stock-tracker
./scripts/run_eod_analysis.sh
```

---

## Integration with Journal

### Current Flow

1. **Scanner runs throughout the day** → generates `today_pick.csv` at 9:50 AM
2. **You trade (or paper trade)** → log manually with `scripts/log_trade.py`
3. **EOD analysis runs at 4:05 PM** → identifies what you *could* have traded
4. **Weekly review** → `scripts/analyze_week.py` summarizes actual trades

### Recommended Workflow

**Morning (9:30 AM):**
- Scanner picks stock → saved to `today_pick.csv`
- You decide to trade or not

**End of Day (4:05 PM):**
- Run `analyze_eod.py` → see best opportunities
- Compare: did the scanner pick match the EOD top pick?
- Log your actual trade (if any) to `journal.csv`

**Friday Evening:**
- Run `analyze_week.py` → review week's actual performance
- Compare actual P&L vs. missed opportunities from `missed.csv`

---

## Customization

### Change Minimum Gain Threshold

Default is 8%. Adjust in script or via CLI:

```bash
# Only show stocks with >12% gains
python3 scripts/analyze_eod.py --min-gain 12.0
```

Or edit `scripts/analyze_eod.py`:
```python
MIN_GAIN_PCT = 12.0  # Line 17
```

### Change Volume Threshold

Edit `scripts/analyze_eod.py`:
```python
MIN_VOLUME = 500_000  # Line 18 (default: 1M)
```

### Filter by Entry Time

Edit `is_catchable()` function in `scripts/analyze_eod.py`:
```python
# Only show stocks that appeared before 11 AM
if self.first_time and self.first_time.hour >= 11:
    return False
```

---

## Example Daily Reports

### Strong Day (5 catchable picks)
```
#1: TICKER1 (+XX.X%)
#2: TICKER2 (+XX.X%)
#3: TICKER3 (+XX.X%)
#4: TICKER4 (+XX.X%)
#5: TICKER5 (+XX.X%)
```

### Weak Day (1-2 picks)
```
#1: TICKER1 (+X.X%)
(Only 1 catchable opportunity today)
```

### Dead Day (0 picks)
```
No catchable opportunities found today (min gain: 8%)
```

---

## Troubleshooting

### "Log file not found"

Make sure scanner ran today. Check:
```bash
ls logs/scanner_$(date +%Y-%m-%d).log
```

### "No catchable opportunities"

Possible reasons:
1. Market was slow (no stocks moved >8%)
2. Movers were late-day runners (appeared after 2 PM)
3. Movers were illiquid (volume <1M)
4. Scanner missed them (not in top 5 at any scan)

Try lowering threshold:
```bash
python3 scripts/analyze_eod.py --min-gain 5.0
```

### Wrong timezone

If cron runs at wrong time, adjust the hour in crontab:
- EST/EDT: Use `TZ='America/New_York'` in cron
- Or convert manually (e.g., PST is -3 hours from ET)

---

## Future Enhancements

Potential additions:
- [ ] Compare scanner pick vs. EOD best pick (hit rate)
- [ ] Calculate hypothetical P&L if all EOD picks were traded
- [ ] Backtest: run EOD analysis on historical logs (Oct 1-7)
- [ ] Email/SMS alert when EOD finds >2 strong picks (>15% gain)
- [ ] Integration: auto-add top pick to tomorrow's watchlist

---

## Files Reference

| File | Purpose |
|------|---------|
| `scripts/analyze_eod.py` | Main EOD analysis script |
| `scripts/run_eod_analysis.sh` | Shell wrapper for automation |
| `output/eod_report_YYYY-MM-DD.md` | Daily markdown report |
| `output/missed.csv` | Historical log of missed opportunities |
| `logs/scanner_YYYY-MM-DD.log` | Input: scanner log to analyze |

---

## Questions Answered

### "What were the best picks today?"
Run `analyze_eod.py` → top 5 listed by gain %

### "What time should I have entered XXX?"
Check entry window in report

### "When should I have exited XXX"
Check exit window in report

### "How often do we find 15%+ gainers?"
Review `missed.csv` → count rows with `gain_pct > 15`

### "Is Polygon data good enough?"
If EOD analysis consistently finds opportunities that scanner logged in real-time, then yes. If best movers never appear in scanner logs, consider upgrade.

---

**Version:** 1.0
