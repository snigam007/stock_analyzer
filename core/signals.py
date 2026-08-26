"""
Signal Engine — Generates BUY / SELL / WATCH signals with:
- Price targets (Target 1/2/3)
- Stop-loss levels
- Risk-reward ratios
- Individual indicator signals
- Key reasons for each decision
- Safe / Moderate / Risky classification
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

logger = logging.getLogger(__name__)


# ─── Individual Indicator Signal Functions ────────────────────────────────────

def rsi_signal(rsi: float) -> Tuple[str, float, str]:
    """Returns (signal, score 0-100, reason)."""
    if rsi is None or pd.isna(rsi):
        return "WATCH", 50.0, "RSI not available"
    if rsi <= 25:
        return "BUY", 95.0, f"RSI={rsi:.1f} extremely oversold (strong buy zone)"
    elif rsi <= 30:
        return "BUY", 85.0, f"RSI={rsi:.1f} oversold — classic buy signal"
    elif rsi <= 40:
        return "BUY", 65.0, f"RSI={rsi:.1f} approaching oversold zone"
    elif rsi <= 60:
        return "WATCH", 50.0, f"RSI={rsi:.1f} neutral zone"
    elif rsi <= 70:
        return "WATCH", 40.0, f"RSI={rsi:.1f} approaching overbought — caution"
    elif rsi <= 80:
        return "SELL", 20.0, f"RSI={rsi:.1f} overbought — consider booking profits"
    else:
        return "SELL", 5.0, f"RSI={rsi:.1f} extremely overbought — strong sell signal"


def macd_signal_fn(macd: float, signal_line: float, hist: float) -> Tuple[str, float, str]:
    """MACD crossover signal."""
    if any(v is None or pd.isna(v) for v in [macd, signal_line, hist]):
        return "WATCH", 50.0, "MACD data not available"

    if macd > signal_line and hist > 0:
        if hist > abs(macd) * 0.1:
            return "BUY", 80.0, f"MACD bullish crossover — histogram positive ({hist:.2f})"
        return "BUY", 65.0, f"MACD above signal line — bullish"
    elif macd < signal_line and hist < 0:
        if abs(hist) > abs(macd) * 0.1:
            return "SELL", 20.0, f"MACD bearish crossover — histogram negative ({hist:.2f})"
        return "SELL", 35.0, f"MACD below signal line — bearish"
    else:
        return "WATCH", 50.0, f"MACD near signal line — wait for confirmation"


def bollinger_signal(close: float, bb_upper: float, bb_lower: float, bb_pct: float) -> Tuple[str, float, str]:
    """Bollinger Bands signal based on price position."""
    if any(v is None or pd.isna(v) for v in [close, bb_upper, bb_lower]):
        return "WATCH", 50.0, "Bollinger Bands not available"

    if bb_pct is not None and not pd.isna(bb_pct):
        if bb_pct <= 0.05:
            return "BUY", 90.0, f"Price at/below lower Bollinger Band — strong mean reversion buy"
        elif bb_pct <= 0.2:
            return "BUY", 75.0, f"Price near lower Bollinger Band — potential bounce"
        elif bb_pct >= 0.95:
            return "SELL", 10.0, f"Price at/above upper Bollinger Band — overbought"
        elif bb_pct >= 0.8:
            return "SELL", 25.0, f"Price near upper Bollinger Band — consider taking profits"
        else:
            return "WATCH", 50.0, f"Price within Bollinger Bands — no clear signal"

    pct_pos = (close - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5
    if pct_pos <= 0.1:
        return "BUY", 85.0, "Price at lower band — mean reversion opportunity"
    elif pct_pos >= 0.9:
        return "SELL", 15.0, "Price at upper band — overbought"
    return "WATCH", 50.0, "Price within bands"


def ema_signal_fn(close: float, ema_9: float, ema_21: float, ema_50: float, ema_200: float) -> Tuple[str, float, str]:
    """EMA crossover and trend alignment signal."""
    valid = [(v, n) for v, n in [(ema_9, 9), (ema_21, 21), (ema_50, 50), (ema_200, 200)] if v and not pd.isna(v)]
    if not valid or close is None or pd.isna(close):
        return "WATCH", 50.0, "EMA data not available"

    reasons = []
    score = 50.0
    signal = "WATCH"

    # Golden Cross: 50 above 200
    if ema_50 and ema_200 and not pd.isna(ema_50) and not pd.isna(ema_200):
        if ema_50 > ema_200:
            score += 15
            reasons.append(f"Golden Cross: EMA50({ema_50:.0f}) > EMA200({ema_200:.0f})")
        else:
            score -= 15
            reasons.append(f"Death Cross: EMA50({ema_50:.0f}) < EMA200({ema_200:.0f})")

    # Price above/below key EMAs
    emas_above = sum(1 for v, _ in valid if close > v)
    total_emas = len(valid)
    score += (emas_above / total_emas - 0.5) * 40

    if close > (ema_200 or 0) and close > (ema_50 or 0):
        reasons.append(f"Price above EMA50 & EMA200 — bullish alignment")
        score += 10
    elif close < (ema_200 or float("inf")) and close < (ema_50 or float("inf")):
        reasons.append(f"Price below EMA50 & EMA200 — bearish alignment")
        score -= 10

    score = max(0, min(100, score))
    if score >= 65:
        signal = "BUY"
    elif score <= 35:
        signal = "SELL"
    else:
        signal = "WATCH"

    reason = "; ".join(reasons) if reasons else "EMA signals mixed"
    return signal, score, reason


def adx_signal_fn(adx: float, di_plus: float, di_minus: float) -> Tuple[str, float, str]:
    """ADX trend strength signal."""
    if adx is None or pd.isna(adx):
        return "WATCH", 50.0, "ADX not available"

    if adx < 20:
        return "WATCH", 50.0, f"ADX={adx:.1f} — weak trend, range-bound market"
    elif adx >= 20 and di_plus and di_minus and not pd.isna(di_plus) and not pd.isna(di_minus):
        if di_plus > di_minus:
            strength = min(90, 50 + adx)
            return "BUY", strength, f"ADX={adx:.1f} strong trend, +DI({di_plus:.1f}) > -DI({di_minus:.1f}) — bullish"
        else:
            strength = max(10, 50 - adx)
            return "SELL", strength, f"ADX={adx:.1f} strong trend, -DI({di_minus:.1f}) > +DI({di_plus:.1f}) — bearish"
    return "WATCH", 50.0, f"ADX={adx:.1f} moderate trend"


def stochastic_signal(k: float, d: float) -> Tuple[str, float, str]:
    """Stochastic oscillator signal."""
    if k is None or pd.isna(k):
        return "WATCH", 50.0, "Stochastic not available"

    if k <= 20 and (d is None or d <= 25):
        return "BUY", 85.0, f"Stochastic K={k:.1f} oversold — buy signal"
    elif k <= 30:
        return "BUY", 70.0, f"Stochastic K={k:.1f} approaching oversold"
    elif k >= 80 and (d is None or d >= 75):
        return "SELL", 15.0, f"Stochastic K={k:.1f} overbought — sell signal"
    elif k >= 70:
        return "SELL", 30.0, f"Stochastic K={k:.1f} approaching overbought"
    else:
        return "WATCH", 50.0, f"Stochastic K={k:.1f} neutral"


def cci_signal_fn(cci: float) -> Tuple[str, float, str]:
    """CCI signal."""
    if cci is None or pd.isna(cci):
        return "WATCH", 50.0, "CCI not available"

    if cci <= -200:
        return "BUY", 92.0, f"CCI={cci:.0f} extremely oversold — strong reversal signal"
    elif cci <= -100:
        return "BUY", 78.0, f"CCI={cci:.0f} oversold — potential reversal"
    elif cci >= 200:
        return "SELL", 8.0, f"CCI={cci:.0f} extremely overbought — strong reversal signal"
    elif cci >= 100:
        return "SELL", 22.0, f"CCI={cci:.0f} overbought — consider taking profits"
    else:
        return "WATCH", 50.0, f"CCI={cci:.0f} neutral"


def obv_signal_fn(obv: float, obv_sma: float, price_trend: str) -> Tuple[str, float, str]:
    """OBV divergence signal."""
    if obv is None or pd.isna(obv) or obv_sma is None or pd.isna(obv_sma):
        return "WATCH", 50.0, "OBV not available"

    if obv > obv_sma:
        if price_trend == "DOWN":
            return "BUY", 75.0, "OBV divergence: volume rising while price falling — bullish reversal"
        return "BUY", 65.0, "OBV above its SMA — volume confirming uptrend"
    else:
        if price_trend == "UP":
            return "SELL", 25.0, "OBV divergence: volume falling while price rising — bearish warning"
        return "SELL", 35.0, "OBV below its SMA — weak volume in uptrend"


def volume_signal_fn(volume_ratio: float, volume_spike: bool, trend: str) -> Tuple[str, float, str]:
    """Volume analysis signal."""
    if volume_ratio is None or pd.isna(volume_ratio):
        return "WATCH", 50.0, "Volume data not available"

    if volume_spike and trend == "UP":
        return "BUY", 80.0, f"Volume spike ({volume_ratio:.1f}x avg) with uptrend — strong buying interest"
    elif volume_spike and trend == "DOWN":
        return "SELL", 20.0, f"Volume spike ({volume_ratio:.1f}x avg) with downtrend — strong selling pressure"
    elif volume_ratio > 1.5:
        return "WATCH", 60.0, f"Above-average volume ({volume_ratio:.1f}x) — increased activity"
    elif volume_ratio < 0.5:
        return "WATCH", 45.0, f"Below-average volume ({volume_ratio:.1f}x) — low conviction"
    else:
        return "WATCH", 50.0, f"Normal volume ({volume_ratio:.1f}x)"


# ─── Price Target Calculator ──────────────────────────────────────────────────
def calculate_targets(
    current_price: float,
    atr: float,
    signal: str,
    trend_strength: float = 50.0,
) -> Dict:
    """
    Calculate buy price, targets (T1/T2/T3), and stop-loss.
    Uses ATR-based dynamic levels.
    """
    if atr is None or pd.isna(atr) or atr <= 0:
        atr = current_price * 0.02  # Fallback: 2% of price

    multiplier = 1 + (trend_strength / 100) * 0.5  # 1.0–1.5 based on strength

    if signal == "BUY":
        buy_price = round(current_price * 0.995, 2)   # 0.5% below current
        target_1 = round(current_price + atr * 1.5 * multiplier, 2)   # Conservative
        target_2 = round(current_price + atr * 3.0 * multiplier, 2)   # Moderate
        target_3 = round(current_price + atr * 5.0 * multiplier, 2)   # Aggressive
        stop_loss = round(current_price - atr * STOPLOSS_ATR_MULTIPLIER, 2)

    elif signal == "SELL":
        buy_price = None
        target_1 = round(current_price - atr * 1.5 * multiplier, 2)   # Downside T1
        target_2 = round(current_price - atr * 3.0 * multiplier, 2)   # Downside T2
        target_3 = round(current_price - atr * 5.0 * multiplier, 2)   # Downside T3
        stop_loss = round(current_price + atr * STOPLOSS_ATR_MULTIPLIER, 2)

    else:  # WATCH
        buy_price = round(current_price - atr, 2)      # Watch entry if dips
        target_1 = round(current_price + atr * 2, 2)
        target_2 = round(current_price + atr * 3.5, 2)
        target_3 = round(current_price + atr * 5.5, 2)
        stop_loss = round(current_price - atr * 1.2, 2)

    # Upside/downside percentages
    def pct(target, base):
        return round((target - base) / base * 100, 2) if base else 0

    risk_reward = abs(pct(target_2, current_price)) / abs(pct(stop_loss, current_price)) if pct(stop_loss, current_price) != 0 else 0

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
        "risk_reward_ratio": round(risk_reward, 2),
    }


# ─── Risk Classifier ──────────────────────────────────────────────────────────
def classify_risk(beta: float, volatility: float, market_cap_tier: str, sector: str) -> str:
    """
    Classify investment as SAFE / MODERATE / RISKY.
    """
    safe_sectors = {"FMCG & Consumer Staples", "Pharmaceuticals & Healthcare", "IT & Technology"}
    risky_sectors = {"Metals & Mining", "Real Estate", "Textiles & Apparel"}

    # Market cap is a strong factor
    if market_cap_tier == "large":
        base_risk = 1
    elif market_cap_tier == "mid":
        base_risk = 2
    else:
        base_risk = 3

    # Sector adjustment
    if sector in safe_sectors:
        base_risk -= 1
    elif sector in risky_sectors:
        base_risk += 1

    # Volatility and beta adjustment
    if beta and not pd.isna(beta):
        if beta < SAFE_BETA_MAX:
            base_risk -= 0.5
        elif beta > RISKY_BETA_MIN:
            base_risk += 0.5

    if volatility and not pd.isna(volatility):
        if volatility < SAFE_VOLATILITY_MAX:
            base_risk -= 0.5
        elif volatility > RISKY_VOLATILITY_MIN:
            base_risk += 0.5

    if base_risk <= 1:
        return "SAFE"
    elif base_risk <= 2.5:
        return "MODERATE"
    else:
        return "RISKY"


def classify_investment_type(
    rsi: float, adx: float, beta: float, sector: str,
    trend_direction: str, composite_score: float
) -> str:
    """Classify investment style."""
    defensive_sectors = {"FMCG & Consumer Staples", "Pharmaceuticals & Healthcare"}

    if sector in defensive_sectors and (beta or 1) < 0.8:
        return "Defensive"
    elif adx and adx > 25 and trend_direction == "UP" and composite_score > 65:
        return "Momentum"
    elif rsi and rsi < 40 and composite_score < 50:
        return "Value"
    else:
        return "Growth"


# ─── Main Signal Generator ────────────────────────────────────────────────────
def generate_signal_for_stock(
    stock: Stock,
    ind: dict,
    composite_score: float,
    beta: float = None,
    volatility: float = None,
    ml_signal: str = "WATCH",
    ml_confidence: float = 0.5,
) -> Optional[Signal]:
    """
    Generate a complete signal record for a stock.
    """
    today = ind.get("date") if ind.get("date") else date.today()
    close = ind.get("close") or 0

    # Get current price from indicator context (stored externally)
    current_price = close

    if current_price is None or current_price == 0:
        return None

    atr = ind.get("atr_14")
    trend = ind.get("trend_direction", "SIDEWAYS")
    trend_strength = ind.get("trend_strength", 50.0) or 50.0

    # ── Individual signals ────────────────────────────────────────────────────
    rsi_sig, rsi_score, rsi_reason = rsi_signal(ind.get("rsi_14"))
    macd_sig, macd_score, macd_reason = macd_signal_fn(
        ind.get("macd"), ind.get("macd_signal"), ind.get("macd_hist")
    )
    bb_sig, bb_score, bb_reason = bollinger_signal(
        current_price, ind.get("bb_upper"), ind.get("bb_lower"), ind.get("bb_pct")
    )
    ema_sig, ema_score, ema_reason = ema_signal_fn(
        current_price, ind.get("ema_9"), ind.get("ema_21"),
        ind.get("ema_50"), ind.get("ema_200")
    )
    adx_sig, adx_score, adx_reason = adx_signal_fn(
        ind.get("adx"), ind.get("di_plus"), ind.get("di_minus")
    )
    stoch_sig, stoch_score, stoch_reason = stochastic_signal(
        ind.get("stoch_k"), ind.get("stoch_d")
    )
    cci_sig, cci_score, cci_reason = cci_signal_fn(ind.get("cci_20"))
    obv_sig, obv_score, obv_reason = obv_signal_fn(
        ind.get("obv"), ind.get("obv_sma"), trend
    )
    vol_sig, vol_score, vol_reason = volume_signal_fn(
        ind.get("volume_ratio"), ind.get("volume_spike"), trend
    )

    # ML signal conversion
    ml_score = {
        "BUY": 75.0 + ml_confidence * 20,
        "SELL": 25.0 - ml_confidence * 20,
        "WATCH": 50.0,
    }.get(ml_signal, 50.0)

    # ── Composite score override ───────────────────────────────────────────────
    final_score = composite_score

    # Multi-factor signal confirmation
    all_tech_sigs = [rsi_sig, macd_sig, bb_sig, ema_sig, adx_sig, stoch_sig, cci_sig, vol_sig, obv_sig]
    bullish_count = sum(1 for s in all_tech_sigs if s == "BUY")
    bearish_count = sum(1 for s in all_tech_sigs if s == "SELL")

    # ── Primary signal determination ──────────────────────────────────────────
    if final_score >= 55.0 or (final_score >= 51.5 and bullish_count >= 3) or bullish_count >= 5:
        primary_signal = "BUY"
    elif final_score <= 45.0 or (final_score <= 48.5 and bearish_count >= 3) or bearish_count >= 5:
        primary_signal = "SELL"
    else:
        primary_signal = "WATCH"

    # Signal strength
    if final_score >= 80 or final_score <= 20:
        strength = "STRONG"
    elif final_score >= 65 or final_score <= 35:
        strength = "MODERATE"
    else:
        strength = "WEAK"

    confidence = abs(final_score - 50) / 50.0  # 0.0–1.0

    # ── Price targets ─────────────────────────────────────────────────────────
    targets = calculate_targets(current_price, atr, primary_signal, trend_strength)

    # ── Build reasons ─────────────────────────────────────────────────────────
    all_reasons = []

    if rsi_sig == primary_signal:
        all_reasons.append(f"📊 RSI: {rsi_reason}")
    if macd_sig == primary_signal:
        all_reasons.append(f"📈 MACD: {macd_reason}")
    if bb_sig == primary_signal:
        all_reasons.append(f"📉 BB: {bb_reason}")
    if ema_sig == primary_signal:
        all_reasons.append(f"〰️ EMA: {ema_reason}")
    if adx_sig == primary_signal:
        all_reasons.append(f"💪 ADX: {adx_reason}")
    if stoch_sig == primary_signal:
        all_reasons.append(f"🔄 Stoch: {stoch_reason}")
    if cci_sig == primary_signal:
        all_reasons.append(f"📐 CCI: {cci_reason}")
    if vol_sig == primary_signal:
        all_reasons.append(f"📦 Volume: {vol_reason}")
    if ml_signal == primary_signal:
        all_reasons.append(f"🤖 ML Model: {ml_signal} with {ml_confidence:.0%} confidence")

    # Trend always included
    all_reasons.append(f"📊 Trend: {trend} (strength: {trend_strength:.0f}%)")

    if not all_reasons:
        all_reasons.append(f"Score={final_score:.1f} — mixed signals")

    key_reason = all_reasons[0] if all_reasons else f"Composite score: {final_score:.1f}"

    # ── Risk classification ───────────────────────────────────────────────────
    risk_level = classify_risk(beta, volatility, stock.market_cap_tier or "mid", stock.sector)
    inv_type = classify_investment_type(
        ind.get("rsi_14"), ind.get("adx"), beta, stock.sector, trend, final_score
    )

    # ── Build Signal record ───────────────────────────────────────────────────
    signal_obj = Signal(
        stock_id=stock.id,
        symbol=stock.symbol,
        date=today,
        signal=primary_signal,
        signal_strength=strength,
        confidence=round(confidence, 3),
        current_price=current_price,
        buy_price=targets.get("buy_price"),
        target_price_1=targets.get("target_1"),
        target_price_2=targets.get("target_2"),
        target_price_3=targets.get("target_3"),
        stop_loss=targets.get("stop_loss"),
        target_1_upside_pct=targets.get("t1_upside_pct"),
        target_2_upside_pct=targets.get("t2_upside_pct"),
        target_3_upside_pct=targets.get("t3_upside_pct"),
        stop_loss_downside_pct=targets.get("sl_downside_pct"),
        risk_reward_ratio=targets.get("risk_reward_ratio"),
        rsi_signal=rsi_sig,
        macd_signal=macd_sig,
        bb_signal=bb_sig,
        ema_signal=ema_sig,
        adx_signal=adx_sig,
        stoch_signal=stoch_sig,
        cci_signal=cci_sig,
        obv_signal=obv_sig,
        volume_signal=vol_sig,
        ml_signal=ml_signal,
        reasons=json.dumps(all_reasons),
        key_reason=key_reason[:255],
        risk_level=risk_level,
        investment_type=inv_type,
    )

    return signal_obj


def generate_all_signals(session: Session, progress_callback=None):
    """Generate signals for all stocks using latest indicators and composite scores."""
    from db.database import TechnicalIndicator, CompositeScore

    stocks = session.query(Stock).filter(Stock.is_active == True).all()
    total = len(stocks)
    logger.info(f"Generating signals for {total} stocks...")

    for i, stock in enumerate(stocks):
        try:
            # Get latest indicator
            ind_row = session.query(TechnicalIndicator).filter(
                TechnicalIndicator.symbol == stock.symbol
            ).order_by(TechnicalIndicator.date.desc()).first()

            if ind_row is None:
                continue

            ind = {c.name: getattr(ind_row, c.name) for c in TechnicalIndicator.__table__.columns}

            # Get latest score
            score_row = session.query(CompositeScore).filter(
                CompositeScore.symbol == stock.symbol
            ).order_by(CompositeScore.date.desc()).first()

            composite = score_row.composite_score if score_row else 50.0
            beta = score_row.beta if score_row else None
            volatility = score_row.volatility_annual if score_row else None

            # Get latest price to inject as "close"
            price_row = session.execute(
                text("SELECT close FROM daily_prices WHERE symbol=:s ORDER BY date DESC LIMIT 1"),
                {"s": stock.symbol}
            ).scalar()
            ind["close"] = price_row

            signal_obj = generate_signal_for_stock(
                stock=stock,
                ind=ind,
                composite_score=composite,
                beta=beta,
                volatility=volatility,
            )

            if signal_obj:
                sig_data = {c.name: getattr(signal_obj, c.name) for c in Signal.__table__.columns if c.name != "id"}
                sig_data["date"] = str(sig_data["date"])
                cols = ", ".join(sig_data.keys())
                placeholders = ", ".join(f":{k}" for k in sig_data.keys())
                session.execute(text(f"INSERT OR REPLACE INTO signals ({cols}) VALUES ({placeholders})"), sig_data)

        except Exception as e:
            session.rollback()
            logger.error(f"{stock.symbol}: Signal generation error: {e}")

        if i % 50 == 0:
            session.commit()

        if progress_callback:
            progress_callback(i + 1, total, stock.symbol)

    session.commit()
    logger.info("✅ Signal generation complete")
