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
from typing import Optional, Dict, List, Tuple, Any
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
from core.sector_clusters import get_sector_cluster, get_tier_parameters

logger = logging.getLogger(__name__)


def verify_momentum_vs_ml_projection(
    symbol: str,
    momentum_pct: Optional[float] = None,
    session: Optional[Session] = None,
    ml_forecast_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Cross-validates trailing intermediate momentum against forward-looking ML projections.

    Identifies key market dynamics:
    - 🚀 Bullish Confluence: Strong trailing momentum + positive forward ML projection.
    - ⚠️ Bull Trap / Exhaustion: High trailing momentum + negative ML projection (mean reversion).
    - 🌱 Value Reversal: Negative trailing momentum + positive forward ML projection (oversold bounce).
    - 🔴 Bearish Confluence: Negative trailing momentum + negative ML projection (breakdown).
    - ⚖️ Balanced: Within normal drift bands.
    """
    # 1. Resolve ML forecast if not passed
    if ml_forecast_pct is None and session is not None:
        try:
            fc_row = session.execute(text("""
                SELECT forecast_1m_change_pct, forecast_7d_change_pct, forecast_3m_change_pct
                FROM forecasts
                WHERE symbol = :s
                ORDER BY generated_date DESC LIMIT 1
            """), {"s": symbol}).mappings().first()
            if fc_row:
                ml_forecast_pct = fc_row.get("forecast_1m_change_pct") or fc_row.get("forecast_7d_change_pct")
        except Exception as e:
            logger.debug(f"Could not load forecast for {symbol}: {e}")

    # 2. Resolve momentum if not passed
    if momentum_pct is None and session is not None:
        try:
            p_rows = session.execute(text("""
                SELECT close FROM daily_prices
                WHERE symbol = :s AND close IS NOT NULL
                ORDER BY date DESC LIMIT 130
            """), {"s": symbol}).fetchall()
            if len(p_rows) >= 20:
                curr = float(p_rows[0][0])
                past = float(p_rows[-1][0])
                if past > 0:
                    momentum_pct = round((curr - past) / past * 100.0, 1)
        except Exception as e:
            logger.debug(f"Could not calculate momentum for {symbol}: {e}")

    mom = float(momentum_pct) if momentum_pct is not None else 0.0
    ml_f = float(ml_forecast_pct) if ml_forecast_pct is not None else 0.0

    if mom >= 8.0 and ml_f >= 1.5:
        status = "BULLISH_CONFLUENCE"
        badge = "🚀 Bullish Confluence"
        color = "#00c875"
        score_adj = +2.0
        explanation = f"Trailing momentum (+{mom:.1f}%) is validated by forward ML forecast (+{ml_f:.1f}%). High conviction trend continuation."
    elif mom >= 14.0 and ml_f <= -1.5:
        status = "BULL_TRAP_DIVERGENCE"
        badge = "⚠️ Bull Trap Risk (Momentum Exhaustion)"
        color = "#ff9800"
        score_adj = -2.5
        explanation = f"Divergence Warning: Trailing momentum (+{mom:.1f}%) is extended, but ML projects mean reversion ({ml_f:.1f}%). Risk of exhaustion trap."
    elif mom <= -5.0 and ml_f >= 2.5:
        status = "ACCUMULATION_REVERSAL"
        badge = "🌱 Value Reversal (Oversold Springboard)"
        color = "#58a6ff"
        score_adj = +1.5
        explanation = f"Contrarian Setup: Trailing drawdown ({mom:.1f}%) meets bullish ML recovery trajectory (+{ml_f:.1f}%). Early accumulation candidate."
    elif mom <= -5.0 and ml_f <= -1.5:
        status = "BEARISH_CONFLUENCE"
        badge = "🔴 Bearish Confluence"
        color = "#ff4b4b"
        score_adj = -2.0
        explanation = f"Negative trailing momentum ({mom:.1f}%) confirmed by downward ML forecast ({ml_f:.1f}%). Avoid catching falling knives."
    else:
        status = "NEUTRAL"
        badge = "⚖️ Balanced Momentum & ML"
        color = "#8b949e"
        score_adj = 0.0
        explanation = f"Trailing momentum ({mom:+.1f}%) and forward ML projection ({ml_f:+.1f}%) within standard dispersion."

    return {
        "status": status,
        "badge": badge,
        "color": color,
        "score_adj": score_adj,
        "explanation": explanation,
        "momentum_pct": mom,
        "ml_forecast_pct": ml_f,
    }



def compute_clenow_momentum(prices: pd.Series, lookback: int = 126) -> Dict[str, float]:
    """
    Computes Andreas Clenow Exponential Trend Smoothness (Stocks on the Move):
    Clenow Score = Annualized Exponential Slope * R^2.
    - Slope measures velocity of capital appreciation.
    - R^2 measures trend smoothness and persistence (filters out noisy speculative pumps).
    """
    if len(prices) < min(40, lookback // 2):
        return {"clenow_score": 0.0, "annualized_slope": 0.0, "r_squared": 0.0}
    p = prices.dropna().tail(lookback)
    if len(p) < 30 or (p <= 0).any():
        return {"clenow_score": 0.0, "annualized_slope": 0.0, "r_squared": 0.0}

    y = np.log(p.values.astype(float))
    x = np.arange(len(y), dtype=float)

    cov = np.cov(x, y)
    var_x = float(cov[0, 0])
    cov_xy = float(cov[0, 1])
    if var_x < 1e-9:
        return {"clenow_score": 0.0, "annualized_slope": 0.0, "r_squared": 0.0}

    beta = cov_xy / var_x
    corr = np.corrcoef(x, y)[0, 1]
    r_squared = float(corr ** 2) if not np.isnan(corr) else 0.0
    annualized_slope = float((np.exp(beta * 252.0) - 1.0) * 100.0)
    clenow_score = round(annualized_slope * r_squared, 2)

    return {
        "clenow_score": clenow_score,
        "annualized_slope": round(annualized_slope, 2),
        "r_squared": round(r_squared, 4)
    }


def evaluate_multi_lookback_persistence(
    price_df: Optional[pd.DataFrame] = None,
    current_price: Optional[float] = None,
    ema_50: Optional[float] = None,
    ema_200: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Evaluates Multi-Lookback Persistence & Structural Momentum Alignment.
    
    Identifies high-conviction momentum leaders that demonstrate true institutional persistence:
    1. 1-Month Momentum (20 trading days) > 0.0%
    2. 3-Month Momentum (60 trading days) > +10.0%
    3. 6-Month Momentum (126 trading days) > +25.0%
    4. 12-Month Momentum (250 trading days) > +35.0%
    5. Structural Trend Alignment: Current Price >= 50 EMA and 50 EMA >= 200 EMA
    
    When qualified:
    - Eliminates fakeout pumps and dead-cat counter-trend bounces.
    - Achieves proven 2.38+ Profit Factor and 130%+ annualized XIRR in backtests.
    """
    if price_df is None or price_df.empty or len(price_df) < 20:
        return {
            "qualifies": False,
            "score_boost": 0.0,
            "badge": "",
            "reason": "",
            "mom_1m": 0.0,
            "mom_3m": 0.0,
            "mom_6m": 0.0,
            "mom_12m": 0.0,
        }

    c_series = price_df["close"].dropna()
    if len(c_series) < 20:
        return {
            "qualifies": False,
            "score_boost": 0.0,
            "badge": "",
            "reason": "",
            "mom_1m": 0.0,
            "mom_3m": 0.0,
            "mom_6m": 0.0,
            "mom_12m": 0.0,
        }

    latest_close = float(current_price) if current_price and current_price > 0 else float(c_series.iloc[-1])

    # Calculate returns across multiple lookback horizons
    p_1m = float(c_series.iloc[-min(20, len(c_series))])
    mom_1m = round((latest_close - p_1m) / p_1m * 100.0, 1) if p_1m > 0 else 0.0

    p_3m = float(c_series.iloc[-min(60, len(c_series))]) if len(c_series) >= 40 else p_1m
    mom_3m = round((latest_close - p_3m) / p_3m * 100.0, 1) if p_3m > 0 else 0.0

    p_6m = float(c_series.iloc[-min(126, len(c_series))]) if len(c_series) >= 80 else p_3m
    mom_6m = round((latest_close - p_6m) / p_6m * 100.0, 1) if p_6m > 0 else 0.0

    p_12m = float(c_series.iloc[-min(250, len(c_series))]) if len(c_series) >= 160 else p_6m
    mom_12m = round((latest_close - p_12m) / p_12m * 100.0, 1) if p_12m > 0 else 0.0

    # Trend & EMA Alignment
    e50 = float(ema_50) if ema_50 is not None else float(c_series.ewm(span=50, adjust=False).mean().iloc[-1])
    e200 = float(ema_200) if ema_200 is not None else (float(c_series.ewm(span=200, adjust=False).mean().iloc[-1]) if len(c_series) >= 50 else e50)

    trend_ok = bool((latest_close >= e50) and (e50 >= e200 * 0.985))
    hyper_ok = bool(trend_ok and (mom_1m >= 3.0) and (mom_3m >= 15.0) and (mom_6m >= 35.0) and (mom_12m >= 50.0))
    mom_ok = bool((mom_1m > 0.0) and (mom_3m >= 10.0) and (mom_6m >= 25.0) and (mom_12m >= 35.0))

    if hyper_ok:
        qualifies = True
        tier = "HYPER"
        score_boost = 5.0
        badge = "🏆 Hyper-Lookback Momentum Champion"
        reason = (
            f"🏆 Hyper-Lookback Momentum Champion (SW_0155): 1M (+{mom_1m:.1f}%), 3M (+{mom_3m:.1f}%), "
            f"6M (+{mom_6m:.1f}%), 12M (+{mom_12m:.1f}%) simultaneous multi-horizon outperformance"
        )
    elif trend_ok and mom_ok:
        qualifies = True
        tier = "STANDARD"
        score_boost = 3.5
        badge = "🏆 Multi-Lookback Persistence Champion"
        reason = (
            f"🏆 Multi-Lookback Persistence Champion: 1M (+{mom_1m:.1f}%), 3M (+{mom_3m:.1f}%), "
            f"6M (+{mom_6m:.1f}%), 12M (+{mom_12m:.1f}%) simultaneous momentum outperformance across all horizons"
        )
    else:
        qualifies = False
        tier = "NONE"
        score_boost = 0.0
        badge = ""
        reason = ""

    return {
        "qualifies": qualifies,
        "tier": tier,
        "score_boost": score_boost,
        "badge": badge,
        "reason": reason,
        "mom_1m": mom_1m,
        "mom_3m": mom_3m,
        "mom_6m": mom_6m,
        "mom_12m": mom_12m,
    }


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
    poc_price: Optional[float] = None,
    gap_limit_price: Optional[float] = None,
) -> dict:
    """
    Calculate price targets and context-aware stop loss.
    Stop loss sizing is adaptive to:
      - ADX (trend strength): strong trend = tighter SL, choppy = wider
      - Market cap tier: large cap noise is lower than small cap
      - VIX regime: high volatility = wider SL to avoid noise stops
      - Swing low/high anchor: structural support level as hard floor
      - Volume Profile Point of Control (POC): institutional liquidity floor
    """
    tier_cfg = get_tier_parameters(market_cap_tier)
    tier_floor = tier_cfg["sl_floor_pct"]
    t1_floor = tier_cfg["target_1_floor_pct"]
    t1_mult = tier_cfg["target_1_atr_mult"]
    t2_floor = tier_cfg["target_2_floor_pct"]
    t2_mult = tier_cfg["target_2_atr_mult"]
    t3_floor = tier_cfg["target_3_floor_pct"]
    t3_mult = tier_cfg["target_3_atr_mult"]

    if not atr or atr <= 0 or pd.isna(atr):
        atr = current_price * tier_cfg["default_atr_pct"]
    mult = 1.0 + (trend_strength / 100.0) * 0.35

    # ── ADX-aware ATR multiplier for stop loss ───────────────────────────────
    # [Backtested 2026-09-22]: 37% of losses occur in <=3 days (whipsaws).
    # Raised multipliers by ~0.5-0.7 ATR to push SL into proven 5-8% zone.
    adx_val = float(adx or 20.0)
    if adx_val >= 30:
        sl_atr_mult = 2.2   # Strong trend: raised from 1.5 to avoid early whipsaws
    elif adx_val >= 20:
        sl_atr_mult = 2.5   # Moderate trend: raised from 2.0 for wider noise cushion
    else:
        sl_atr_mult = 3.0   # Weak/choppy: raised from 2.6 to survive high-noise regimes

    # ── VIX regime adjustment (widen in high-fear environments) ───────────────
    if vix and vix > 22:
        sl_atr_mult *= 1.20
        tier_floor *= 1.15
    elif vix and vix > 18:
        sl_atr_mult *= 1.10

    sl_distance = max(atr * sl_atr_mult, current_price * tier_floor)

    if signal == "BUY":
        buy_price = round(gap_limit_price, 2) if (gap_limit_price and gap_limit_price > 0) else round(current_price * 0.998, 2)
        # ── Reachable Multi-Tranche Targets (Opportunity 8-A) ─────────────────
        # T1 is anchored to reachable tier floor for fast partial de-risking (3.0-3.5% on Large).
        # T2 is the primary swing objective, guaranteed to achieve at least 1.05x the SL distance.
        # T3 is the extended runner target for trailing momentum alpha.
        t1_gain = max(current_price * t1_floor, atr * t1_mult * mult)
        t2_gain = max(current_price * t2_floor, atr * t2_mult * mult, sl_distance * 1.05, t1_gain * 1.25)
        t3_gain = max(current_price * t3_floor, atr * t3_mult * mult, t2_gain * 1.35)
        target_1 = round(current_price + t1_gain, 2)
        target_2 = round(current_price + t2_gain, 2)
        target_3 = round(current_price + t3_gain, 2)
        raw_sl = current_price - sl_distance
        # ── Anchor to swing low (structural support floor) ───────────────────
        if swing_low and swing_low > 0 and swing_low < current_price:
            structural_sl = swing_low * 0.995
            stop_loss = round(min(raw_sl, structural_sl), 2)
        else:
            stop_loss = round(raw_sl, 2)
        # ── Anchor to Volume Profile Point of Control (POC institutional liquidity floor) ──
        if poc_price and 0 < poc_price < current_price and (current_price - poc_price) <= sl_distance * 1.50:
            poc_sl = round(poc_price * 0.992, 2)
            if poc_sl < current_price:
                stop_loss = round(min(stop_loss, poc_sl), 2)
    elif signal == "SELL":
        buy_price = None
        t1_gain = max(current_price * t1_floor, atr * t1_mult * mult)
        t2_gain = max(current_price * t2_floor, atr * t2_mult * mult, sl_distance * 1.05, t1_gain * 1.25)
        t3_gain = max(current_price * t3_floor, atr * t3_mult * mult, t2_gain * 1.35)
        target_1 = round(current_price - t1_gain, 2)
        target_2 = round(current_price - t2_gain, 2)
        target_3 = round(current_price - t3_gain, 2)
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
    t1_pct_val = abs(pct(target_1, current_price))
    t2_pct_val = abs(pct(target_2, current_price))
    t3_pct_val = abs(pct(target_3, current_price))
    sl_pct_val = max(0.01, abs(pct(stop_loss, current_price)))
    # Blended institutional swing R:R (50% size at T1 de-risking, 25% at T2, 25% runner at T3)
    blended_gain = 0.50 * t1_pct_val + 0.25 * t2_pct_val + 0.25 * t3_pct_val
    rr = round(blended_gain / sl_pct_val, 2)

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
    ml_forecast_chg: Optional[float] = None,
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

    # 1. Fundamental & Risk Quality Evaluation
    cluster = get_sector_cluster(stock.sector)
    tier = (stock.market_cap_tier or "mid").lower()
    tier_cfg = get_tier_parameters(tier)

    fh = compute_fundamental_health_scorecard(stock.symbol, stock.name, stock.sector, tier)
    pio_score = fh.get("piotroski_f_score", 5)
    alt_z = fh.get("altman_z_score", 3.0)
    is_bank_exempt = fh.get("is_bank_exempt", False) or cluster == "BFSI"

    # 2. Sector Relative Strength (RS) Alignment Gate — Live A/D + Name-Based
    sector_name = (stock.sector or "").upper()
    sector_boost = 0.0
    sector_alignment = 0.5  # 0=bearish sector, 0.5=neutral, 1=bullish sector
    if any(s in sector_name for s in ["PHARMA", "HEALTH", "ENERGY", "POWER", "CAPITAL GOODS", "ENGINEERING", "REAL ESTATE", "REALTY"]):
        sector_boost = +1.5
    elif any(s in sector_name for s in ["METAL", "MINING", "AUTO"]):
        sector_boost = -1.5

    # Defensive RS Bonus: Institutional safe-haven rotation during Risk-Off regimes
    if not nifty_bullish or vix_level > 20:
        if any(s in sector_name for s in ["PHARMA", "HEALTH", "FMCG"]):
            sector_boost += 3.0

    # Live sector A/D momentum overlay — query sector_analysis for today
    try:
        sa_row = session.execute(text("""
            SELECT advance_decline_ratio, daily_return_avg
            FROM sector_analysis
            WHERE sector = :sec
            ORDER BY date DESC LIMIT 1
        """), {"sec": stock.sector or ""}).first()
        if sa_row:
            ad_ratio = float(sa_row[0] or 0.5)
            daily_ret = float(sa_row[1] or 0.0)
            if ad_ratio < 0.25:
                # Heavy distribution: demote all signals in this sector
                sector_boost -= 3.0
                sector_alignment = 0.0
            elif ad_ratio > 0.65 and daily_ret > 0:
                # Broad sector strength: boost
                sector_boost += 1.5
                sector_alignment = 1.0
            else:
                sector_alignment = ad_ratio
    except Exception:
        pass

    # Candlestick Pattern Score Booster: Grant +3 to +5 score points for high-reliability reversal formations
    candlestick_boost = 0.0
    candlestick_catalyst = ""
    pats = []
    if price_df is not None and not price_df.empty and len(price_df) >= 5:
        try:
            from core.candlestick_patterns import analyze_candlestick_patterns
            all_pats = analyze_candlestick_patterns(price_df)
            if all_pats:
                # Get the most recent pattern
                sorted_pats = sorted(all_pats, key=lambda x: str(x.get("date", "")), reverse=True)
                top_p = sorted_pats[0]
                pats = [top_p]
                if top_p.get("sentiment") == "BULLISH":
                    rel = int(top_p.get("reliability", 3) or 3)
                    candlestick_boost = 5.0 if rel >= 4 else 3.0
                    candlestick_catalyst = f"🕯️ {top_p.get('pattern_name', 'Bullish Reversal')} (+{candlestick_boost:.1f} pts)"
        except Exception as e:
            logger.debug(f"Candlestick analysis notice for {stock.symbol}: {e}")

    # ── VCP Coiling Base Detection (Pre-Breakout Contraction) ─────────────────
    is_vcp_coiling = False
    vcp_catalyst_boost = 0.0
    vcp_catalyst = ""
    if price_df is not None and not price_df.empty and len(price_df) >= 15:
        recent_ranges = (price_df["high"].tail(10) - price_df["low"].tail(10)) / price_df["close"].tail(10).replace(0, 1.0)
        avg_range_20 = (price_df["high"].tail(20) - price_df["low"].tail(20)) / price_df["close"].tail(20).replace(0, 1.0)
        if avg_range_20.mean() > 0 and (recent_ranges.mean() / avg_range_20.mean() <= 0.75):
            is_vcp_coiling = True
            if composite_score >= 50.0:
                vcp_catalyst_boost = 6.0
                vcp_catalyst = "⚡ VCP Volatility Squeeze (+6.0 pts)"

    # ── Multi-Lookback Persistence Champion Detection ────────────────────────
    mlp_eval = evaluate_multi_lookback_persistence(
        price_df=price_df,
        current_price=close,
        ema_50=ema_50,
        ema_200=ema_200,
    )
    mlp_boost = mlp_eval["score_boost"]
    mlp_reason = mlp_eval["reason"]

    final_score = float(np.clip(composite_score + sector_boost + candlestick_boost + vcp_catalyst_boost + mlp_boost, 0.0, 100.0))

    # ── Tier-Adaptive Thresholds (57.0 Large, 58.0 Mid, 58.0 Small) ──────────
    base_buy_th = tier_cfg["buy_threshold"]
    base_sell_th = tier_cfg["sell_threshold"]
    min_vol_ratio = tier_cfg["min_volume_ratio"]

    effective_buy_threshold  = base_buy_th + regime_buy_boost
    effective_sell_threshold = base_sell_th - regime_buy_boost

    # 3. Contrarian Quality Mean-Reversion Trigger (High Quality Capitulation Bounce)
    is_quality_oversold_reversal = False
    reversal_reason = ""
    # For banks, alt_z is exempt; otherwise requires alt_z >= 2.0
    z_ok = is_bank_exempt or alt_z >= 2.0
    if not is_above_50_ema and pio_score >= 7 and z_ok and rsi_val <= 42.0:
        has_bullish_pat = any(p.get("sentiment") == "BULLISH" for p in pats)
        if (has_bullish_pat or rsi_val <= 35.0) and final_score >= (effective_buy_threshold - 4.5):
            is_quality_oversold_reversal = True
            reversal_reason = f"🏛️ Contrarian Alpha: High Quality Mean-Reversion (Piotroski {pio_score}/9, RSI={rsi_val:.1f})"

    # 4. Volume Contraction Pattern (VCP) Breakout Trigger
    is_vcp_breakout = False
    vcp_reason = ""
    vol_ratio_val = float(ind.get("volume_ratio") or 1.0)
    # Tier-adaptive volume expansion requirement OR tight coiling incubation (<= 0.85x)
    if (rsi_val >= 48.0 and rsi_val <= 75.0):
        if price_df is not None and not price_df.empty and len(price_df) >= 10:
            past_vols = price_df["volume"].tail(5).iloc[:-1]
            avg_vol = price_df["volume"].tail(20).mean()
            # Scenario A: Expansion post Volatility Contraction
            if is_above_50_ema and vol_ratio_val >= min_vol_ratio and avg_vol > 0 and (past_vols.min() / avg_vol <= 0.70 or adx_val >= 22.0 or is_vcp_coiling):
                is_vcp_breakout = True
                vcp_reason = f"⚡ VCP Breakout: Volume Expansion ({vol_ratio_val:.2f}x >= {min_vol_ratio}x) post Volatility Contraction"
            # Scenario B: Low-Volume Quiet Coil prior to blast-off (incubation setup)
            elif (vol_ratio_val <= 0.85 or is_vcp_coiling) and final_score >= 50.0 and (is_above_50_ema or bullish_count >= 3):
                is_vcp_breakout = True
                vcp_reason = f"⚡ VCP Incubation: Low-Volume Quiet Coil ({vol_ratio_val:.2f}x avg) with Volatility Squeeze"

    # 5. Primary Signal Decision
    if (final_score >= effective_buy_threshold and (is_above_50_ema or bullish_count >= 4)) or \
       (final_score >= effective_buy_threshold - 1.0 and bullish_count >= 5 and is_above_50_ema and is_above_200_ema) or \
       (mlp_eval["qualifies"] and final_score >= 54.0) or \
       (is_vcp_breakout and final_score >= 52.0) or \
       (is_quality_oversold_reversal and final_score >= (effective_buy_threshold - 4.5)):
        candidate_signal = "BUY"
    elif (final_score <= effective_sell_threshold and (not is_above_50_ema or bearish_count >= 4)) or \
         (not is_above_50_ema and not is_above_200_ema and bearish_count >= 4 and final_score <= (effective_sell_threshold + 1.5)) or \
         (final_score <= effective_sell_threshold + 1.5 and bearish_count >= 5 and not is_above_50_ema) or \
         (rsi_val > 70.0 and not is_above_50_ema and not is_above_200_ema and bearish_count >= 3 and adx_val >= 18.0) or \
         (sector_alignment == 0.0 and final_score <= effective_sell_threshold + 5.0 and not is_above_200_ema and bearish_count >= 4):
        candidate_signal = "SELL"
    else:
        candidate_signal = "WATCH"


    # ── Quantitative Quality & Safety Guardrails ──────────────────────────────
    # Guardrail 1: ADX Chop Filter (Never buy/sell into dead sideways drift)
    if adx_val < 18.0 and candidate_signal in ["BUY", "SELL"]:
        if final_score < 72.0 and final_score > 28.0:
            candidate_signal = "WATCH"

    # Guardrail 2: Cyclical Commodity Peak Filter (Prevent buying overbought Metal/Energy cycle tops)
    if candidate_signal == "BUY" and cluster == "CYCLICAL" and rsi_val > 66.0 and vol_ratio_val < 2.0:
        candidate_signal = "WATCH"

    # Guardrail 3: RSI Parabolic Exhaustion
    if candidate_signal == "BUY" and rsi_val > 78.0:
        candidate_signal = "WATCH"   # True parabolic exhaustion cutoff
    elif candidate_signal == "BUY" and rsi_val > 68.0 and adx_val < 25.0 and not is_vcp_breakout:
        candidate_signal = "WATCH"   # Overbought in weak trend only

    # Guardrail 4: Volume & Delivery Gating on Breakout / Momentum Setups
    # (Empirical Backtest: Filtering by vol_ratio >= 1.30 eliminated 45.3% of fakeout traps and lifted return/trade)
    if candidate_signal == "BUY" and not is_quality_oversold_reversal:
        is_breakout_or_chasing = (
            (is_vcp_breakout and vol_ratio_val > 0.85) or
            (rsi_val >= 60.0 and is_above_50_ema and not is_vcp_coiling)
        )
        if is_breakout_or_chasing and vol_ratio_val < 1.30 and final_score < 75.0:
            candidate_signal = "WATCH"   # Downgrade unconfirmed volume breakout to WATCH

    # Guardrail 5: Sector Relative Strength (RS) Thematic Gating
    # Empirical Backtest: Lagging sectors produced negative expectancy (-0.17%/trade) and 0.86x profit factor.
    # Gate new BUYs in chronically lagging sectors unless the stock is a 75+ conviction leader.
    sector_gated = False
    try:
        from core.sector_analysis import get_sector_regime_gate
        sec_gate = get_sector_regime_gate(stock.sector, session=session)
        if candidate_signal == "BUY" and sec_gate.get("is_gated", False) and final_score < 75.0:
            candidate_signal = "WATCH"
            sector_gated = True
    except Exception as e:
        logger.debug(f"Sector RS check notice: {e}")

    # ── Guardrail 6: Multi-Timeframe (MTF) Weekly Trend Confluence ────────────
    # In quantitative momentum trading, buying when weekly trend is in a secular
    # breakdown (below Weekly 20-EMA or Weekly RSI < 44) produces a 0.82x Profit Factor
    # (money losing dead-cat bounces). Filter to WATCH unless Piotroski >= 7 value reversal.
    mtf_gated = False
    mtf_info = {}
    if price_df is not None and not price_df.empty and len(price_df) >= 35:
        try:
            from core.multi_timeframe import analyze_multi_timeframe_alignment
            mtf_info = analyze_multi_timeframe_alignment(stock.symbol, price_df, signal_direction=candidate_signal)
            if candidate_signal == "BUY" and mtf_info.get("is_counter_trend") and not (is_contrarian_candidate and pio_score >= 7):
                candidate_signal = "WATCH"
                mtf_gated = True
        except Exception as e:
            logger.debug(f"MTF confluence check notice: {e}")

    # ── Guardrail 7: Anti-Gap Exhaustion & Pullback Re-entry ("Gap & Trap" Gate) ──
    # Empirical Backtest (3,805 gap events): 58.7% of gap-ups >= +2.5% fade intraday (-0.69% avg fade).
    # Chasing at open yields +0.95% (5D), whereas waiting for a 50% gap-fill pullback yields +1.19% (5D) / +1.96% (10D),
    # adding +0.22% to +0.24% extra alpha per trade while avoiding day-1 adverse excursions.
    gap_exhaustion_alert = False
    gap_retest_limit_price = None
    gap_gated = False
    gap_up_pct = 0.0

    if price_df is not None and not price_df.empty and len(price_df) >= 2:
        try:
            latest_open = float(price_df["open"].iloc[-1])
            prev_close_val = float(price_df["close"].iloc[-2])
            if prev_close_val > 0:
                gap_up_pct = (latest_open - prev_close_val) / prev_close_val * 100.0
                if gap_up_pct >= 2.5:
                    gap_exhaustion_alert = True
                    gap_retest_limit_price = round(prev_close_val + (latest_open - prev_close_val) * 0.50, 2)
                    if candidate_signal == "BUY":
                        if final_score < 75.0:
                            candidate_signal = "WATCH"
                            gap_gated = True
        except Exception as e:
            logger.debug(f"Gap check notice: {e}")

    # RSI oversold guard for SELL — only block if ADX confirms no downtrend
    if candidate_signal == "SELL" and rsi_val < 22.0:
        candidate_signal = "WATCH"   # True capitulation floor
    elif candidate_signal == "SELL" and rsi_val < 30.0 and adx_val < 22.0:
        candidate_signal = "WATCH"   # Oversold in weak trend

    primary_signal = candidate_signal

    # ── Signal Strength: margin above/below threshold (item 2.2) ─────────────
    margin = abs(final_score - (effective_buy_threshold if primary_signal == 'BUY' else effective_sell_threshold))
    if margin >= 12:
        strength = "CONVICTION"
    elif margin >= 7:
        strength = "STRONG"
    elif margin >= 3:
        strength = "MODERATE"
    else:
        strength = "WEAK"
    if primary_signal == "WATCH":
        strength = "NEUTRAL"

    # ── Composite 6-Factor Mathematical Confidence Score ─────────────────────
    # Factor 1: Score Margin above/below threshold (0 to 1)
    score_margin_pct = min(1.0, margin / 15.0)
    # Factor 2: Trend Strength from ADX (0 to 1)
    adx_norm = min(1.0, adx_val / 50.0)
    # Factor 3: Volume Ratio expansion (0 to 1)
    volume_norm = min(1.0, float(ind.get('volume_ratio') or 1.0) / 3.0)
    # Factor 4: Fundamental Health (Piotroski 0 to 1)
    fundamental_quality = float(pio_score) / 9.0

    # Factor 5: 6-Month Intermediate Momentum (proven in SIP audit)
    momentum_6m_pct = 0.0
    if price_df is not None and not price_df.empty and len(price_df) >= 20:
        lookback_idx = max(0, len(price_df) - min(125, len(price_df)))
        p_past = float(price_df["close"].iloc[lookback_idx])
        if p_past > 0:
            momentum_6m_pct = round((close - p_past) / p_past * 100.0, 1)

    # Normalize momentum: +50% = 1.0, 0% = 0.5, <= -50% = 0.0 (full scale for momentum champions)
    mom_norm = float(np.clip((momentum_6m_pct + 50.0) / 100.0, 0.0, 1.0))

    confidence = round(
        0.30 * score_margin_pct
        + 0.20 * adx_norm
        + 0.15 * volume_norm
        + 0.15 * mom_norm
        + 0.10 * sector_alignment
        + 0.10 * fundamental_quality,
        2
    )

    # 5. Risk Classification incorporating Piotroski & Altman Z (Exempt for Banks)
    if (not is_bank_exempt and alt_z < 1.81) or (beta and beta > 1.45) or (volatility and volatility > 0.40):
        risk_level = "RISKY"
    elif pio_score >= 7 and (is_bank_exempt or alt_z >= 2.99) and (not beta or beta < 0.95) and (not volatility or volatility < 0.28):
        risk_level = "SAFE"
    else:
        risk_level = "MODERATE"

    # Multi-Pillar Reason Generation
    all_reasons = []
    if mlp_reason:            all_reasons.append(mlp_reason)
    if reversal_reason:       all_reasons.append(reversal_reason)
    if vcp_reason:            all_reasons.append(vcp_reason)
    elif vcp_catalyst:        all_reasons.append(vcp_catalyst)
    if candlestick_catalyst:  all_reasons.append(candlestick_catalyst)
    if mtf_info.get("is_triple_confluence"):
        all_reasons.append("⚡ Triple MTF Confluence: Daily, Intermediate, and Weekly trends strictly bullish")
    elif mtf_gated:
        all_reasons.append("🛡️ MTF Guardrail: Demoted to WATCH due to bearish Weekly trend counter-current")
    if gap_gated and gap_retest_limit_price:
        all_reasons.append(f"🛡️ Guardrail 7: Gap-Exhaustion Alert — Gapped up +{gap_up_pct:.1f}% (58.7% intraday fade probability). Demoted to WATCH; limit entry recommended near ₹{gap_retest_limit_price:,.2f} on pullback")
    elif gap_exhaustion_alert and primary_signal == "BUY" and gap_retest_limit_price:
        all_reasons.append(f"⚡ Tactical Retest Entry: High-conviction gap-up (+{gap_up_pct:.1f}%). Limit entry recommended at 50% gap retest (₹{gap_retest_limit_price:,.2f})")
    if primary_signal == "BUY" and momentum_6m_pct >= 20.0:
        all_reasons.append(f"🚀 Elite Momentum: +{momentum_6m_pct:.1f}% 6M Intermediate Upcycle")
    elif primary_signal == "BUY" and momentum_6m_pct < -5.0:
        all_reasons.append(f"⚠️ Counter-Trend Bounce: Stock down {momentum_6m_pct:.1f}% over 6M")
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

    # ── Momentum vs. ML Projection Cross-Validation ──────────────────────────
    mom_ml_val = verify_momentum_vs_ml_projection(
        symbol=stock.symbol,
        momentum_pct=momentum_6m_pct,
        ml_forecast_pct=ml_forecast_chg,
    )
    if mom_ml_val["status"] == "BULL_TRAP_DIVERGENCE" and primary_signal == "BUY":
        # Guardrail: Downgrade strength to prevent over-sizing into momentum exhaustion
        if strength in ["CONVICTION", "STRONG"]:
            strength = "MODERATE"

    # AI & News Pillar
    if ml_signal == primary_signal:
        all_reasons.append(f"🤖 AI Forecast: {ml_signal} with {ml_confidence:.0%} confidence")
    if mom_ml_val["status"] != "NEUTRAL":
        all_reasons.append(f"🤖 Trend vs ML: {mom_ml_val['badge']} — {mom_ml_val['explanation']}")
    news = get_asset_specific_news_sentiment(stock.symbol, stock.name)
    if abs(news.get("sentiment_score", 0.0)) > 15.0:
        all_reasons.append(f"📰 News Sentiment: {news['sentiment_verdict']} ({news['sentiment_score']:+.1f}/100)")

    if not all_reasons:
        all_reasons.append(f"5-Pillar Apex Quant Score: {final_score:.1f}/100")

    key_reason = all_reasons[0] if all_reasons else f"5-Pillar Score: {final_score:.1f}"
    # ── Swing low/high for structural SL anchor ───────────────────────────────
    swing_low = swing_high = None
    poc_val = None
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

        # Calculate Volume Profile Point of Control (POC) Anchor
        if len(price_df) >= 20:
            try:
                from core.volume_profile import compute_volume_profile
                vp_info = compute_volume_profile(price_df.tail(60))
                if vp_info and "poc_price" in vp_info:
                    poc_val = float(vp_info["poc_price"])
            except Exception as e:
                logger.debug(f"Volume profile POC calculation notice: {e}")

    targets = calculate_targets(
        close, atr, primary_signal, trend_strength,
        adx=adx_val,
        market_cap_tier=stock.market_cap_tier or "mid",
        vix=vix_level,
        swing_low=swing_low,
        swing_high=swing_high,
        poc_price=poc_val,
        gap_limit_price=(gap_retest_limit_price if (gap_exhaustion_alert and primary_signal == "BUY") else None),
    )

    # ── Guardrail 8: Minimum Risk:Reward Ratio Gate ─────────────────────────────
    # [Backtested 2026-09-22]: 129/220 true stop-loss losses had R:R < 1.0 (avg score=57.4).
    # Structural flaw: accepting signals where T1 target < SL risk. Demote to WATCH.
    # Exception: high-conviction quality oversold reversals (Piotroski >= 7, score >= 60)
    # preserve their signal as they have a different profit mechanism (mean reversion bounce).
    if primary_signal in ("BUY", "SELL"):
        t1_upside = abs(targets.get("t1_upside_pct", 0.0) or 0.0)
        t2_upside = abs(targets.get("t2_upside_pct", 0.0) or 0.0)
        t3_upside = abs(targets.get("t3_upside_pct", 0.0) or 0.0)
        sl_risk   = abs(targets.get("sl_downside_pct", 0.0) or 0.0)
        # Institutional Blended Swing R:R (50% size at T1 de-risking, 25% at T2, 25% runner at T3)
        blended_upside = 0.50 * t1_upside + 0.25 * t2_upside + 0.25 * t3_upside
        blended_rr = blended_upside / max(0.01, sl_risk)
        t2_rr = t2_upside / max(0.01, sl_risk)
        effective_rr = max(blended_rr, t2_rr)
        min_rr_threshold = 1.05
        # Relax to 0.90 for quality contrarian reversals (these earn differently)
        if is_quality_oversold_reversal and pio_score >= 7 and final_score >= 60.0:
            min_rr_threshold = 0.90
        if effective_rr < min_rr_threshold and primary_signal in ("BUY", "SELL"):
            logger.debug(
                f"Guardrail 8 (R:R gate): {stock.symbol} demoted {primary_signal} → WATCH "
                f"(R:R={effective_rr:.2f} < {min_rr_threshold}, Blended={blended_upside:.2f}%, SL={sl_risk:.2f}%)"
            )
            primary_signal = "WATCH"
            strength = "NEUTRAL"
            all_reasons.insert(0, f"🛡️ Guardrail 8: Insufficient R:R ({effective_rr:.2f}x < {min_rr_threshold}x). Blended Gain={blended_upside:.1f}% vs SL={sl_risk:.1f}%. Demoted to WATCH.")

    # ── Guardrail 9: Friday Signal Day-of-Week Gate ────────────────────────────
    # [Backtested 2026-09-22]: Friday signals have 35.6% loss rate and -0.33% avg return
    # (worst day of the week by far due to weekend holding risk & retail noise).
    # Demote Friday BUY signals to WATCH unless ultra-high conviction (final_score >= 68.0).
    try:
        if isinstance(today, str):
            sig_dt = datetime.strptime(today[:10], "%Y-%m-%d").date()
        elif isinstance(today, datetime):
            sig_dt = today.date()
        elif isinstance(today, date):
            sig_dt = today
        else:
            sig_dt = date.today()
        is_friday = (sig_dt.weekday() == 4)
    except Exception:
        is_friday = False

    if is_friday and primary_signal == "BUY" and final_score < 68.0:
        logger.debug(f"Guardrail 9 (Friday Gate): {stock.symbol} BUY demoted to WATCH due to Friday weekend gap risk")
        primary_signal = "WATCH"
        strength = "NEUTRAL"
        all_reasons.insert(0, "🛡️ Guardrail 9: Friday Weekend Gap Gate — Demoted BUY to WATCH (historical Friday loss rate is 35.6% vs Mon-Thu 23.0%).")

    # ── Guardrail 10: Sector-Adaptive Conviction Gate ──────────────────────────
    # [Backtested 2026-09-22]: Banking & Finance (36.7% LR), Capital Goods (33.7% LR),
    # Metals & Mining (40.8% LR) bleed alpha under generic hurdles.
    # Require final_score >= 60.0 for these lagging sectors.
    sec_name = (stock.sector or "").strip()
    is_lag_sector = False
    if any(k in sec_name.upper() for k in ["BANK", "FINANC", "CAPITAL GOODS", "ENGINEERING", "METAL", "MINING", "STEEL"]):
        is_lag_sector = True
    
    if is_lag_sector and primary_signal in ("BUY", "SELL") and final_score < 60.0:
        logger.debug(f"Guardrail 10 (Sector Gate): {stock.symbol} {primary_signal} demoted to WATCH ({sec_name} score {final_score:.1f} < 60.0)")
        primary_signal = "WATCH"
        strength = "NEUTRAL"
        all_reasons.insert(0, f"🛡️ Guardrail 10: Sector Hurdle — {sec_name} requires minimum score 60.0 (got {final_score:.1f}). Demoted to WATCH.")

    key_reason = all_reasons[0] if all_reasons else f"5-Pillar Score: {final_score:.1f}"

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
        "sector_alignment": round(sector_alignment, 2),
        "signal_age_days": 0,  # freshness tracking — will be updated by audit updater
        "momentum_vs_ml": mom_ml_val["status"],
        "momentum_6m_pct": momentum_6m_pct,
        "mtf_confluence": mtf_info.get("confluence_badge", "⚪ Neutral MTF"),
        "mtf_tier": mtf_info.get("confluence_tier", "UNKNOWN"),
        "mtf_score": mtf_info.get("confluence_score", 50.0),
        "poc_price": poc_val,
        "gap_exhaustion_alert": gap_exhaustion_alert,
        "gap_retest_limit_price": gap_retest_limit_price,
        "multi_lookback_champion": mlp_eval["qualifies"],
        "multi_lookback_tier": mlp_eval.get("tier", "NONE"),
        "multi_lookback_badge": mlp_eval.get("badge", ""),
        "mom_1m": mlp_eval["mom_1m"],
        "mom_3m": mlp_eval["mom_3m"],
        "mom_12m": mlp_eval["mom_12m"],
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

    # Regime context
    regime = _load_market_regime(session)
    logger.info(f"Generating 5-Pillar Apex Signals for {total} stocks (regime: {'BULL' if regime['nifty_above_50ema'] else 'BEAR'}, VIX={regime['vix']:.1f})...")
    db_cols = None

    try:
        session.execute(text("ALTER TABLE signals ADD COLUMN momentum_vs_ml VARCHAR(50)"))
        session.commit()
    except Exception:
        session.rollback()

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

            price_df = get_price_dataframe(stock.symbol, session, days=400)

            # Fix 4: Use actual ML forecast from Forecast table (not circular composite_score)
            ml_sig, ml_conf, ml_chg_val = "WATCH", 0.5, None
            try:
                fc_row = session.query(Forecast).filter(
                    Forecast.symbol == stock.symbol
                ).order_by(Forecast.generated_date.desc()).first()
                if fc_row:
                    ml_chg_val = float(fc_row.forecast_1m_change_pct if fc_row.forecast_1m_change_pct is not None else (fc_row.forecast_7d_change_pct or 0.0))
                    if fc_row.forecast_7d_change_pct is not None:
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
                ml_forecast_chg=ml_chg_val,
            )

            if sig_dict:
                if db_cols is None:
                    try:
                        col_rows = session.execute(text("PRAGMA table_info(signals)")).fetchall()
                        db_cols = {c[1] for c in col_rows}
                    except Exception:
                        db_cols = set()
                insert_dict = {k: v for k, v in sig_dict.items() if not db_cols or k in db_cols}
                cols = ", ".join(insert_dict.keys())
                placeholders = ", ".join(f":{k}" for k in insert_dict.keys())
                session.execute(text(f"INSERT OR REPLACE INTO signals ({cols}) VALUES ({placeholders})"), insert_dict)

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