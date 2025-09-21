# Local AI Stock Tracker (Premarket Top-5)

A local, rules-driven system that:
- Ranks premarket movers (gap%, RVOL, ATR stretch) from **04:00–09:27 ET**
- Writes **watchlist.csv** + **recommendations_buy.csv** by 09:27
- Fires open-time alerts (spam-controlled)
- Logs missed plays; EOD analyzer computes **Max-Run%** and **Fade%**
- YAML-driven rules for exits, risk, pump-prone constraints

## Quick start
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt  # or pip install httpx pydantic pyyaml python-dotenv pandas tenacity
cp .env.example .env   # put your Polygon Starter key inside
