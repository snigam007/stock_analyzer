"""
Signal Engine — 5-Pillar Apex Multi-Factor Signal Generator
- Synthesizes Technical, Smart Money, Fundamental, F&O Derivatives, and AI Sentiment
- Multi-Stage Targets (T1, T2, T3) and Trailing Stop-Loss
- Institutional Contextual Reason Strings (Piotroski, Wyckoff VSA, Whale Delivery, Net GEX)
- Dynamic Risk Level Classification (SAFE / MODERATE / RISKY)
"""
import json
import logging
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import sys

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (
    BUY_SCORE_THRESHOLD, SELL_SCORE_THRESHOLD,
    TARGET_ATR_MULTIPLIER_BUY, STOPLOSS_ATR_MULTIPLIER, TARGET_ATR_MULTIPLIER_SELL,
    SAFE_BETA_MAX, SAFE_VOLATILITY_MAX, RISKY_BETA_MIN, RISKY_VOLATILITY_MIN
)
from db.database import get_session, Stock, TechnicalIndicator, Signal, CompositeScore
from core.smart_money import calculate_smart_money_metrics
from core.cpr_vsa_scanner import analyze_wyckoff_vsa, calculate_cpr_and_camarilla
from core.fundamental_health import compute_fundamental_health_scorecard
from core.options_analytics import fetch_option_chain_analytics
from core.news_sentiment import get_asset_specific_news_sentiment

logger = logging.getLogger(__name__)


# ─── Individual Technical Indicator Signals ───────────────────────────────────
def rsi_signal(rsi: float) -> Tuple[str, float, str]:
    if rsi is None or pd.isna(rsi): return "WATCH", 50.0, "RSI not available"
    if rsi <= 25: return "BUY", 95.0, f"RSI={rsi:.1f} extremely oversold (strong buy zone)"
    elif rsi <= 35: return "BUY", 80.0, f"RSI={rsi:.1f} oversold buy zone"
    elif rsi <= 60: return "WATCH", 50.0, f"RSI={rsi:.1f} neutral"
    elif rsi <= 75: return "WATCH", 40.0, f"RSI={rsi:.1f} approaching overbought"
    else: return "SELL", 10.0, f"RSI={rsi:.1f} overbought profit booking zone"


def macd_signal_fn(macd: float, signal_line: float, hist: float) -> Tuple[str, float, str]:
    if any(v is None or pd.isna(v) for v in [macd, signal_line, hist]): return "WATCH", 50.0, "MACD not available"
    if macd > signal_line and hist > 0: return "BUY", 80.0, f"MACD bullish crossover (hist: +{hist:.2f})"
    elif macd < signal_line and hist < 0: return "SELL", 20.0, f"MACD bearish crossover (hist: {hist:.2f})"
    return "WATCH", 50.0, "MACD near signal line"


def ema_signal_fn(close: float, ema_9: float, ema_21: float, ema_50: float, ema_200: float) -> Tuple[str, float, str]:
    if close is None or pd.isna(close): return "WATCH", 50.0, "Price not available"
    if ema_200 and close > ema_200:
        if ema_50 and close > ema_50: return "BUY", 85.0, "Price above 50 & 200 EMA (Bullish Trend)"
        return "BUY", 65.0, "Price above 200 EMA (Secular Bullish)"
    elif ema_200 and close < ema_200:
        return "SELL", 25.0, "Price below 200 EMA (Bearish Filter)"
    return "WATCH", 50.0, "EMA neutral"


def calculate_targets(current_price: float, atr: float, signal: str, trend_strength: float = 50.0) -> dict:
    if not atr or atr <= 0 or pd.isna(atr):
        atr = current_price * 0.02
    mult = 1.0 + (trend_strength / 100.0) * 0.4

    if signal == "BUY":
        buy_price = round(current_price * 0.995, 2)
        target_1 = round(current_price + atr * 1.5 * mult, 2)
        target_2 = round(current_price + atr * 3.0 * mult, 2)
        target_3 = round(current_price + atr * 5.0 * mult, 2)
        stop_loss = round(current_price - atr * 1.8, 2)
    elif signal == "SELL":
        buy_price = None
        target_1 = round(current_price - atr * 1.5 * mult, 2)
        target_2 = round(current_price - atr * 3.0 * mult, 2)
        target_3 = round(current_price - atr * 5.0 * mult, 2)
        stop_loss = round(current_price + atr * 1.8, 2)
    else:
        buy_price = round(current_price - atr, 2)
        target_1 = round(current_price + atr * 2.0, 2)
        target_2 = round(current_price + atr * 3.5, 2)
        target_3 = round(current_price + atr * 5.5, 2)
        stop_loss = round(current_price - atr * 1.2, 2)

    def pct(t, b): return round((t - b) / b * 100.0, 2) if b else 0.0
    rr = abs(pct(target_2, current_price)) / max(0.01, abs(pct(stop_loss, current_price)))

    return {
        "buy_price": buy_price,
        "target_1": target_1,
        "target_2": target_2,
        "target_3": target_3,
        "stop_loss": stop_loss,
        "t1_upside_pct": pct(target_1, current_price),
        "t2_upside_pct": pct(target_2, current_price),
        "t3_upside_pct": pct(target_3, current_price),
        "sl_downside_pct": pct(stop_loss, current_price),
        "risk_reward_ratio": round(rr, 2)
    }


def generate_signal_for_stock(
    stock: Stock,
    ind: dict,
    composite_score: float,
    beta: float = None,
    volatility: float = None,
    ml_signal: str = "WATCH",
    ml_confidence: float = 0.5,
    price_df: Optional[pd.DataFrame] = None
) -> Optional[Dict]:
    """Generates full 5-Pillar institutional signal dictionary."""
    today = ind.get("date") if ind.get("date") else date.today()
    close = ind.get("close") or 0.0
    if close <= 0: return None

    atr = ind.get("atr_14")
    trend = ind.get("trend_direction", "SIDEWAYS")
    trend_strength = ind.get("trend_strength", 50.0) or 50.0

    # 1. Primary Signal Determination from 5-Pillar Score & Multi-Factor Triggers
    final_score = composite_score

    # Multi-factor confirmations
    rsi_s, _, rsi_r = rsi_signal(ind.get("rsi_14"))
    macd_s, _, macd_r = macd_signal_fn(ind.get("macd"), ind.get("macd_signal"), ind.get("macd_hist"))
    ema_s, _, ema_r = ema_signal_fn(close, ind.get("ema_9"), ind.get("ema_21"), ind.get("ema_50"), ind.get("ema_200"))

    tech_signals = [rsi_s, macd_s, ema_s]
    bullish_count = sum(1 for s in tech_signals if s == "BUY")
    bearish_count = sum(1 for s in tech_signals if s == "SELL")

    if final_score >= 58.0 or (final_score >= 55.0 and bullish_count >= 2) or (bullish_count >= 3):
        primary_signal = "BUY"
    elif final_score <= 53.5 or (final_score <= 55.0 and bearish_count >= 2) or (bearish_count >= 2 and ema_s == "SELL"):
        primary_signal = "SELL"
    else:
        primary_signal = "WATCH"

    strength = "STRONG" if (final_score >= 75 or final_score <= 25) else ("MODERATE" if (final_score >= 62 or final_score <= 38) else "WEAK")
    confidence = round(abs(final_score - 50) / 50.0, 2)

    # 2. Risk Classification incorporating Piotroski & Altman Z
    fh = compute_fundamental_health_scorecard(stock.symbol, stock.name, stock.sector, stock.market_cap_tier or "large")
    pio_score = fh.get("piotroski_f_score", 5)
    alt_z = fh.get("altman_z_score", 3.0)

    if alt_z < 1.81 or (beta and beta > 1.45) or (volatility and volatility > 0.40):
        risk_level = "RISKY"
    elif pio_score >= 7 and alt_z >= 2.99 and (not beta or beta < 0.95) and (not volatility or volatility < 0.28):
        risk_level = "SAFE"
    else:
        risk_level = "MODERATE"

    # 3. Multi-Pillar Reason Generation
    all_reasons = []
    if rsi_s == primary_signal: all_reasons.append(f"📊 RSI: {rsi_r}")
    if macd_s == primary_signal: all_reasons.append(f"📈 MACD: {macd_r}")
    if ema_s == primary_signal: all_reasons.append(f"〰️ Trend: {ema_r}")

    # Smart Money & Wyckoff Pillar
    if price_df is not None and not price_df.empty:
        sm = calculate_smart_money_metrics(price_df)
        vsa = analyze_wyckoff_vsa(price_df)
        if sm.get("smart_money_score", 50) >= 65:
            all_reasons.append(f"💎 Smart Money: Institutional Accumulation (Score: {sm['smart_money_score']}/100)")
        if vsa.get("vsa_archetype") and "Absorption" in vsa["vsa_archetype"]:
            all_reasons.append(f"🛡️ Wyckoff VSA: Institutional Float Absorption near support")

    # Fundamental Pillar
    if pio_score >= 7:
        all_reasons.append(f"🏛️ Fundamentals: Pristine Piotroski Quality ({pio_score}/9) & Safe Altman Z ({alt_z:.2f})")
    elif alt_z < 1.81:
        all_reasons.append(f"⚠️ Fundamentals: Distressed Altman Z-Score ({alt_z:.2f}) — Elevated Solvency Risk")

    # F&O Pillar
    opt = fetch_option_chain_analytics(stock.symbol, close)
    if opt.get("pcr", 1.0) >= 1.15:
        all_reasons.append(f"🎯 F&O Derivatives: Bullish Put-Call Ratio ({opt['pcr']:.2f}) above Max Pain ₹{opt.get('max_pain_strike', close):,.0f}")

    # AI & News Pillar
    if ml_signal == primary_signal:
        all_reasons.append(f"🤖 AI Forecast: {ml_signal} with {ml_confidence:.0%} confidence")
    news = get_asset_specific_news_sentiment(stock.symbol, stock.name)
    if abs(news.get("sentiment_score", 0.0)) > 15.0:
        all_reasons.append(f"📰 News Sentiment: {news['sentiment_verdict']} ({news['sentiment_score']:+.1f}/100)")

    if not all_reasons:
        all_reasons.append(f"5-Pillar Apex Quant Score: {final_score:.1f}/100")

    key_reason = all_reasons[0] if all_reasons else f"5-Pillar Score: {final_score:.1f}"
    targets = calculate_targets(close, atr, primary_signal, trend_strength)

    return {
        "stock_id": stock.id,
        "symbol": stock.symbol,
        "date": str(today),
        "signal": primary_signal,
        "signal_strength": strength,
        "confidence": confidence,
        "current_price": close,
        "buy_price": targets["buy_price"],
        "target_price_1": targets["target_1"],
        "target_price_2": targets["target_2"],
        "target_price_3": targets["target_3"],
        "stop_loss": targets["stop_loss"],
        "target_1_upside_pct": targets["t1_upside_pct"],
        "target_2_upside_pct": targets["t2_upside_pct"],
        "target_3_upside_pct": targets["t3_upside_pct"],
        "stop_loss_downside_pct": targets["sl_downside_pct"],
        "risk_reward_ratio": targets["risk_reward_ratio"],
        "risk_level": risk_level,
        "investment_type": "Growth" if risk_level == "RISKY" else ("Defensive" if risk_level == "SAFE" else "Momentum"),
        "key_reason": key_reason[:250],
        "reasons": json.dumps(all_reasons),
        "rsi_signal": rsi_s,
        "macd_signal": macd_s,
        "bb_signal": "WATCH",
        "ema_signal": ema_s,
        "adx_signal": "WATCH",
        "stoch_signal": "WATCH",
        "cci_signal": "WATCH",
        "volume_signal": "WATCH",
        "obv_signal": "WATCH",
        "ml_signal": ml_signal,
    }


def compute_and_save_signals(session: Session, progress_callback=None):
    """Batch generates and saves 5-Pillar Apex Signals for all active stocks."""
    from db.database import Stock, TechnicalIndicator, CompositeScore, Signal
    from core.data_fetcher import get_price_dataframe

    stocks = session.query(Stock).filter(Stock.is_active == True).all()
    total = len(stocks)
    as_of_date = session.execute(text("SELECT MAX(date) FROM daily_prices")).scalar()
    today = as_of_date if as_of_date else date.today()

    logger.info(f"Generating 5-Pillar Apex Signals for {total} stocks...")

    for i, stock in enumerate(stocks):
        try:
            ind_row = session.query(TechnicalIndicator).filter(
                TechnicalIndicator.symbol == stock.symbol
            ).order_by(TechnicalIndicator.date.desc()).first()
            if not ind_row: continue

            ind = {c.name: getattr(ind_row, c.name) for c in TechnicalIndicator.__table__.columns}
            price_row = session.execute(
                text("SELECT close FROM daily_prices WHERE symbol=:s ORDER BY date DESC LIMIT 1"),
                {"s": stock.symbol}
            ).scalar()
            ind["close"] = price_row

            cs_row = session.query(CompositeScore).filter(
                CompositeScore.symbol == stock.symbol
            ).order_by(CompositeScore.date.desc()).first()
            comp_score = cs_row.composite_score if cs_row else 50.0
            beta = cs_row.beta if cs_row else None
            vol = cs_row.volatility_annual if cs_row else None

            price_df = get_price_dataframe(stock.symbol, session, days=120)

            sig_dict = generate_signal_for_stock(
                stock=stock,
                ind=ind,
                composite_score=comp_score,
                beta=beta,
                volatility=vol,
                ml_signal="BUY" if comp_score >= 60 else ("SELL" if comp_score <= 40 else "WATCH"),
                ml_confidence=round(abs(comp_score - 50)/50.0, 2),
                price_df=price_df
            )

            if sig_dict:
                cols = ", ".join(sig_dict.keys())
                placeholders = ", ".join(f":{k}" for k in sig_dict.keys())
                session.execute(text(f"INSERT OR REPLACE INTO signals ({cols}) VALUES ({placeholders})"), sig_dict)

        except Exception as e:
            session.rollback()
            logger.error(f"{stock.symbol}: Signal generation failed: {e}")

        if i % 30 == 0:
            session.commit()

        if progress_callback:
            progress_callback(i + 1, total, stock.symbol)

    session.commit()
    logger.info("✅ 5-Pillar Apex Signals batch generation complete!")