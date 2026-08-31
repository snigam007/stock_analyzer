"""
Candlestick Pattern Recognition Engine — 15 Pure NumPy/Pandas Formations
- Zero C-extension / external library build dependencies
- High-precision vectorized candle geometry calculations
- Reversal and Continuation sentiment labeling with reliability scoring (1-5)
- Automated batch scanner and database storage
"""
import logging
from datetime import date, datetime
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

import importlib
import db.database
if not hasattr(db.database, "CandlestickPatternRecord"):
    importlib.reload(db.database)
from db.database import CandlestickPatternRecord, Stock, DailyPrice

logger = logging.getLogger(__name__)

# Pattern metadata definition
PATTERN_METADATA = {
    "Hammer": {
        "sentiment": "BULLISH", "reliability": 3, "candles": 1,
        "description": "Bullish reversal signal. Buyers rejected lower prices with a long lower wick."
    },
    "Inverted Hammer": {
        "sentiment": "BULLISH", "reliability": 3, "candles": 1,
        "description": "Bullish reversal attempt after a downtrend. Upper wick indicates buying pressure."
    },
    "Hanging Man": {
        "sentiment": "BEARISH", "reliability": 3, "candles": 1,
        "description": "Bearish reversal signal at swing highs. Heavy selling during session despite recovery."
    },
    "Shooting Star": {
        "sentiment": "BEARISH", "reliability": 4, "candles": 1,
        "description": "Strong bearish reversal at resistance. Bulls pushed high but were completely rejected."
    },
    "Bullish Engulfing": {
        "sentiment": "BULLISH", "reliability": 4, "candles": 2,
        "description": "Major bullish reversal. Large green candle completely engulfs prior red candle body."
    },
    "Bearish Engulfing": {
        "sentiment": "BEARISH", "reliability": 4, "candles": 2,
        "description": "Major bearish reversal. Large red candle completely engulfs prior green candle body."
    },
    "Morning Star": {
        "sentiment": "BULLISH", "reliability": 5, "candles": 3,
        "description": "High-conviction 3-bar bottom reversal: Long Red -> Indecision Gap -> Strong Green."
    },
    "Evening Star": {
        "sentiment": "BEARISH", "reliability": 5, "candles": 3,
        "description": "High-conviction 3-bar top reversal: Long Green -> Indecision Gap -> Strong Red."
    },
    "Doji": {
        "sentiment": "INDECISION", "reliability": 2, "candles": 1,
        "description": "Market equilibrium / indecision. Open and Close are virtually equal."
    },
    "Dragonfly Doji": {
        "sentiment": "BULLISH", "reliability": 4, "candles": 1,
        "description": "Strong bullish support. Long lower shadow with open, high, and close near the top."
    },
    "Gravestone Doji": {
        "sentiment": "BEARISH", "reliability": 4, "candles": 1,
        "description": "Strong bearish rejection. Long upper shadow with open, low, and close near the bottom."
    },
    "Piercing Line": {
        "sentiment": "BULLISH", "reliability": 4, "candles": 2,
        "description": "Bullish reversal. Green candle opens lower but penetrates >50% into prior red body."
    },
    "Dark Cloud Cover": {
        "sentiment": "BEARISH", "reliability": 4, "candles": 2,
        "description": "Bearish reversal. Red candle opens higher but closes deep below >50% of prior green body."
    },
    "Three White Soldiers": {
        "sentiment": "BULLISH", "reliability": 5, "candles": 3,
        "description": "Strong bullish continuation. 3 consecutive long green candles with steady higher closes."
    },
    "Three Black Crows": {
        "sentiment": "BEARISH", "reliability": 5, "candles": 3,
        "description": "Strong bearish continuation. 3 consecutive long red candles with steady lower closes."
    },
}


def scan_candlestick_patterns(df: pd.DataFrame, lookback: int = 5) -> List[Dict]:
    """
    Scans the latest OHLCV dataframe for all 15 candlestick patterns.
    Returns a list of detected pattern dictionaries sorted by date (newest first).
    """
    if df is None or len(df) < 5:
        return []

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    dates = [str(d) for d in df["date"].values] if "date" in df.columns else [str(i) for i in df.index]

    n = len(df)
    results = []

    # Calculate candle component geometry
    body = np.abs(closes - opens)
    body_top = np.maximum(opens, closes)
    body_bottom = np.minimum(opens, closes)
    candle_range = np.maximum(highs - lows, 1e-6)
    upper_shadow = highs - body_top
    lower_shadow = body_bottom - lows
    is_green = closes > opens
    is_red = closes < opens
    is_flat = body / candle_range < 0.05

    # 10-day average body size for scale comparison
    avg_body = pd.Series(body).rolling(10, min_periods=1).mean().values

    # Scan last `lookback` indices
    start_idx = max(3, n - lookback)

    for i in range(start_idx, n):
        curr_date = dates[i]
        curr_close = float(closes[i])
        c_range = candle_range[i]
        b_size = body[i]
        u_shad = upper_shadow[i]
        l_shad = lower_shadow[i]
        mean_b = avg_body[i]

        patterns_today = []

        # ── 1. Doji variations (1-bar) ───────────────────────────────────────
        if b_size / c_range <= 0.08:
            if l_shad >= c_range * 0.65 and u_shad <= c_range * 0.15:
                patterns_today.append("Dragonfly Doji")
            elif u_shad >= c_range * 0.65 and l_shad <= c_range * 0.15:
                patterns_today.append("Gravestone Doji")
            else:
                patterns_today.append("Doji")

        # ── 2. Hammer & Hanging Man (1-bar) ──────────────────────────────────
        if l_shad >= 2.0 * max(b_size, 1e-4) and u_shad <= 0.25 * max(b_size, 1e-4) and b_size >= 0.1 * c_range:
            # Check context: downtrend vs uptrend in previous 3 days
            is_downtrend = closes[i - 1] < closes[max(0, i - 4)]
            if is_downtrend:
                patterns_today.append("Hammer")
            else:
                patterns_today.append("Hanging Man")

        # ── 3. Inverted Hammer & Shooting Star (1-bar) ────────────────────────
        if u_shad >= 2.0 * max(b_size, 1e-4) and l_shad <= 0.25 * max(b_size, 1e-4) and b_size >= 0.1 * c_range:
            is_uptrend = closes[i - 1] > closes[max(0, i - 4)]
            if is_uptrend:
                patterns_today.append("Shooting Star")
            else:
                patterns_today.append("Inverted Hammer")

        # ── 4. Bullish & Bearish Engulfing (2-bar) ───────────────────────────
        if i >= 1:
            prev_b = body[i - 1]
            if is_red[i - 1] and is_green[i] and opens[i] <= closes[i - 1] and closes[i] >= opens[i - 1]:
                if b_size > prev_b * 1.1:
                    patterns_today.append("Bullish Engulfing")

            if is_green[i - 1] and is_red[i] and opens[i] >= closes[i - 1] and closes[i] <= opens[i - 1]:
                if b_size > prev_b * 1.1:
                    patterns_today.append("Bearish Engulfing")

        # ── 5. Piercing Line & Dark Cloud Cover (2-bar) ──────────────────────
        if i >= 1:
            prev_b = body[i - 1]
            prev_mid = (opens[i - 1] + closes[i - 1]) / 2.0

            # Piercing line: prior red, opens lower, closes above prior body midpoint
            if is_red[i - 1] and is_green[i] and opens[i] < lows[i - 1] and closes[i] > prev_mid and closes[i] < opens[i - 1]:
                patterns_today.append("Piercing Line")

            # Dark Cloud Cover: prior green, opens higher, closes below prior body midpoint
            if is_green[i - 1] and is_red[i] and opens[i] > highs[i - 1] and closes[i] < prev_mid and closes[i] > opens[i - 1]:
                patterns_today.append("Dark Cloud Cover")

        # ── 6. Morning Star & Evening Star (3-bar) ───────────────────────────
        if i >= 2:
            # Morning Star: Bar1 large red, Bar2 small body gap down, Bar3 strong green
            if is_red[i - 2] and body[i - 2] >= mean_b * 0.8:
                if body[i - 1] <= body[i - 2] * 0.4 and body_top[i - 1] <= body_bottom[i - 2]:
                    if is_green[i] and closes[i] >= (opens[i - 2] + closes[i - 2]) / 2.0:
                        patterns_today.append("Morning Star")

            # Evening Star: Bar1 large green, Bar2 small body gap up, Bar3 strong red
            if is_green[i - 2] and body[i - 2] >= mean_b * 0.8:
                if body[i - 1] <= body[i - 2] * 0.4 and body_bottom[i - 1] >= body_top[i - 2]:
                    if is_red[i] and closes[i] <= (opens[i - 2] + closes[i - 2]) / 2.0:
                        patterns_today.append("Evening Star")

        # ── 7. Three White Soldiers & Three Black Crows (3-bar) ───────────────
        if i >= 2:
            # 3 White Soldiers: 3 consecutive green candles with higher closes
            if is_green[i - 2] and is_green[i - 1] and is_green[i]:
                if closes[i] > closes[i - 1] > closes[i - 2]:
                    if opens[i] > opens[i - 1] and opens[i] < closes[i - 1]:
                        if u_shad < b_size * 0.35 and upper_shadow[i - 1] < body[i - 1] * 0.35:
                            patterns_today.append("Three White Soldiers")

            # 3 Black Crows: 3 consecutive red candles with lower closes
            if is_red[i - 2] and is_red[i - 1] and is_red[i]:
                if closes[i] < closes[i - 1] < closes[i - 2]:
                    if opens[i] < opens[i - 1] and opens[i] > closes[i - 1]:
                        if l_shad < b_size * 0.35 and lower_shadow[i - 1] < body[i - 1] * 0.35:
                            patterns_today.append("Three Black Crows")

        # Aggregate unique detections for the day
        for pat in set(patterns_today):
            meta = PATTERN_METADATA.get(pat, {})
            results.append({
                "date": curr_date,
                "pattern_name": pat,
                "sentiment": meta.get("sentiment", "NEUTRAL"),
                "reliability": meta.get("reliability", 3),
                "candle_count": meta.get("candles", 1),
                "description": meta.get("description", ""),
                "close_price": curr_close,
            })

    return results


def batch_scan_candlestick_patterns(session: Session, progress_callback=None) -> int:
    """
    Batch scans all active stocks and stores detected candlestick patterns into candlestick_patterns table.
    """
    from core.data_fetcher import get_price_dataframe

    stocks = session.query(Stock).filter(Stock.is_active == True).all()
    total = len(stocks)
    total_saved = 0

    logger.info(f"Scanning candlestick patterns for {total} active stocks...")

    for idx, stock in enumerate(stocks):
        try:
            df = get_price_dataframe(stock.symbol, session, days=30)
            if df is None or len(df) < 5:
                continue

            patterns = scan_candlestick_patterns(df, lookback=3)

            for p in patterns:
                p_date = str(p["date"]).split(" ")[0]

                session.execute(text("""
                    INSERT OR REPLACE INTO candlestick_patterns
                    (symbol, date, pattern_name, sentiment, reliability, candle_count, description, close_price, detected_at)
                    VALUES (:sym, :d, :p_name, :sent, :rel, :cnt, :desc, :close, datetime('now'))
                """), {
                    "sym": stock.symbol,
                    "d": p_date,
                    "p_name": p["pattern_name"],
                    "sent": p["sentiment"],
                    "rel": p["reliability"],
                    "cnt": p["candle_count"],
                    "desc": p["description"],
                    "close": p["close_price"],
                })
                total_saved += 1

            if idx % 25 == 0:
                session.commit()

        except Exception as e:
            session.rollback()
            logger.warning(f"Candlestick scan notice for {stock.symbol}: {e}")

        if progress_callback:
            progress_callback(idx + 1, total, stock.symbol)

    session.commit()
    logger.info(f"Candlestick scanning complete! Saved/updated {total_saved} pattern records.")
    return total_saved


def get_patterns_for_symbol(symbol: str, session: Session, limit: int = 10) -> List[Dict]:
    """Fetch stored candlestick patterns for a given symbol."""
    rows = session.execute(text("""
        SELECT date, pattern_name, sentiment, reliability, candle_count, description, close_price
        FROM candlestick_patterns
        WHERE symbol = :s
        ORDER BY date DESC
        LIMIT :lim
    """), {"s": symbol, "lim": limit}).fetchall()

    return [{
        "date": str(r[0]),
        "pattern_name": r[1],
        "sentiment": r[2],
        "reliability": r[3],
        "candle_count": r[4],
        "description": r[5],
        "close_price": r[6],
    } for r in rows]
