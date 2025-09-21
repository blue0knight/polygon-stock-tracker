# Premarket Top-5 Scanner

A local rule-based tool that connects to the Polygon API, scans premarket tickers, ranks the **Top 5 movers by gap %**, logs results, and supports paper-trading with a journal and weekly summaries.

---

## Features
- **Premarket scanning (04:00–09:27 ET)** with configurable cadence
- **Gap % scoring** and Top-5 ranking
- **Watchlist output** → `output/watchlist.csv`
- **Logging** → `logs/scanner.log` with Top-5 each cycle
- **Paper-trading journal** → record hypothetical trades in `output/journal.csv`
- **Weekly analyzer** → generate summaries of wins/losses and P&L

---

## Repo Structure
```
.
├── CHANGELOG.md
├── README.md
├── backtest/
├── configs/
│   ├── scanner.example.yaml
│   └── scanner.yaml
├── data/
├── logs/
│   └── scanner.log
├── output/
│   └── watchlist.csv
├── schemas/
│   ├── journal_template.csv
│   ├── missed_template.csv
│   ├── recommendations_buy.schema.json
│   ├── watchlist.schema.json
│   └── watchlist_template.csv
├── scripts/
│   ├── analyze_week.py
│   ├── test_fetch.py
│   └── validate_csv.py
├── src/
│   ├── adapters/
│   │   └── polygon_adapter.py
│   ├── core/
│   │   ├── scoring.py
│   │   ├── output.py
│   │   └── journal.py
│   ├── scanner/
│   │   └── scanner.py
│   └── utils/
├── test_polygon.py
└── tests/
    └── test_scoring.py
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

### 3. Live Run (premarket loop)
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

### 5. Weekly Summary
```bash
python scripts/analyze_week.py
```
Outputs a Markdown report in `output/`:
- Total trades, win rate, avg P/L
- Best/worst trades
- P/L per ticker

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
