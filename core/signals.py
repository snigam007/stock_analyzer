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


def calculate_targets(
    current_price: float,
    atr: float,
    signal: str,
    trend_strength: float = 50.0,
    adx: float = 20.0,
    market_cap_tier: str = "mid",
    vix: float = 15.0,
    swing_low: Optional[float] = None,
    swing_high: Optional[float] = None,
) -> dict:
    """
    Calculate price targets and context-aware stop loss.
    Stop loss sizing is adaptive to:
      - ADX (trend strength): strong trend = tighter SL, choppy = wider
      - Market cap tier: large cap noise is lower than small cap
      - VIX regime: high volatility = wider SL to avoid noise stops
      - Swing low/high anchor: structural support level as hard floor
    """
    if not atr or atr <= 0 or pd.isna(atr):
        atr = current_price * 0.022
    mult = 1.0 + (trend_strength / 100.0) * 0.35

    # ── Fix 5A: ADX-aware ATR multiplier for stop loss ──────────────────────
    adx_val = float(adx or 20.0)
    if adx_val >= 30:
        sl_atr_mult = 1.2   # Strong trend: tight SL, direction is clear
    elif adx_val >= 20:
        sl_atr_mult = 1.8   # Moderate trend: balanced cushion
    else:
        sl_atr_mult = 2.5   # Weak/choppy: wide SL to survive noise

    # ── Fix 5B: Market-cap tier floor (% of price) ───────────────────────────
    tier_floor = {"large": 0.018, "mid": 0.025, "small": 0.035}.get(
        (market_cap_tier or "mid").lower(), 0.025
    )

    # ── Fix 5C: VIX regime adjustment (widen in high-fear environments) ──────
    if vix and vix > 22:
        sl_atr_mult *= 1.25
        tier_floor *= 1.1
    elif vix and vix > 18:
        sl_atr_mult *= 1.1

    sl_distance = max(atr * sl_atr_mult, current_price * tier_floor)

    if signal == "BUY":
        buy_price = round(current_price * 0.998, 2)
        target_1 = round(current_price + max(current_price * 0.035, atr * 1.8 * mult), 2)
        target_2 = round(current_price + max(current_price * 0.075, atr * 3.5 * mult), 2)
        target_3 = round(current_price + max(current_price * 0.140, atr * 6.0 * mult), 2)
        raw_sl = current_price - sl_distance
        # ── Fix 5D: Anchor to swing low (structural support floor) ───────────
        if swing_low and swing_low > 0 and swing_low < current_price:
            # SL should not be above the nearest structural swing low minus 0.5%
            structural_sl = swing_low * 0.995
            stop_loss = round(min(raw_sl, structural_sl), 2)  # Pick lower (more room)
        else:
            stop_loss = round(raw_sl, 2)
    elif signal == "SELL":
        buy_price = None
        target_1 = round(current_price - max(current_price * 0.035, atr * 1.8 * mult), 2)
        target_2 = round(current_price - max(current_price * 0.075, atr * 3.5 * mult), 2)
        target_3 = round(current_price - max(current_price * 0.140, atr * 6.0 * mult), 2)
        raw_sl = current_price + sl_distance
        if swing_high and swing_high > current_price:
            structural_sl = swing_high * 1.005
            stop_loss = round(max(raw_sl, structural_sl), 2)
        else:
            stop_loss = round(raw_sl, 2)
    else:
        buy_price = round(current_price - atr, 2)
        target_1 = round(current_price + atr * 2.0, 2)
        target_2 = round(current_price + atr * 3.8, 2)
        target_3 = round(current_price + atr * 6.0, 2)
        stop_loss = round(current_price - atr * sl_atr_mult, 2)

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


def _derive_indicator_signals(ind: dict) -> dict:
    """Derive individual BUY/SELL/WATCH signals for all 9 indicators."""
    close     = float(ind.get("close") or 0)
    rsi       = float(ind.get("rsi_14") or 50)
    macd      = ind.get("macd")
    macd_sig  = ind.get("macd_signal")
    macd_hist = ind.get("macd_hist")
    bb_pct    = ind.get("bb_pct")         # 0 = at lower band, 1 = at upper band
    ema_50    = ind.get("ema_50")
    ema_200   = ind.get("ema_200")
    adx       = float(ind.get("adx") or 0)
    di_plus   = float(ind.get("di_plus") or 0)
    di_minus  = float(ind.get("di_minus") or 0)
    stoch_k   = float(ind.get("stoch_k") or 50)
    stoch_d   = float(ind.get("stoch_d") or 50)
    cci       = float(ind.get("cci_20") or 0)
    obv       = ind.get("obv")
    obv_sma   = ind.get("obv_sma")
    vol_ratio = float(ind.get("volume_ratio") or 1.0)
    vol_spike = bool(ind.get("volume_spike") or False)

    # RSI
    rsi_s, _, rsi_r = rsi_signal(rsi)
    # MACD
    macd_s, _, macd_r = macd_signal_fn(macd, macd_sig, macd_hist)
    # EMA trend
    ema_s, _, ema_r = ema_signal_fn(close, ind.get("ema_9"), ind.get("ema_21"), ema_50, ema_200)
    # Bollinger Band
    if bb_pct is not None and not pd.isna(bb_pct):
        bb_s = "BUY" if bb_pct <= 0.20 else ("SELL" if bb_pct >= 0.80 else "WATCH")
    else:
        bb_s = "WATCH"
    # ADX directional
    if adx >= 20:
        adx_s = "BUY" if di_plus > di_minus else "SELL"
    else:
        adx_s = "WATCH"  # No meaningful trend
    # Stochastic
    if stoch_k <= 25 and stoch_k < stoch_d:
        stoch_s = "BUY"
    elif stoch_k >= 75 and stoch_k > stoch_d:
        stoch_s = "SELL"
    else:
        stoch_s = "WATCH"
    # CCI
    if cci <= -100:
        cci_s = "BUY"
    elif cci >= 100:
        cci_s = "SELL"
    else:
        cci_s = "WATCH"
    # OBV
    if obv is not None and obv_sma is not None and not pd.isna(obv) and not pd.isna(obv_sma):
        obv_s = "BUY" if float(obv) > float(obv_sma) else "SELL"
    else:
        obv_s = "WATCH"
    # Volume
    if vol_spike or vol_ratio >= 2.0:
        vol_s = "BUY"   # High volume = buyer conviction (direction determined by price)
    elif vol_ratio <= 0.5:
        vol_s = "SELL"  # Dry volume = lack of conviction
    else:
        vol_s = "WATCH"

    return {
        "rsi_s": rsi_s, "rsi_r": rsi_r,
        "macd_s": macd_s, "macd_r": macd_r,
        "ema_s": ema_s, "ema_r": ema_r,
        "bb_s": bb_s, "adx_s": adx_s,
        "stoch_s": stoch_s, "cci_s": cci_s,
        "obv_s": obv_s, "vol_s": vol_s,
    }


def generate_signal_for_stock(
    stock: Stock,
    ind: dict,
    composite_score: float,
    beta: float = None,
    volatility: float = None,
    ml_signal: str = "WATCH",
    ml_confidence: float = 0.5,
    price_df: Optional[pd.DataFrame] = None,
    regime: Optional[dict] = None,
) -> Optional[Dict]:
    """Generates full 5-Pillar institutional signal dictionary with quantitative guardrails."""
    today = ind.get("date") if ind.get("date") else date.today()
    close = ind.get("close") or 0.0
    if close <= 0: return None

    atr = ind.get("atr_14")
    trend = ind.get("trend_direction", "SIDEWAYS")
    trend_strength = ind.get("trend_strength", 50.0) or 50.0
    adx_val = float(ind.get("adx") or 0.0)
    rsi_val = float(ind.get("rsi_14") or 50.0)
    ema_50 = ind.get("ema_50")
    ema_200 = ind.get("ema_200")

    # ── Fix 6: Market Regime Context ─────────────────────────────────────────
    regime = regime or {}
    nifty_bullish  = regime.get("nifty_above_50ema", True)   # Is Nifty in uptrend?
    vix_level      = float(regime.get("vix", 15.0) or 15.0)
    regime_buy_boost = 0.0
    regime_sl_mult   = 1.0
    if not nifty_bullish:
        # Bear regime: require higher conviction for BUYs (+1.0 point on calibrated 50-62 scale)
        regime_buy_boost = 1.0
        regime_sl_mult   = 1.2   # Wider stops in bear markets
    if vix_level > 22:
        regime_buy_boost += 0.8  # Extra caution in high-fear markets
        regime_sl_mult   *= 1.15

    # ── Fix 3: Derive all 9 indicator signals (not just RSI/MACD/EMA) ────────
    ind_sigs = _derive_indicator_signals(ind)
    rsi_s, rsi_r   = ind_sigs["rsi_s"], ind_sigs["rsi_r"]
    macd_s, macd_r = ind_sigs["macd_s"], ind_sigs["macd_r"]
    ema_s, ema_r   = ind_sigs["ema_s"], ind_sigs["ema_r"]
    bb_s    = ind_sigs["bb_s"]
    adx_s   = ind_sigs["adx_s"]
    stoch_s = ind_sigs["stoch_s"]
    cci_s   = ind_sigs["cci_s"]
    obv_s   = ind_sigs["obv_s"]
    vol_s   = ind_sigs["vol_s"]

    # Count across all 9 indicators
    all_signals = [rsi_s, macd_s, ema_s, bb_s, adx_s, stoch_s, cci_s, obv_s, vol_s]
    bullish_count = sum(1 for s in all_signals if s == "BUY")
    bearish_count = sum(1 for s in all_signals if s == "SELL")

    is_above_50_ema  = bool(ema_50 and close > ema_50)
    is_above_200_ema = bool(ema_200 and close > ema_200)

    # 1. Primary Signal Determination
    # Calibrated to 5-pillar composite distribution (mean ~55, top 10% is 59.5 - 62.4)
    final_score = composite_score
    effective_buy_threshold  = 59.5 + regime_buy_boost   # ~59.5 in Bull, ~60.5 in Bear
    effective_sell_threshold = 50.5 - regime_buy_boost   # ~50.5 in Bull, ~49.5 in Bear

    # BUY: need solid score in top ~8% OR (score >= threshold-1.5 with 5+ bullish indicators & above both 50 and 200 EMA)
    if (final_score >= effective_buy_threshold and (is_above_50_ema or bullish_count >= 4)) or \
       (final_score >= effective_buy_threshold - 1.5 and bullish_count >= 5 and is_above_50_ema and is_above_200_ema):
        candidate_signal = "BUY"
    elif (final_score <= effective_sell_threshold) or \
         (final_score <= effective_sell_threshold + 1.5 and bearish_count >= 5 and not is_above_50_ema):
        candidate_signal = "SELL"
    else:
        candidate_signal = "WATCH"

    # ── Quantitative Quality & Safety Guardrails ──────────────────────────────
    # Guardrail 1: ADX Chop Filter
    if adx_val < 18.0 and candidate_signal in ["BUY", "SELL"]:
        if final_score < 72.0 and final_score > 28.0:
            candidate_signal = "WATCH"

    # ── Fix 4 (RSI guardrail): Only block BUY if RSI overbought AND trend weak ──
    # Strong uptrends (ADX >= 25) can sustain RSI 68-80 — allow momentum trades
    if candidate_signal == "BUY" and rsi_val > 78.0:
        candidate_signal = "WATCH"   # True parabolic exhaustion cutoff
    elif candidate_signal == "BUY" and rsi_val > 68.0 and adx_val < 25.0:
        candidate_signal = "WATCH"   # Overbought in weak trend only

    # RSI oversold guard for SELL — only block if ADX confirms no downtrend
    if candidate_signal == "SELL" and rsi_val < 22.0:
        candidate_signal = "WATCH"   # True capitulation floor
    elif candidate_signal == "SELL" and rsi_val < 32.0 and adx_val < 25.0:
        candidate_signal = "WATCH"   # Oversold in weak trend

    primary_signal = candidate_signal
    strength = "STRONG" if (final_score >= 75 or final_score <= 25) else ("MODERATE" if (final_score >= 62 or final_score <= 38) else "WEAK")
    confidence = round(abs(final_score - 50) / 50.0, 2)

    # 2. Risk Classification incorporating Piotroski & Altman Z
    fh = compute_fundamental_health_scorecard(stock.symbol, stock.name, stock.sector, stock.market_cap_tier or "mid")
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
    if rsi_s == primary_signal:   all_reasons.append(f"📊 RSI: {rsi_r}")
    if macd_s == primary_signal:  all_reasons.append(f"📈 MACD: {macd_r}")
    if ema_s == primary_signal:   all_reasons.append(f"〰️ Trend: {ema_r}")
    if bb_s == primary_signal:    all_reasons.append(f"📉 Bollinger: {'Near lower band — oversold setup' if bb_s == 'BUY' else 'Near upper band — overbought'} ")
    if adx_s == primary_signal:   all_reasons.append(f"📡 ADX: Directional trend confirmed (ADX={adx_val:.1f}, +DI vs -DI)")
    if stoch_s == primary_signal: all_reasons.append(f"⚡ Stochastic: {'Oversold crossover (K < 25)' if stoch_s == 'BUY' else 'Overbought (K > 75)'}")
    if cci_s == primary_signal:   all_reasons.append(f"🔄 CCI: {'Extreme oversold (<-100)' if cci_s == 'BUY' else 'Extreme overbought (>+100)'}")
    if obv_s == primary_signal:   all_reasons.append(f"📊 OBV: {'Volume supporting price trend (OBV > OBV-SMA)' if obv_s == 'BUY' else 'Volume diverging (OBV < OBV-SMA)'}")

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
    # ── Swing low/high for structural SL anchor ───────────────────────────────
    swing_low = swing_high = None
    if price_df is not None and not price_df.empty and len(price_df) >= 10:
        try:
            lows  = price_df["low"].tail(20).dropna()
            highs = price_df["high"].tail(20).dropna()
            if len(lows) >= 5:
                swing_low  = float(lows.rolling(5).min().dropna().iloc[-1])
            if len(highs) >= 5:
                swing_high = float(highs.rolling(5).max().dropna().iloc[-1])
        except Exception:
            pass

    targets = calculate_targets(
        close, atr, primary_signal, trend_strength,
        adx=adx_val,
        market_cap_tier=stock.market_cap_tier or "mid",
        vix=vix_level,
        swing_low=swing_low,
        swing_high=swing_high,
    )

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
        "bb_signal": bb_s,        # Fix 3: now properly computed
        "ema_signal": ema_s,
        "adx_signal": adx_s,      # Fix 3: now properly computed
        "stoch_signal": stoch_s,  # Fix 3: now properly computed
        "cci_signal": cci_s,      # Fix 3: now properly computed
        "volume_signal": vol_s,   # Fix 3: now properly computed
        "obv_signal": obv_s,      # Fix 3: now properly computed
        "ml_signal": ml_signal,
    }


def _load_market_regime(session: Session) -> dict:
    """
    Fix 7: Load current market regime context once per batch.
    Returns dict with nifty_above_50ema and vix level.
    """
    regime = {"nifty_above_50ema": True, "vix": 15.0}
    try:
        # Nifty 50 price vs 50-day EMA
        nifty_prices = session.execute(text("""
            SELECT close FROM index_prices
            WHERE symbol = '^NSEI' ORDER BY date DESC LIMIT 55
        """)).fetchall()
        if len(nifty_prices) >= 50:
            prices = [float(r[0]) for r in nifty_prices if r[0]][::-1]  # oldest first
            ema50 = pd.Series(prices).ewm(span=50, adjust=False).mean().iloc[-1]
            latest_close = prices[-1]
            regime["nifty_above_50ema"] = latest_close > ema50
            logger.info(f"Regime: Nifty={latest_close:.0f} {'>' if regime['nifty_above_50ema'] else '<'} EMA50={ema50:.0f}")
    except Exception as e:
        logger.warning(f"Regime Nifty check failed: {e}")
    try:
        # India VIX level
        vix_row = session.execute(text("""
            SELECT close FROM index_prices
            WHERE symbol = '^INDIAVIX' OR symbol LIKE '%VIX%'
            ORDER BY date DESC LIMIT 1
        """)).scalar()
        if vix_row:
            regime["vix"] = float(vix_row)
            logger.info(f"Regime: VIX={regime['vix']:.1f}")
    except Exception as e:
        logger.warning(f"Regime VIX check failed: {e}")
    return regime


def compute_and_save_signals(session: Session, progress_callback=None):
    """Batch generates and saves 5-Pillar Apex Signals for all active stocks."""
    from db.database import Stock, TechnicalIndicator, CompositeScore, Signal, Forecast
    from core.data_fetcher import get_price_dataframe

    stocks = session.query(Stock).filter(Stock.is_active == True).all()
    total = len(stocks)
    as_of_date = session.execute(text("SELECT MAX(date) FROM daily_prices")).scalar()
    today = as_of_date if as_of_date else date.today()

    # Fix 7: Load regime context once (not per stock)
    regime = _load_market_regime(session)
    logger.info(f"Generating 5-Pillar Apex Signals for {total} stocks (regime: {'BULL' if regime['nifty_above_50ema'] else 'BEAR'}, VIX={regime['vix']:.1f})...")

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

            # Fix 4: Use actual ML forecast from Forecast table (not circular composite_score)
            ml_sig, ml_conf = "WATCH", 0.5
            try:
                fc_row = session.query(Forecast).filter(
                    Forecast.symbol == stock.symbol
                ).order_by(Forecast.generated_date.desc()).first()
                if fc_row and fc_row.forecast_7d_change_pct is not None:
                    chg = float(fc_row.forecast_7d_change_pct)
                    if chg > 1.5:
                        ml_sig  = "BUY"
                        ml_conf = min(0.95, 0.5 + chg / 20.0)
                    elif chg < -1.5:
                        ml_sig  = "SELL"
                        ml_conf = min(0.95, 0.5 + abs(chg) / 20.0)
                    else:
                        ml_sig, ml_conf = "WATCH", 0.5
            except Exception:
                # Fallback to score-based proxy if Forecast table missing
                ml_sig  = "BUY" if comp_score >= 65 else ("SELL" if comp_score <= 35 else "WATCH")
                ml_conf = round(abs(comp_score - 50) / 50.0, 2)

            sig_dict = generate_signal_for_stock(
                stock=stock,
                ind=ind,
                composite_score=comp_score,
                beta=beta,
                volatility=vol,
                ml_signal=ml_sig,
                ml_confidence=ml_conf,
                price_df=price_df,
                regime=regime,
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


# Alias for backwards compatibility with runner, initialization, and updater scripts
generate_all_signals = compute_and_save_signals