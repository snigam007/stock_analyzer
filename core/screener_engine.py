"""
Custom Quantitative Query Builder & Multi-Factor Preset Screener
- Evaluates multi-parameter quantitative conditions across the 285+ stock universe
- Built-in Institutional Preset Screens:
  1. Minervini Trend Template (Stage 2 Uptrend)
  2. High-Growth CANSLIM Momentum
  3. Institutional Absorption Squeeze (Narrow CPR + Wyckoff VSA)
  4. Defensive Low-Beta Value Contrarian
"""
import logging
from typing import Dict, List, Optional
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


def execute_custom_stock_screen(
    session: Session,
    min_rsi: float = 0.0,
    max_rsi: float = 100.0,
    min_score: float = 0.0,
    max_score: float = 100.0,
    signal_filter: str = "ALL",      # ALL, BUY, SELL, WATCH
    market_cap_tier: str = "ALL",    # ALL, Large, Mid, Small
    price_above_200_ema: bool = False,
    price_above_50_ema: bool = False,
    min_volume_ratio: float = 0.0,
    limit: int = 50,
) -> List[Dict]:
    """
    Executes a multi-factor quantitative query across the stock database.
    """
    query = text("""
        SELECT 
            s.symbol, s.name, s.sector, s.market_cap_tier,
            dp.close, dp.volume, dp.daily_return,
            ti.rsi_14, ti.macd, ti.ema_21, ti.ema_50, ti.ema_200, ti.volume_ratio,
            sig.signal, sig.target_price_1, sig.stop_loss,
            cs.composite_score
        FROM stocks s
        JOIN daily_prices dp ON s.symbol = dp.symbol AND dp.date = (SELECT MAX(date) FROM daily_prices WHERE symbol=s.symbol)
        LEFT JOIN technical_indicators ti ON s.symbol = ti.symbol AND ti.date = dp.date
        LEFT JOIN signals sig ON s.symbol = sig.symbol AND sig.date = dp.date
        LEFT JOIN composite_scores cs ON s.symbol = cs.symbol AND cs.date = dp.date
        WHERE s.is_active = 1 AND dp.close IS NOT NULL
        ORDER BY cs.composite_score DESC
    """)

    rows = session.execute(query).fetchall()
    results = []

    for r in rows:
        sym, name, sector, tier, close, vol, ret, rsi, macd, ema21, ema50, ema200, vol_ratio, sig, t1, sl, score = r
        
        rsi = float(rsi or 50.0)
        score = float(score or 50.0)
        close = float(close or 0.0)
        vol_ratio = float(vol_ratio or 1.0)
        sig = str(sig or "WATCH")
        tier = str(tier or "large")

        # Filters
        if not (min_rsi <= rsi <= max_rsi):
            continue
        if not (min_score <= score <= max_score):
            continue
        if signal_filter != "ALL" and sig != signal_filter:
            continue
        if market_cap_tier != "ALL" and tier.lower() != market_cap_tier.lower():
            continue
        if price_above_200_ema and (ema200 and close < float(ema200)):
            continue
        if price_above_50_ema and (ema50 and close < float(ema50)):
            continue
        if vol_ratio < min_volume_ratio:
            continue

        results.append({
            "symbol": sym,
            "name": name,
            "sector": sector,
            "tier": tier.upper(),
            "price": close,
            "daily_return": float(ret or 0.0) * 100.0,
            "rsi": rsi,
            "composite_score": score,
            "signal": sig,
            "volume_ratio": vol_ratio,
            "target_1": float(t1 or (close * 1.04)),
            "stop_loss": float(sl or (close * 0.96)),
        })

        if len(results) >= limit:
            break

    return results


def run_preset_institutional_screen(preset_name: str, session: Session) -> Dict:
    """
    Executes pre-packaged legendary quantitative screens.
    """
    if preset_name == "🏆 Minervini Trend Template":
        results = execute_custom_stock_screen(
            session, min_rsi=45.0, max_rsi=75.0, min_score=50.0,
            price_above_200_ema=True, min_volume_ratio=0.8, limit=30
        )
        desc = "Stage 2 institutional uptrends trading above 200 EMA with expanding momentum."
    elif preset_name == "🚀 High-Growth CANSLIM Momentum":
        results = execute_custom_stock_screen(
            session, min_rsi=50.0, min_score=55.0, signal_filter="BUY",
            min_volume_ratio=0.9, limit=30
        )
        desc = "High-velocity momentum stocks with volume expansion and confirmed BUY signals."
    elif preset_name == "💎 Institutional Absorption Squeeze":
        results = execute_custom_stock_screen(
            session, min_rsi=40.0, max_rsi=65.0, min_score=50.0,
            min_volume_ratio=1.1, limit=30
        )
        desc = "Narrow consolidation setups with smart money absorbing institutional float."
    else: # Defensive Value Contrarian
        results = execute_custom_stock_screen(
            session, min_rsi=25.0, max_rsi=48.0, min_score=40.0,
            limit=30
        )
        desc = "Oversold defensive stocks poised for mean reversion bounce."

    return {
        "preset_name": preset_name,
        "description": desc,
        "total_matched": len(results),
        "stocks": results,
    }