"""
P&D Behavior Tracker
Tracks key metrics for pump & dump analysis:
- When did it start moving? (9:30 spike time)
- When did it peak? (high of day time)
- When did it fade? (when it dropped X% from peak)
- Was it in watchlist, scanner pick, or both?
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import pytz

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from src.adapters.polygon_adapter import _require_api_key, _session, to_unix_ms

BASE_URL = "https://api.polygon.io"
NY_TZ = pytz.timezone("America/New_York")


def get_intraday_bars(ticker: str, date: str, start_time: str = "09:30", end_time: str = "16:00") -> List[Dict]:
    """
    Fetch 1-minute bars for a ticker on a specific date.
    Returns list of bars: [{t: timestamp_ms, o: open, h: high, l: low, c: close, v: volume}, ...]
    """
    api_key = _require_api_key()

    # Build start/end datetime
    start_dt = NY_TZ.localize(datetime.strptime(f"{date} {start_time}:00", "%Y-%m-%d %H:%M:%S"))
    end_dt = NY_TZ.localize(datetime.strptime(f"{date} {end_time}:00", "%Y-%m-%d %H:%M:%S"))

    start_ms = to_unix_ms(start_dt.astimezone(pytz.UTC))
    end_ms = to_unix_ms(end_dt.astimezone(pytz.UTC))

    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{start_ms}/{end_ms}"
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": api_key}

    with _session() as s:
        resp = s.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

    return data.get("results", [])


def analyze_pd_behavior(
    ticker: str,
    date: str,
    premarket_price: float,
    prev_close: float,
    pick_time: str = "09:50",
    in_watchlist: bool = False,
    is_scanner_pick: bool = False,
) -> Dict:
    """
    Analyze P&D behavior for a ticker.

    Returns:
    {
        'ticker': str,
        'date': str,
        'prev_close': float,
        'premarket_price': float,
        'premarket_gap_pct': float,

        # Opening behavior (9:30-9:35)
        'open_9_30': float,
        'high_9_35': float,
        'spike_9_35_pct': float,  # % from open to 9:35 high

        # Peak analysis
        'high_of_day': float,
        'high_time': str,
        'minutes_to_peak': int,  # minutes from 9:30 to peak

        # Pick time analysis
        'price_at_pick': float,  # price at 9:50 (or pick_time)
        'pick_vs_open_pct': float,  # % change from 9:30 to pick time
        'pick_vs_peak_pct': float,  # how far from peak at pick time

        # Fade analysis
        'fade_10pct_time': Optional[str],  # when it dropped 10% from peak
        'fade_20pct_time': Optional[str],  # when it dropped 20% from peak
        'minutes_peak_to_fade': Optional[int],  # how long the pump lasted

        # End of day
        'close_price': float,
        'close_vs_peak_pct': float,

        # Classification
        'in_watchlist': bool,
        'is_scanner_pick': bool,
        'pattern': str,  # "quick_spike_fade" | "sustained_run" | "grind_up" | "failed"
    }
    """

    # Fetch 1-minute bars from 9:30-16:00
    bars = get_intraday_bars(ticker, date, "09:30", "16:00")

    if not bars:
        return {
            'ticker': ticker,
            'date': date,
            'error': 'No intraday data available',
        }

    # Calculate premarket gap
    premarket_gap_pct = ((premarket_price - prev_close) / prev_close * 100.0) if prev_close else 0

    # Opening behavior (9:30-9:35)
    open_9_30 = bars[0]['o'] if bars else 0
    bars_9_35 = [b for b in bars if b['t'] <= to_unix_ms(NY_TZ.localize(datetime.strptime(f"{date} 09:35:00", "%Y-%m-%d %H:%M:%S")).astimezone(pytz.UTC))]
    high_9_35 = max([b['h'] for b in bars_9_35]) if bars_9_35 else open_9_30
    spike_9_35_pct = ((high_9_35 - open_9_30) / open_9_30 * 100.0) if open_9_30 else 0

    # Find peak (high of day)
    high_bar = max(bars, key=lambda b: b['h'])
    high_of_day = high_bar['h']
    high_time_dt = datetime.fromtimestamp(high_bar['t'] / 1000, tz=pytz.UTC).astimezone(NY_TZ)
    high_time = high_time_dt.strftime("%H:%M")

    # Minutes to peak from 9:30
    open_time = NY_TZ.localize(datetime.strptime(f"{date} 09:30:00", "%Y-%m-%d %H:%M:%S"))
    minutes_to_peak = int((high_time_dt - open_time).total_seconds() / 60)

    # Price at pick time
    pick_time_dt = NY_TZ.localize(datetime.strptime(f"{date} {pick_time}:00", "%Y-%m-%d %H:%M:%S"))
    pick_time_ms = to_unix_ms(pick_time_dt.astimezone(pytz.UTC))
    pick_bar = min([b for b in bars if b['t'] >= pick_time_ms], key=lambda b: abs(b['t'] - pick_time_ms), default=None)
    price_at_pick = pick_bar['c'] if pick_bar else 0

    pick_vs_open_pct = ((price_at_pick - open_9_30) / open_9_30 * 100.0) if open_9_30 else 0
    pick_vs_peak_pct = ((price_at_pick - high_of_day) / high_of_day * 100.0) if high_of_day else 0

    # Fade analysis (when price drops X% from peak)
    fade_10pct_threshold = high_of_day * 0.90
    fade_20pct_threshold = high_of_day * 0.80

    fade_10pct_time = None
    fade_20pct_time = None

    for bar in bars:
        if bar['t'] > high_bar['t']:  # After peak
            if not fade_10pct_time and bar['l'] <= fade_10pct_threshold:
                fade_dt = datetime.fromtimestamp(bar['t'] / 1000, tz=pytz.UTC).astimezone(NY_TZ)
                fade_10pct_time = fade_dt.strftime("%H:%M")
            if not fade_20pct_time and bar['l'] <= fade_20pct_threshold:
                fade_dt = datetime.fromtimestamp(bar['t'] / 1000, tz=pytz.UTC).astimezone(NY_TZ)
                fade_20pct_time = fade_dt.strftime("%H:%M")

    minutes_peak_to_fade = None
    if fade_10pct_time:
        fade_dt = datetime.strptime(f"{date} {fade_10pct_time}:00", "%Y-%m-%d %H:%M:%S")
        fade_dt = NY_TZ.localize(fade_dt)
        minutes_peak_to_fade = int((fade_dt - high_time_dt).total_seconds() / 60)

    # End of day
    close_price = bars[-1]['c'] if bars else 0
    close_vs_peak_pct = ((close_price - high_of_day) / high_of_day * 100.0) if high_of_day else 0

    # Pattern classification
    pattern = classify_pattern(
        minutes_to_peak=minutes_to_peak,
        minutes_peak_to_fade=minutes_peak_to_fade,
        spike_9_35_pct=spike_9_35_pct,
        pick_vs_peak_pct=pick_vs_peak_pct,
    )

    return {
        'ticker': ticker,
        'date': date,
        'prev_close': round(prev_close, 4),
        'premarket_price': round(premarket_price, 4),
        'premarket_gap_pct': round(premarket_gap_pct, 2),

        'open_9_30': round(open_9_30, 4),
        'high_9_35': round(high_9_35, 4),
        'spike_9_35_pct': round(spike_9_35_pct, 2),

        'high_of_day': round(high_of_day, 4),
        'high_time': high_time,
        'minutes_to_peak': minutes_to_peak,

        'price_at_pick': round(price_at_pick, 4),
        'pick_vs_open_pct': round(pick_vs_open_pct, 2),
        'pick_vs_peak_pct': round(pick_vs_peak_pct, 2),

        'fade_10pct_time': fade_10pct_time,
        'fade_20pct_time': fade_20pct_time,
        'minutes_peak_to_fade': minutes_peak_to_fade,

        'close_price': round(close_price, 4),
        'close_vs_peak_pct': round(close_vs_peak_pct, 2),

        'in_watchlist': in_watchlist,
        'is_scanner_pick': is_scanner_pick,
        'pattern': pattern,
    }


def classify_pattern(
    minutes_to_peak: int,
    minutes_peak_to_fade: Optional[int],
    spike_9_35_pct: float,
    pick_vs_peak_pct: float,
) -> str:
    """
    Classify P&D pattern:
    - quick_spike_fade: Peaks in <10 min, fades fast (<5 min)
    - sustained_run: Peaks 10-30 min, holds for 10+ min
    - grind_up: Peaks >30 min, slow build
    - failed: Never broke above 9:35 high significantly
    """

    if spike_9_35_pct < 5 and pick_vs_peak_pct < -10:
        return "failed"

    if minutes_to_peak <= 10:
        if minutes_peak_to_fade and minutes_peak_to_fade <= 5:
            return "quick_spike_fade"
        else:
            return "early_peak"

    if 10 < minutes_to_peak <= 30:
        if minutes_peak_to_fade and minutes_peak_to_fade >= 10:
            return "sustained_run"
        else:
            return "mid_pump"

    return "grind_up"


def print_analysis(analysis: Dict) -> None:
    """Pretty print analysis results."""
    print("\n" + "="*60)
    print(f"P&D Analysis: {analysis['ticker']} on {analysis['date']}")
    print("="*60)

    if 'error' in analysis:
        print(f"❌ {analysis['error']}")
        return

    print(f"\n📊 Premarket:")
    print(f"   Prev Close: ${analysis['prev_close']}")
    print(f"   Premarket:  ${analysis['premarket_price']} ({analysis['premarket_gap_pct']:+.2f}%)")

    print(f"\n🚀 Opening Spike (9:30-9:35):")
    print(f"   9:30 Open:  ${analysis['open_9_30']}")
    print(f"   9:35 High:  ${analysis['high_9_35']}")
    print(f"   Spike:      {analysis['spike_9_35_pct']:+.2f}% in 5 minutes")

    print(f"\n🔥 Peak:")
    print(f"   High:       ${analysis['high_of_day']} @ {analysis['high_time']}")
    print(f"   Time to peak: {analysis['minutes_to_peak']} minutes from open")

    print(f"\n🎯 Pick Analysis (@ {analysis.get('pick_time', '9:50')}):")
    print(f"   Price:      ${analysis['price_at_pick']}")
    print(f"   vs Open:    {analysis['pick_vs_open_pct']:+.2f}%")
    print(f"   vs Peak:    {analysis['pick_vs_peak_pct']:+.2f}% ({'GOOD' if analysis['pick_vs_peak_pct'] > -5 else 'LATE'})")

    print(f"\n📉 Fade:")
    if analysis['fade_10pct_time']:
        print(f"   -10% @ {analysis['fade_10pct_time']} ({analysis['minutes_peak_to_fade']} min after peak)")
    else:
        print(f"   -10%: Never faded")

    if analysis['fade_20pct_time']:
        print(f"   -20% @ {analysis['fade_20pct_time']}")

    print(f"\n📊 End of Day:")
    print(f"   Close:      ${analysis['close_price']}")
    print(f"   vs Peak:    {analysis['close_vs_peak_pct']:+.2f}%")

    print(f"\n🏷️  Classification:")
    print(f"   Pattern:    {analysis['pattern']}")
    print(f"   Watchlist:  {'✅' if analysis['in_watchlist'] else '❌'}")
    print(f"   Pick:       {'✅' if analysis['is_scanner_pick'] else '❌'}")

    print("\n" + "="*60)


if __name__ == "__main__":
    # Test with today's date and a sample ticker
    today = datetime.now(NY_TZ).strftime("%Y-%m-%d")

    # Example: Analyze RVYL from watchlist
    result = analyze_pd_behavior(
        ticker="RVYL",
        date=today,
        premarket_price=0.54,
        prev_close=0.30,
        pick_time="09:50",
        in_watchlist=True,
        is_scanner_pick=False,
    )

    print_analysis(result)
