"""
Strategy Recommendation Engine
Generates investment strategies for stocks, sectors, and portfolio level.
Includes: Safe, Risky, Momentum, Value, Defensive, and Growth strategies.
"""
import json
import logging
from datetime import date
from pathlib import Path
from typing import List, Dict, Optional
import sys

import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.database import Strategy, Stock

logger = logging.getLogger(__name__)


# ─── Strategy Templates ───────────────────────────────────────────────────────
STRATEGY_TEMPLATES = {
    "momentum_buy": {
        "name": "Momentum Play",
        "type": "Momentum",
        "risk_level": "MODERATE",
        "horizon": "SHORT",
        "description": (
            "Stock is in a strong uptrend with high volume confirmation. "
            "Momentum indicators (MACD, ADX) confirm bullish continuation. "
            "Enter on any minor pullback to EMA-9 or EMA-21."
        ),
        "action": "BUY",
        "rationale_template": "Strong bullish momentum: {reasons}. ADX > 25 confirms trend strength.",
        "risks_template": "Momentum can reverse quickly. Use tight stop-loss at EMA-21.",
    },
    "value_buy": {
        "name": "Value Accumulation",
        "type": "Value",
        "risk_level": "SAFE",
        "horizon": "LONG",
        "description": (
            "Stock appears undervalued based on technical indicators. "
            "RSI in oversold territory, price near historical support. "
            "Accumulate in tranches — buy 1/3 now, 1/3 on a further 5% dip, 1/3 on trend reversal confirmation."
        ),
        "action": "ACCUMULATE",
        "rationale_template": "Value opportunity: RSI oversold at {rsi:.0f}, price near lower Bollinger Band. {reasons}",
        "risks_template": "May continue falling. Strict stop-loss required. Check fundamentals independently.",
    },
    "defensive_hold": {
        "name": "Defensive Hold",
        "type": "Defensive",
        "risk_level": "SAFE",
        "horizon": "LONG",
        "description": (
            "This is a defensive stock from a stable sector (FMCG/Pharma). "
            "Hold for steady dividend yield and capital preservation. "
            "Not suitable for aggressive short-term gains. Ideal for conservative portfolios."
        ),
        "action": "HOLD",
        "rationale_template": "Defensive sector with low beta. Provides portfolio stability. {reasons}",
        "risks_template": "Underperforms during bull markets. Opportunity cost vs growth stocks.",
    },
    "growth_buy": {
        "name": "Growth Investment",
        "type": "Growth",
        "risk_level": "MODERATE",
        "horizon": "MEDIUM",
        "description": (
            "Stock is from a high-growth sector with improving trend signals. "
            "ML models project positive returns over 3-6 months. "
            "Enter on current levels with a medium-term view."
        ),
        "action": "BUY",
        "rationale_template": "Growth opportunity in {sector}. ML forecast shows positive trend. {reasons}",
        "risks_template": "Valuation risk if growth expectations disappoint. Monitor quarterly results.",
    },
    "sell_take_profit": {
        "name": "Book Profits",
        "type": "Momentum",
        "risk_level": "MODERATE",
        "horizon": "SHORT",
        "description": (
            "Stock appears overbought on multiple indicators. "
            "Consider booking partial profits (50%) at current levels. "
            "Keep remaining position with raised stop-loss."
        ),
        "action": "SELL",
        "rationale_template": "Overbought conditions: {reasons}. Consider partial profit booking.",
        "risks_template": "Stocks can stay overbought longer in bull markets. Watch for reversal signals.",
    },
    "risky_speculative": {
        "name": "Speculative Play",
        "type": "Speculative",
        "risk_level": "RISKY",
        "horizon": "SHORT",
        "description": (
            "High-risk, high-reward opportunity. Small-cap or volatile stock with strong "
            "short-term signals. Strict position sizing — max 2-3% of portfolio. "
            "Exit quickly if stop-loss is triggered."
        ),
        "action": "BUY",
        "rationale_template": "Speculative opportunity: {reasons}. High risk-reward setup.",
        "risks_template": "High volatility. Can lose 20-40% quickly. Only for risk-tolerant investors.",
    },
    "avoid": {
        "name": "Avoid / Exit",
        "type": "Risk Management",
        "risk_level": "SAFE",
        "horizon": "SHORT",
        "description": (
            "Multiple bearish signals. Avoid new positions. "
            "If holding, consider reducing exposure. "
            "Wait for trend reversal confirmation before re-entering."
        ),
        "action": "AVOID",
        "rationale_template": "Bearish signals: {reasons}. Risk outweighs potential reward.",
        "risks_template": "Holding against trend can lead to larger losses.",
    },
}


def generate_stock_strategy(
    symbol: str,
    signal: str,
    composite_score: float,
    risk_level: str,
    rsi: float,
    adx: float,
    sector: str,
    current_price: float,
    target_1: float,
    stop_loss: float,
    key_reason: str,
    trend_direction: str,
    market_cap_tier: str,
    ml_signal: str = "WATCH",
) -> Dict:
    """
    Select and customize the appropriate strategy for a stock.
    """
    reasons = key_reason or ""
    rsi = rsi or 50

    # Strategy selection logic based on signal and quantitative setup
    if signal == "BUY":
        if adx and adx > 25 and composite_score >= 58:
            template_key = "momentum_buy"
        elif rsi < 42:
            template_key = "value_buy"
        elif market_cap_tier == "small" or risk_level == "RISKY":
            template_key = "risky_speculative"
        else:
            template_key = "growth_buy"
    elif signal == "SELL":
        template_key = "avoid" if composite_score < 40 else "sell_take_profit"
    elif risk_level == "SAFE":
        template_key = "defensive_hold"
    else:
        template_key = "value_buy" if rsi < 45 else "defensive_hold"

    tmpl = STRATEGY_TEMPLATES[template_key]

    rationale = tmpl["rationale_template"].format(
        reasons=reasons,
        rsi=rsi,
        sector=sector,
    )
    risks = tmpl["risks_template"]

    expected_return = None
    if target_1 and current_price and current_price > 0:
        expected_return = round((target_1 - current_price) / current_price * 100, 2)

    return {
        "strategy_name": tmpl["name"],
        "strategy_type": tmpl["type"],
        "risk_level": tmpl["risk_level"],
        "time_horizon": tmpl["horizon"],
        "description": tmpl["description"],
        "action": tmpl["action"],
        "entry_price": current_price,
        "target_price": target_1,
        "stop_loss": stop_loss,
        "expected_return_pct": expected_return,
        "rationale": rationale,
        "risks": risks,
    }


SECTOR_STRATEGY_TEMPLATES = {
    "BUY": {
        "name": "Sector Overweight",
        "description": "Majority of stocks in this sector show bullish momentum and positive breadth. Consider increasing allocation.",
        "rationale": "Strong sector breadth: positive multi-period returns and high proportion of advancing stocks.",
        "risks": "Sector-level downturns can affect all stocks simultaneously.",
    },
    "SELL": {
        "name": "Sector Underweight",
        "description": "Sector showing relative weakness. Reduce allocation or avoid new entries.",
        "rationale": "Broad sector weakness: negative momentum and declining stock breadth.",
        "risks": "Sector may recover quickly on macroeconomic catalysts.",
    },
    "WATCH": {
        "name": "Sector Neutral",
        "description": "Balanced signals across sector. Selective stock-picking recommended.",
        "rationale": "No strong directional sector trend. Focus on individual high-scoring leaders.",
        "risks": "May lag high-beta sector rotations.",
    },
}


def generate_sector_strategy(
    sector: str,
    sector_signal: str,
    buy_count: int,
    sell_count: int,
    total: int,
    weekly_return: float,
    monthly_return: float,
    risk_weight: str = "medium",
) -> Dict:
    """Generate strategy recommendation for a sector."""
    breadth_pct = (buy_count / total * 100) if total > 0 else 50

    # Determine dynamic action
    if weekly_return > 0.4 or (monthly_return > 3.0 and breadth_pct >= 40):
        action = "BUY"
    elif weekly_return < -0.4 or (monthly_return < -1.0 and breadth_pct < 30):
        action = "SELL"
    else:
        action = "WATCH"

    tmpl = SECTOR_STRATEGY_TEMPLATES.get(action, SECTOR_STRATEGY_TEMPLATES["WATCH"])

    description = (
        f"{tmpl['description']} "
        f"({buy_count}/{total} stocks BUY = {breadth_pct:.0f}% breadth). "
        f"Weekly: {weekly_return:+.1f}%, Monthly: {monthly_return:+.1f}%."
    )

    risk_level = {"low": "SAFE", "medium": "MODERATE", "high": "RISKY"}.get(risk_weight, "MODERATE")

    return {
        "strategy_name": tmpl["name"],
        "strategy_type": "Sector Rotation",
        "risk_level": risk_level,
        "time_horizon": "MEDIUM",
        "description": description,
        "action": action,
        "rationale": tmpl["rationale"],
        "risks": tmpl["risks"],
    }


PORTFOLIO_STRATEGIES = [
    {
        "name": "Conservative Portfolio",
        "risk_level": "SAFE",
        "description": (
            "Allocation: 40% FMCG/Pharma (defensive) + 30% Large-Cap Banking + "
            "20% IT Blue Chips + 10% Gold ETF. Focus on capital preservation with "
            "steady 8-12% annual returns."
        ),
        "action": "HOLD",
        "sectors": ["FMCG & Consumer Staples", "Pharmaceuticals & Healthcare", "Banking & Finance", "IT & Technology"],
        "rationale": "Low beta, high dividend stocks providing downside protection.",
        "risks": "Underperforms in strong bull markets.",
    },
    {
        "name": "Balanced Growth Portfolio",
        "risk_level": "MODERATE",
        "description": (
            "Allocation: 25% IT + 20% Banking + 15% Auto + 15% Pharma + "
            "15% Infra + 10% FMCG. Targets 15-18% annual returns with "
            "manageable drawdowns."
        ),
        "action": "BUY",
        "sectors": ["IT & Technology", "Banking & Finance", "Automobiles & Auto Ancillaries",
                    "Pharmaceuticals & Healthcare", "Construction & Infrastructure"],
        "rationale": "Diversified across growth and defensive sectors.",
        "risks": "Moderate drawdown risk during market corrections.",
    },
    {
        "name": "Aggressive Growth Portfolio",
        "risk_level": "RISKY",
        "description": (
            "Allocation: 30% Midcap IT + 25% Metals + 20% Real Estate + "
            "15% Telecom + 10% Textiles. High-risk, high-reward targeting "
            "25%+ annual returns. Only for risk-tolerant investors."
        ),
        "action": "BUY",
        "sectors": ["Metals & Mining", "Real Estate", "Telecom & Media",
                    "Consumer Discretionary & Retail"],
        "rationale": "Sector rotation play with high beta stocks for maximum gains.",
        "risks": "High drawdown potential (30-50%). Not suitable for short-term goals.",
    },
]


def generate_portfolio_strategies() -> List[Dict]:
    """Return pre-defined portfolio strategy recommendations."""
    return PORTFOLIO_STRATEGIES


def save_all_strategies(session: Session, progress_callback=None):
    """Generate and save strategies for all stocks and sectors."""
    from db.database import Signal, CompositeScore, Stock, TechnicalIndicator, SectorAnalysis

    as_of = session.execute(text("SELECT MAX(date) FROM signals")).scalar()
    today = as_of if as_of else date.today()
    stocks = session.query(Stock).filter(Stock.is_active == True).all()
    total = len(stocks)

    logger.info(f"Generating strategies for {total} stocks...")

    for i, stock in enumerate(stocks):
        try:
            # Get latest signal and score
            sig = session.query(Signal).filter(
                Signal.symbol == stock.symbol
            ).order_by(Signal.date.desc()).first()

            score = session.query(CompositeScore).filter(
                CompositeScore.symbol == stock.symbol
            ).order_by(CompositeScore.date.desc()).first()

            ind = session.query(TechnicalIndicator).filter(
                TechnicalIndicator.symbol == stock.symbol
            ).order_by(TechnicalIndicator.date.desc()).first()

            if sig is None or score is None:
                continue

            strat = generate_stock_strategy(
                symbol=stock.symbol,
                signal=sig.signal,
                composite_score=score.composite_score,
                risk_level=sig.risk_level or "MODERATE",
                rsi=ind.rsi_14 if ind else None,
                adx=ind.adx if ind else None,
                sector=stock.sector,
                current_price=sig.current_price,
                target_1=sig.target_price_1,
                stop_loss=sig.stop_loss,
                key_reason=sig.key_reason,
                trend_direction=ind.trend_direction if ind else "SIDEWAYS",
                market_cap_tier=stock.market_cap_tier or "mid",
                ml_signal="WATCH",
            )

            strat_data = {
                "date": str(today),
                "target_type": "stock",
                "target_name": stock.symbol,
                **strat,
            }
            cols = ", ".join(strat_data.keys())
            placeholders = ", ".join(f":{k}" for k in strat_data.keys())
            session.execute(text(f"INSERT OR REPLACE INTO strategies ({cols}) VALUES ({placeholders})"), strat_data)

        except Exception as e:
            session.rollback()
            logger.error(f"{stock.symbol}: Strategy error: {e}")

        if i % 50 == 0:
            session.commit()

        if progress_callback:
            progress_callback(i + 1, total, stock.symbol)

    session.commit()

    # Sector strategies
    sector_analyses = session.query(SectorAnalysis).filter(
        SectorAnalysis.date == today
    ).all()

    for sa in sector_analyses:
        try:
            strat = generate_sector_strategy(
                sector=sa.sector,
                sector_signal=sa.sector_signal or "WATCH",
                buy_count=sa.buy_signals_count or 0,
                sell_count=sa.sell_signals_count or 0,
                total=sa.total_stocks or 1,
                weekly_return=sa.weekly_return or 0,
                monthly_return=sa.monthly_return or 0,
            )
            strat_data = {
                "date": str(today),
                "target_type": "sector",
                "target_name": sa.sector,
                **strat,
            }
            cols = ", ".join(strat_data.keys())
            placeholders = ", ".join(f":{k}" for k in strat_data.keys())
            session.execute(text(f"INSERT OR REPLACE INTO strategies ({cols}) VALUES ({placeholders})"), strat_data)
        except Exception as e:
            session.rollback()
            logger.error(f"Sector strategy error: {e}")

    session.commit()
    logger.info("✅ Strategy generation complete")
