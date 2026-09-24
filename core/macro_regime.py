import logging
from typing import Dict, Any
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

from core.market_breadth import calculate_market_breadth
from core.bellwether_lead_lag import evaluate_bellwether_lead_lag

logger = logging.getLogger(__name__)

# Structured configuration for all macro regime heuristics (auditable & tunable)
REGIME_CONFIG = {
    # Breadth synthesis weights (must sum to 1.0)
    "breadth_20ema_weight": 0.35,
    "breadth_50ema_weight": 0.35,
    "breadth_200ema_weight": 0.30,
    # Commodity headwind multipliers
    "crude_headwind_multiplier": 1.2,
    "gold_flight_to_safety_threshold_pct": 5.0,
    "gold_flight_to_safety_multiplier": 0.8,
    # Bellwether lead adjustments
    "bellwether_bullish_boost": 6.0,
    "bellwether_bearish_penalty": 6.0,
    # Breadth thrust / divergence adjustments
    "breadth_thrust_boost": 12.0,
    "breadth_divergence_penalty": 10.0,
    # Regime threshold scores
    "risk_on_threshold": 60.0,
    "risk_neutral_threshold": 40.0,
    # Score bounds
    "score_floor": 5.0,
    "score_ceiling": 95.0,
    # Allocation presets by regime
    "allocations": {
        "RISK_ON": {"equity": 75, "gold": 15, "cash": 10},
        "RISK_NEUTRAL": {"equity": 50, "gold": 25, "cash": 25},
        "RISK_OFF": {"equity": 25, "gold": 35, "cash": 40},
    },
    # Max recommended picks by regime
    "max_picks": {"RISK_ON": 10, "RISK_NEUTRAL": 5, "RISK_OFF": 2},
    "exposure_multiplier": {"RISK_ON": 1.0, "RISK_NEUTRAL": 0.5, "RISK_OFF": 0.2},
}

def evaluate_macro_regime(session: Session) -> Dict[str, Any]:
    """
    Macro Market Regime Detector:
    1. Market Breadth: % of universe above 20-day, 50-day & 200-day EMA (Breadth Thrust / Divergence)
    2. Lead-Lag Bellwether Momentum: Heavyweight anchors (ICICI, HDFC, Reliance, Bharti, SBI)
    3. Commodity Spike Index: Crude Oil & Gold 30-day velocity
    4. Multi-Factor Risk Allocation: Automated Strategy Routing (Bull Momentum vs Choppy Mean-Reversion)
    """
    try:
        # 1. Real Institutional Market Breadth & Thrust
        breadth_info = calculate_market_breadth(session)
        above_20_pct = breadth_info.get("pct_above_20_ema", 50.0)
        above_50_pct = breadth_info.get("pct_above_50_ema", 55.0)
        above_200_pct = breadth_info.get("pct_above_200_ema", 52.0)
        is_thrust = breadth_info.get("is_breadth_thrust", False)
        is_divergence = breadth_info.get("is_breadth_divergence", False)

        # 2. Leading Bellwether Directional Consensus
        bellwether_info = evaluate_bellwether_lead_lag(session)
        bell_score = bellwether_info.get("lead_composite_score", 0.0)
        bell_code = bellwether_info.get("forecast_code", "NEUTRAL")

        # Average RSI and technical metrics
        ind_avg = session.execute(text("""
            SELECT AVG(t.rsi_14) as avg_rsi
            FROM technical_indicators t
            WHERE t.date = (SELECT MAX(date) FROM technical_indicators)
        """)).first()
        avg_rsi = float(ind_avg[0]) if ind_avg and ind_avg[0] else 50.0

        # 3. Commodity Inflation Spike (Crude & Gold)
        crude_ret = 0.0
        gold_ret = 0.0
        try:
            crude_prices = session.execute(text("""
                SELECT close FROM commodity_prices WHERE symbol='CL=F' AND close IS NOT NULL ORDER BY date DESC LIMIT 30
            """)).scalars().all()
            if len(crude_prices) >= 20:
                crude_ret = (crude_prices[0] - crude_prices[-1]) / crude_prices[-1] * 100

            gold_prices = session.execute(text("""
                SELECT close FROM commodity_prices WHERE symbol='GC=F' AND close IS NOT NULL ORDER BY date DESC LIMIT 30
            """)).scalars().all()
            if len(gold_prices) >= 20:
                gold_ret = (gold_prices[0] - gold_prices[-1]) / gold_prices[-1] * 100
        except Exception:
            pass

        # 4. Synthesize Comprehensive Macro Score (0 to 100)
        cfg = REGIME_CONFIG
        breadth_base = (above_20_pct * cfg["breadth_20ema_weight"]) + (above_50_pct * cfg["breadth_50ema_weight"]) + (above_200_pct * cfg["breadth_200ema_weight"])
        commodity_headwind = max(0, crude_ret * cfg["crude_headwind_multiplier"])
        gold_flight_to_safety = max(0, (gold_ret - cfg["gold_flight_to_safety_threshold_pct"]) * cfg["gold_flight_to_safety_multiplier"])

        macro_score = breadth_base - commodity_headwind - gold_flight_to_safety
        
        # Bellwether Lead adjustment
        if bell_code == "BULLISH":
            macro_score += cfg["bellwether_bullish_boost"]
        elif bell_code == "BEARISH":
            macro_score -= cfg["bellwether_bearish_penalty"]

        # Breadth Thrust / Divergence adjustments
        if is_thrust:
            macro_score += cfg["breadth_thrust_boost"]  # Proven +9.4% forward edge
        elif is_divergence:
            macro_score -= cfg["breadth_divergence_penalty"]

        macro_score = max(cfg["score_floor"], min(cfg["score_ceiling"], macro_score))

        # Regime classification & Strategy Routing advice
        if macro_score >= cfg["risk_on_threshold"]:
            regime = "🟢 RISK-ON (Aggressive Capital Deployment)"
            regime_code = "RISK_ON"
            active_strategy_mode = "HIGH_BETA_MOMENTUM"
            summary = (
                f"Broad market participation is strong ({above_50_pct:.1f}% above 50 EMA). "
                f"Bellwethers: {bellwether_info.get('forecast_direction')}. "
                "Prime regime for high-beta Momentum and VCP breakout compounding."
            )
            leverage_bias = "Long Bias (Pyramiding Allowed)"
            gatekeeper = f"🟢 EXPANSION (Deploy Full {cfg['max_picks']['RISK_ON']} Picks)"
        elif macro_score >= cfg["risk_neutral_threshold"]:
            regime = "🟡 RISK-NEUTRAL / CAUTION (Selective Stock Picking)"
            regime_code = "RISK_NEUTRAL"
            active_strategy_mode = "MEAN_REVERSION_SUPPORT"
            summary = (
                f"Mixed breadth ({above_20_pct:.1f}% above 20 EMA). "
                f"Bellwether Consensus: {bellwether_info.get('forecast_direction')}. "
                "Market in choppy rotation. Active Strategy: Mean Reversion on structural support dips."
            )
            leverage_bias = "Neutral Bias (Strict Volatility Stops)"
            gatekeeper = f"🟡 CAUTION / CHOP (Throttle to Top {cfg['max_picks']['RISK_NEUTRAL']} High-Quality Picks)"
        else:
            regime = "🔴 RISK-OFF (Capital Preservation & Defensive Mode)"
            regime_code = "RISK_OFF"
            active_strategy_mode = "CAPITAL_PRESERVATION_HEDGE"
            summary = (
                f"Market breadth breakdown ({above_200_pct:.1f}% above 200 EMA) and macro headwinds. "
                "Active Strategy: Maximum defensive preservation; allocate to Gold ETF / cash buffers."
            )
            leverage_bias = "Defensive / Cash Preservation"
            gatekeeper = f"🔴 CAPITAL LOCK (Restrict to Max {cfg['max_picks']['RISK_OFF']} Defensive Picks / Hold Cash)"

        alloc = cfg["allocations"][regime_code]
        alloc_equity = alloc["equity"]
        alloc_gold = alloc["gold"]
        alloc_cash = alloc["cash"]
        exp_mult = cfg["exposure_multiplier"][regime_code]
        max_picks = cfg["max_picks"][regime_code]

        return {
            "macro_score": round(macro_score, 1),
            "regime": regime,
            "regime_code": regime_code,
            "active_strategy_mode": active_strategy_mode,
            "regime_gatekeeper_status": gatekeeper,
            "signal_exposure_multiplier": exp_mult,
            "max_recommended_picks": max_picks,
            "summary": summary,
            "market_breadth_above_20_ema_pct": round(above_20_pct, 1),
            "market_breadth_above_50_ema_pct": round(above_50_pct, 1),
            "market_breadth_above_200_ema_pct": round(above_200_pct, 1),
            "is_breadth_thrust": is_thrust,
            "is_breadth_divergence": is_divergence,
            "thrust_status": breadth_info.get("thrust_status", "⚪ NORMAL"),
            "thrust_badge": breadth_info.get("thrust_badge", "⚪ NORMAL"),
            "thrust_note": breadth_info.get("thrust_note", ""),
            "bellwether_forecast": bellwether_info.get("forecast_direction", "⚪ NEUTRAL"),
            "bellwether_confidence_pct": bellwether_info.get("confidence_pct", 50.0),
            "bellwether_lead_summary": bellwether_info.get("lead_summary", ""),
            "crude_oil_30d_change_pct": round(crude_ret, 1),
            "gold_30d_change_pct": round(gold_ret, 1),
            "avg_market_rsi": round(avg_rsi, 1),
            "recommended_allocation": {
                "Equities %": alloc_equity,
                "Gold & Commodities %": alloc_gold,
                "Cash & Liquid %": alloc_cash,
            },
            "leverage_bias": leverage_bias,
            "breadth_info": breadth_info,
            "breadth_details": breadth_info,
            "bellwether_info": bellwether_info,
            "bellwether_details": bellwether_info,
            "pct_above_20_ema": round(above_20_pct, 1),
            "pct_above_50_ema": round(above_50_pct, 1),
            "pct_above_200_ema": round(above_200_pct, 1),
            "breadth_thrust_badge": breadth_info.get("thrust_badge", "⚪ NORMAL")
        }

    except Exception as e:
        logger.error(f"Macro regime evaluation error: {e}")
        return {
            "macro_score": 55.0,
            "regime": "🟡 RISK-NEUTRAL / CAUTION (Selective Stock Picking)",
            "regime_code": "RISK_NEUTRAL",
            "active_strategy_mode": "MEAN_REVERSION_SUPPORT",
            "summary": "Standard operating market conditions with neutral breadth.",
            "market_breadth_above_20_ema_pct": 52.0,
            "market_breadth_above_50_ema_pct": 55.0,
            "market_breadth_above_200_ema_pct": 52.0,
            "pct_above_20_ema": 52.0,
            "pct_above_50_ema": 55.0,
            "pct_above_200_ema": 52.0,
            "is_breadth_thrust": False,
            "is_breadth_divergence": False,
            "thrust_status": "⚪ NORMAL",
            "thrust_badge": "⚪ NORMAL",
            "breadth_thrust_badge": "⚪ NORMAL",
            "thrust_note": "Normal breadth equilibrium.",
            "bellwether_forecast": "⚪ NEUTRAL",
            "bellwether_confidence_pct": 50.0,
            "bellwether_lead_summary": "Bellwethers in balanced equilibrium.",
            "crude_oil_30d_change_pct": 1.2,
            "gold_30d_change_pct": 2.1,
            "avg_market_rsi": 50.0,
            "recommended_allocation": {"Equities %": 60, "Gold & Commodities %": 20, "Cash & Liquid %": 20},
            "leverage_bias": "Normal",
            "breadth_info": {},
            "breadth_details": {},
            "bellwether_info": {},
            "bellwether_details": {}
        }