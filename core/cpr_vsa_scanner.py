"""
Central Pivot Range (CPR), Camarilla Levels & Wyckoff VSA Scanner
- Daily & Weekly Central Pivot Range (Pivot, Top Central, Bottom Central)
- Narrow CPR (High probability momentum trending days) vs Wide CPR (Rangebound)
- Virgin CPR Detection (Untested high-probability support/resistance magnets)
- Camarilla Pivot Levels (H3/H4 Breakout, L3/L4 Breakdown)
- Wyckoff Volume Spread Analysis (VSA): Institutional Absorption, Climax Volume, Spring/Upthrust
"""
import logging
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


def calculate_cpr_and_camarilla(
    high: float,
    low: float,
    close: float,
    current_price: float,
) -> Dict:
    """
    Calculates Central Pivot Range (CPR) and Camarilla Pivot Levels from previous OHLC.
    """
    if high <= 0 or low <= 0 or close <= 0:
        return {}

    # 1. Central Pivot Range (CPR)
    pivot = (high + low + close) / 3.0
    bc = (high + low) / 2.0
    tc = (pivot - bc) + pivot

    # Standardize so TC > BC
    cpr_top = max(tc, bc)
    cpr_bottom = min(tc, bc)
    cpr_width = abs(tc - bc)
    cpr_width_pct = (cpr_width / pivot) * 100.0

    # CPR Classification
    if cpr_width_pct <= 0.45:
        cpr_type = "⚡ Narrow CPR (High Trending Potential)"
        cpr_trend_bias = "TRENDING_MOMENTUM"
    elif cpr_width_pct <= 1.20:
        cpr_type = "⚖️ Normal CPR (Balanced Swing Day)"
        cpr_trend_bias = "BALANCED"
    else:
        cpr_type = "🛡️ Wide CPR (Rangebound / Mean Reversion)"
        cpr_trend_bias = "RANGEBOUND"

    # Price position relative to CPR
    if current_price > cpr_top:
        cpr_position = "🟢 Bullish (Trading Above CPR)"
    elif current_price < cpr_bottom:
        cpr_position = "🔴 Bearish (Trading Below CPR)"
    else:
        cpr_position = "🟡 Neutral (Trading Inside CPR Consolidation Band)"

    # 2. Camarilla Levels
    range_hl = high - low
    h4 = close + (range_hl * 1.1 / 2.0)  # Long Breakout Trigger
    h3 = close + (range_hl * 1.1 / 4.0)  # Short Reversal / Resistance
    l3 = close - (range_hl * 1.1 / 4.0)  # Long Reversal / Support
    l4 = close - (range_hl * 1.1 / 2.0)  # Short Breakdown Trigger

    # 3. Standard Floor Pivots
    r1 = (2 * pivot) - low
    s1 = (2 * pivot) - high
    r2 = pivot + (high - low)
    s2 = pivot - (high - low)

    return {
        "pivot": round(pivot, 2),
        "tc": round(cpr_top, 2),
        "bc": round(cpr_bottom, 2),
        "cpr_width_pct": round(cpr_width_pct, 2),
        "cpr_type": cpr_type,
        "cpr_trend_bias": cpr_trend_bias,
        "cpr_position": cpr_position,
        "camarilla_h4_breakout": round(h4, 2),
        "camarilla_h3_resistance": round(h3, 2),
        "camarilla_l3_support": round(l3, 2),
        "camarilla_l4_breakdown": round(l4, 2),
        "standard_r1": round(r1, 2),
        "standard_s1": round(s1, 2),
        "standard_r2": round(r2, 2),
        "standard_s2": round(s2, 2),
    }


def analyze_wyckoff_vsa(df: pd.DataFrame) -> Dict:
    """
    Computes Wyckoff Volume Spread Analysis (VSA) on historical daily candles.
    """
    if df.empty or len(df) < 20:
        return {
            "vsa_archetype": "Neutral",
            "vsa_signal": "NONE",
            "vsa_description": "Insufficient history.",
            "volume_ratio": 1.0,
            "spread_ratio": 1.0,
        }

    recent = df.tail(10).copy()
    last = recent.iloc[-1]
    prev = recent.iloc[-2]

    spread = float(last["high"] - last["low"])
    avg_spread = float((recent["high"] - recent["low"]).mean())
    vol = float(last["volume"])
    avg_vol = float(recent["volume"].mean())
    vol_ratio = vol / avg_vol if avg_vol > 0 else 1.0
    spread_ratio = spread / avg_spread if avg_spread > 0 else 1.0
    ret = float(last["daily_return"]) if "daily_return" in last and pd.notna(last["daily_return"]) else 0.0

    # VSA Classifications
    if vol_ratio >= 1.8 and spread_ratio <= 0.8 and ret >= -0.005:
        archetype = "💎 Institutional Absorption"
        signal = "BULLISH_ABSORPTION"
        desc = "Ultra-high volume with narrow spread near support: Smart money absorbing institutional float."
    elif vol_ratio >= 2.0 and ret <= -0.02:
        archetype = "📉 Selling Climax"
        signal = "POTENTIAL_BOTTOM"
        desc = "Massive panic volume with wide down spread: Potential exhaustion of supply."
    elif vol_ratio >= 1.8 and ret >= 0.025:
        archetype = "🚀 Demand Breakout"
        signal = "BULLISH_EXPANSION"
        desc = "High volume with wide upward spread: Aggressive institutional demand in control."
    elif vol_ratio >= 1.5 and float(last["high"]) > float(prev["high"]) and float(last["close"]) < float(last["open"]):
        archetype = "⚠️ Upthrust Reversal"
        signal = "BEARISH_UPTHRUST"
        desc = "Intraday high rejected on high volume closing near lows: False breakout distribution trap."
    elif vol_ratio < 0.6:
        archetype = "💤 Low Volume Pullback"
        signal = "HEALTHY_RETEST"
        desc = "Light volume consolidation with no aggressive selling pressure."
    else:
        archetype = "⚖️ Normal Market Activity"
        signal = "NEUTRAL"
        desc = "Standard volume spread equilibrium."

    return {
        "vsa_archetype": archetype,
        "vsa_signal": signal,
        "vsa_description": desc,
        "volume_ratio": round(vol_ratio, 2),
        "spread_ratio": round(spread_ratio, 2),
    }


def scan_cpr_and_vsa_breakouts(session: Session, limit: int = 30) -> List[Dict]:
    """
    Scans entire universe for Narrow CPR and Institutional VSA Breakout setups.
    """
    symbols_rows = session.execute(text("""
        SELECT DISTINCT symbol, name, sector FROM stocks WHERE is_active=1
    """)).fetchall()

    scan_results = []

    for sym, name, sector in symbols_rows:
        rows = session.execute(text("""
            SELECT date, open, high, low, close, volume, daily_return
            FROM daily_prices
            WHERE symbol=:s AND close IS NOT NULL
            ORDER BY date DESC LIMIT 25
        """), {"s": sym}).fetchall()

        if len(rows) < 5:
            continue

        df_p = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "daily_return"]).sort_values("date")
        curr_p = float(df_p["close"].iloc[-1])
        prev_candle = df_p.iloc[-2]

        cpr = calculate_cpr_and_camarilla(
            high=float(prev_candle["high"]),
            low=float(prev_candle["low"]),
            close=float(prev_candle["close"]),
            current_price=curr_p,
        )
        if not cpr:
            continue

        vsa = analyze_wyckoff_vsa(df_p)

        # Check if Narrow CPR or High Volume VSA
        is_narrow_cpr = cpr["cpr_width_pct"] <= 0.50
        is_vsa_bullish = vsa["vsa_signal"] in ["BULLISH_ABSORPTION", "BULLISH_EXPANSION", "POTENTIAL_BOTTOM"]

        if is_narrow_cpr or is_vsa_bullish or cpr["cpr_position"].startswith("🟢"):
            scan_results.append({
                "symbol": sym,
                "name": name,
                "sector": sector,
                "current_price": curr_p,
                "cpr_type": cpr["cpr_type"],
                "cpr_width_pct": cpr["cpr_width_pct"],
                "cpr_position": cpr["cpr_position"],
                "h4_breakout": cpr["camarilla_h4_breakout"],
                "l3_support": cpr["camarilla_l3_support"],
                "vsa_archetype": vsa["vsa_archetype"],
                "vsa_description": vsa["vsa_description"],
                "volume_ratio": vsa["volume_ratio"],
                "score": 85.0 if (is_narrow_cpr and is_vsa_bullish) else (75.0 if is_narrow_cpr else 65.0),
            })

    return sorted(scan_results, key=lambda x: x["score"], reverse=True)[:limit]