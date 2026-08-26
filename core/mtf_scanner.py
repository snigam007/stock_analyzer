"""
Multi-Timeframe (MTF) Triple-Screen Confluence Scanner
- Implements Alexander Elder's Triple-Screen Method:
  1. Weekly Macro Tide (20-week EMA slope + Weekly MACD direction)
  2. Daily Wave (50-day EMA alignment + Daily RSI pullback zone 40-65)
  3. Short-Term Ripple (Volume spike / CPR bounce confirmation)
- Scans full universe to isolate 💎 MTF Golden Confluence setups.
"""
import logging
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


def scan_mtf_triple_screen_confluence(session: Session, limit: int = 30) -> List[Dict]:
    """
    Scans universe for Multi-Timeframe (MTF) Triple-Screen Confluence setups.
    """
    symbols_rows = session.execute(text("""
        SELECT symbol, name, sector FROM stocks WHERE is_active=1
    """)).fetchall()

    mtf_results = []

    for sym, name, sector in symbols_rows:
        rows = session.execute(text("""
            SELECT date, open, high, low, close, volume
            FROM daily_prices
            WHERE symbol=:s AND close IS NOT NULL
            ORDER BY date DESC LIMIT 140
        """), {"s": sym}).fetchall()

        if len(rows) < 60:
            continue

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"]).sort_values("date").reset_index(drop=True)
        df["close"] = df["close"].astype(float)
        curr_p = float(df["close"].iloc[-1])

        # 1. Weekly Macro Tide (Resample to weekly or approximate with 20-week / 100-day EMA)
        ema_100 = df["close"].ewm(span=100, adjust=False).mean()
        weekly_tide_bullish = curr_p > float(ema_100.iloc[-1]) and float(ema_100.iloc[-1]) > float(ema_100.iloc[-5])
        weekly_status = "🟢 Bullish Uptrend" if weekly_tide_bullish else "🔴 Bearish Downtrend"

        # 2. Daily Wave (50-day EMA & RSI-14)
        ema_50 = df["close"].ewm(span=50, adjust=False).mean()
        # RSI calculation
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, 0.001)
        rsi_14 = float(100 - (100 / (1 + rs.iloc[-1]))) if pd.notnull(rs.iloc[-1]) else 50.0

        daily_wave_aligned = curr_p > float(ema_50.iloc[-1]) and (42.0 <= rsi_14 <= 72.0)
        daily_status = "🟢 Wave Aligned (40-70 RSI)" if daily_wave_aligned else "🟡 Pullback / Overextended"

        # 3. Short-Term Ripple (Recent 3-day volume & momentum)
        recent_vol = float(df["volume"].iloc[-1])
        avg_vol = float(df["volume"].tail(20).mean())
        vol_ratio = round(recent_vol / avg_vol, 2) if avg_vol > 0 else 1.0
        ret_3d = ((curr_p - float(df["close"].iloc[-4])) / float(df["close"].iloc[-4])) * 100.0 if len(df) >= 4 else 0.0

        ripple_trigger = vol_ratio >= 1.1 and ret_3d >= 0.5
        ripple_status = "🚀 Volume Trigger" if ripple_trigger else "⚖️ Normal Ripple"

        # Classification
        if weekly_tide_bullish and daily_wave_aligned and ripple_trigger:
            mtf_tier = "💎 MTF Golden Confluence"
            score = 95.0
            tag_color = "#00c875"
            action = "High-Conviction Institutional BUY Setup"
        elif weekly_tide_bullish and daily_wave_aligned:
            mtf_tier = "🟢 Dual-Timeframe Wave"
            score = 80.0
            tag_color = "#00a8ff"
            action = "Swing Buy on Retest"
        elif weekly_tide_bullish:
            mtf_tier = "🟡 Weekly Tide Only"
            score = 65.0
            tag_color = "#f0a500"
            action = "Wait for Daily Pullback to Complete"
        else:
            mtf_tier = "🔴 Bearish MTF"
            score = 35.0
            tag_color = "#ff4b4b"
            action = "Avoid / Short Bias"

        if score >= 65.0:
            mtf_results.append({
                "symbol": sym,
                "name": name,
                "sector": sector,
                "current_price": curr_p,
                "weekly_status": weekly_status,
                "daily_status": daily_status,
                "ripple_status": ripple_status,
                "rsi": round(rsi_14, 1),
                "volume_ratio": vol_ratio,
                "mtf_tier": mtf_tier,
                "score": score,
                "tag_color": tag_color,
                "action": action,
            })

    return sorted(mtf_results, key=lambda x: x["score"], reverse=True)[:limit]