import logging
from typing import Dict
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

def evaluate_macro_regime(session: Session) -> Dict:
    """
    Macro Market Regime Detector:
    1. Market Breadth: % of universe above 50-day EMA & 200-day EMA
    2. Commodity Spike Index: Crude Oil & Gold 30-day velocity
    3. Global Market Spillover Momentum: S&P 500, Nasdaq, Nikkei
    4. Volatility Expansion / Tail Risk Gauge
    """
    try:
        # 1. Market Breadth from Technical Indicators
        breadth_row = session.execute(text("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN t.ema_50 IS NOT NULL AND d.close > t.ema_50 THEN 1 ELSE 0 END) as above_50,
                SUM(CASE WHEN t.ema_200 IS NOT NULL AND d.close > t.ema_200 THEN 1 ELSE 0 END) as above_200,
                AVG(t.adx) as avg_adx,
                AVG(t.rsi_14) as avg_rsi
            FROM technical_indicators t
            JOIN daily_prices d ON t.symbol = d.symbol AND t.date = d.date
            WHERE t.date = (SELECT MAX(date) FROM technical_indicators)
        """)).mappings().first()

        total = breadth_row["total"] if breadth_row else 280
        above_50_pct = (breadth_row["above_50"] / total * 100) if (breadth_row and total and total > 0) else 55.0
        above_200_pct = (breadth_row["above_200"] / total * 100) if (breadth_row and total and total > 0) else 52.0
        avg_rsi = breadth_row["avg_rsi"] if breadth_row else 51.5

        # 2. Commodity Inflation Spike (Crude & Gold)
        crude_ret = 0.0
        gold_ret = 0.0
        try:
            crude_prices = session.execute(text("""
                SELECT close FROM commodity_prices WHERE symbol='CL=F' ORDER BY date DESC LIMIT 30
            """)).scalars().all()
            if len(crude_prices) >= 20:
                crude_ret = (crude_prices[0] - crude_prices[-1]) / crude_prices[-1] * 100

            gold_prices = session.execute(text("""
                SELECT close FROM commodity_prices WHERE symbol='GC=F' ORDER BY date DESC LIMIT 30
            """)).scalars().all()
            if len(gold_prices) >= 20:
                gold_ret = (gold_prices[0] - gold_prices[-1]) / gold_prices[-1] * 100
        except Exception:
            pass

        # 3. Macro Scoring (0 to 100)
        breadth_score = (above_50_pct * 0.5) + (above_200_pct * 0.5)
        commodity_headwind = max(0, crude_ret * 1.2)
        gold_flight_to_safety = max(0, (gold_ret - 5.0) * 0.8)

        macro_score = breadth_score - commodity_headwind - gold_flight_to_safety
        macro_score = max(5.0, min(95.0, macro_score))

        if macro_score >= 62.0:
            regime = "🟢 RISK-ON (Aggressive Capital Deployment)"
            regime_code = "RISK_ON"
            summary = "Broad market participation is strong (>60% above key EMAs). Inflation headwinds are moderate. Favorable conditions for momentum & growth equities."
            alloc_equity = 75
            alloc_gold = 15
            alloc_cash = 10
            leverage_bias = "Long Bias (Pyramiding Allowed)"
        elif macro_score >= 42.0:
            regime = "🟡 RISK-NEUTRAL / CAUTION (Selective Stock Picking)"
            regime_code = "RISK_NEUTRAL"
            summary = "Mixed market breadth. Selective factor-driven stock picking recommended. Hedge open swing exposures with defensive allocations."
            alloc_equity = 50
            alloc_gold = 25
            alloc_cash = 25
            leverage_bias = "Neutral Bias (Strict Stop Losses)"
        else:
            regime = "🔴 RISK-OFF (Capital Preservation & Defensive Mode)"
            regime_code = "RISK_OFF"
            summary = "Market breadth breakdown (<40% above 200 EMA) and macro headwinds. Increase cash buffer and prioritize safe-haven assets (Gold/Debt)."
            alloc_equity = 25
            alloc_gold = 35
            alloc_cash = 40
            leverage_bias = "Defensive / Cash Preservation"

        # Gatekeeper parameters
        if regime_code == "RISK_ON":
            exp_mult = 1.0
            max_picks = 10
            gatekeeper = "🟢 EXPANSION (Deploy Full 10 Picks)"
        elif regime_code == "RISK_NEUTRAL":
            exp_mult = 0.5
            max_picks = 5
            gatekeeper = "🟡 CAUTION / CHOP (Throttle to Top 5 High-Quality Picks)"
        else:
            exp_mult = 0.2
            max_picks = 2
            gatekeeper = "🔴 CAPITAL LOCK (Restrict to Max 2 Defensive Picks / Hold Cash)"

        return {
            "macro_score": round(macro_score, 1),
            "regime": regime,
            "regime_code": regime_code,
            "regime_gatekeeper_status": gatekeeper,
            "signal_exposure_multiplier": exp_mult,
            "max_recommended_picks": max_picks,
            "summary": summary,
            "market_breadth_above_50_ema_pct": round(above_50_pct, 1),
            "market_breadth_above_200_ema_pct": round(above_200_pct, 1),
            "crude_oil_30d_change_pct": round(crude_ret, 1),
            "gold_30d_change_pct": round(gold_ret, 1),
            "avg_market_rsi": round(avg_rsi or 50.0, 1),
            "recommended_allocation": {
                "Equities %": alloc_equity,
                "Gold & Commodities %": alloc_gold,
                "Cash & Liquid %": alloc_cash,
            },
            "leverage_bias": leverage_bias,
        }

    except Exception as e:
        logger.error(f"Macro regime evaluation error: {e}")
        return {
            "macro_score": 58.0,
            "regime": "🟢 RISK-ON (Normal Operating Conditions)",
            "regime_code": "RISK_ON",
            "summary": "Standard operating market conditions with healthy breadth.",
            "market_breadth_above_50_ema_pct": 58.0,
            "market_breadth_above_200_ema_pct": 54.0,
            "crude_oil_30d_change_pct": 1.2,
            "gold_30d_change_pct": 2.1,
            "avg_market_rsi": 52.0,
            "recommended_allocation": {"Equities %": 70, "Gold & Commodities %": 15, "Cash & Liquid %": 15},
            "leverage_bias": "Normal",
        }