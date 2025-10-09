# Stock Scanner & Trade Analyzer

A full-day scanner that monitors stocks from premarket through market close, identifies top movers using multi-factor scoring (gap %, volume, momentum), and provides end-of-day analysis with optimal entry/exit windows. Includes trading journal and performance tracking.

---

## Features
- **Premarket scanning (04:00–09:30 ET)** with configurable cadence
- **Intraday monitoring (09:30–16:00 ET)** with heartbeat detection (catches slow climbers)
- **Pick of the Day** → Scanner selects top pick at 9:50 AM
- **End-of-Day analysis** → Identifies best catchable opportunities with entry/exit windows
- **Trading journal** → Track actual trades and compare vs. best picks
- **Weekly analyzer** → Generate summaries of wins/losses and P&L
- **Gap % + volume + heartbeat scoring** for Top-5 ranking

---

## Repo Structure
```
.
├── README.md
├── requirements.txt
├── docs/                          # Documentation
│   ├── CHANGELOG.md
│   ├── EOD_ANALYSIS.md           # End-of-day analysis guide
│   ├── SYSTEM_GUIDE.md           # Complete system guide
│   └── archive/
├── configs/
│   ├── scanner.yaml
│   └── group_watchlist.csv
├── logs/                          # Scanner logs (gitignored)
│   └── scanner_YYYY-MM-DD.log
├── output/
│   ├── journal.csv               # Your actual trades
│   ├── missed.csv                # Historical best picks
│   ├── today_pick.csv            # Scanner's daily pick
│   ├── watchlist.csv
│   └── reports/                  # Daily EOD reports (gitignored)
│       └── eod_report_*.md
├── schemas/
│   ├── journal_template.csv
│   ├── today_pick.schema.json
│   └── watchlist.schema.json
├── scripts/
│   ├── analyze_eod.py            # End-of-day analysis
│   ├── analyze_week.py           # Weekly summary
│   ├── log_today_trades.py       # Quick trade logger
│   └── run_eod_analysis.sh       # Automation script
├── src/
│   ├── adapters/
│   │   └── polygon_adapter.py
│   ├── analysis/                 # Analysis tools
│   ├── core/
│   │   ├── scoring.py
│   │   ├── output.py
│   │   └── journal.py
│   └── scanner/
│       └── scanner.py            # Main scanner (heartbeat fix)
└── tests/
```

---

## ⚡ Usage

### 1. Setup
```bash
# activate virtualenv
source .venv/bin/activate

# export your Polygon API key
export POLYGON_API_KEY="your_key_here"
```

### 2. Dry Run (night before)
```bash
python -m src.scanner.scanner --once
```
- Prints sample snapshot + Top-5 movers
- Writes rows into `output/watchlist.csv`

### 3. Live Run (full-day scan)
```bash
python -m src.scanner.scanner
```
- Runs every `cadence_minutes` until 09:27 ET  
- Logs Top-5 movers to `logs/scanner.log`  
- Appends Top-5 movers into `output/watchlist.csv`

### 4. Paper Trades
Log hypothetical trades:
```python
from src.core.journal import record_trade

record_trade("output/journal.csv",
             ticker="AAPL", side="long",
             entry_price=225.0, exit_price=231.5,
             shares=100,
             plan="Breakout above PMH +0.3%",
             actual="Filled at open",
             notes="Paper trade")
```

### 5. End-of-Day Analysis
```bash
python scripts/analyze_eod.py
```
Analyzes today's scanner log and identifies:
- Best catchable picks (>8% gain)
- Optimal entry/exit windows
- Compares your actual trades vs. best picks

### 6. Log Your Trades
```bash
python scripts/log_today_trades.py
```
Interactive CLI to log your trades to `journal.csv`.

### 7. Weekly Summary
```bash
python scripts/analyze_week.py
```
Outputs a Markdown report:
- Total trades, win rate, avg P/L
- Best/worst trades
- P/L per ticker

---

## 📚 Documentation

- **[EOD Analysis Guide](docs/EOD_ANALYSIS.md)** - How end-of-day analysis works
- **[Changelog](docs/CHANGELOG.md)** - Version history and changes

---

## 🛠️ Roadmap
- [ ] Add RVOL and ATR stretch into scoring
- [ ] Schema validation for `watchlist.csv`
- [ ] Auto-log paper entries when tickers first appear
- [ ] Equity curve + performance visualization
- [ ] AI-powered trade recommendations (future)

---

## 📜 License
Private / internal use.
