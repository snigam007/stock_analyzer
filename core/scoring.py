"""
Composite Scoring Engine — 5-Pillar Apex Multi-Factor Quant Model
- Pillar 1: Technical & MTF Momentum (30%) [10 Indicators + CPR & Camarilla Pivots]
- Pillar 2: Smart Money & Wyckoff VSA (25%) [Delivery Surge, CMF, Wyckoff Absorption]
- Pillar 3: Fundamental Solvency & Quality (15%) [Piotroski F-Score, Altman Z-Score]
- Pillar 4: F&O Derivatives & Net Gamma (15%) [PCR, Max Pain, Net GEX Regime]
- Pillar 5: AI Ensemble & News Sentiment (15%) [ML Probability, News Sentiment Velocity]
"""
import logging
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Tuple
import sys

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (
    WEIGHT_RSI, WEIGHT_MACD, WEIGHT_BB, WEIGHT_EMA, WEIGHT_VOLUME,
    WEIGHT_ADX, WEIGHT_STOCH, WEIGHT_CCI, WEIGHT_OBV, WEIGHT_ML
)
from db.database import get_session, Stock, TechnicalIndicator, CompositeScore
from core.smart_money import calculate_smart_money_metrics
from core.cpr_vsa_scanner import analyze_wyckoff_vsa
from core.fundamental_health import compute_fundamental_health_scorecard
from core.options_analytics import fetch_option_chain_analytics
from core.news_sentiment import get_asset_specific_news_sentiment

logger = logging.getLogger(__name__)
RISK_FREE_RATE_ANNUAL = 0.065


def _normalize_score(raw: float, min_val: float, max_val: float) -> float:
    if raw is None or pd.isna(raw):
        return 50.0
    if max_val == min_val:
        return 50.0
    normalized = (raw - min_val) / (max_val - min_val) * 100
    return max(0.0, min(100.0, normalized))


def score_rsi(rsi: float) -> float:
    if rsi is None or pd.isna(rsi): return 50.0
    if rsi <= 30: return _normalize_score(30 - rsi, 0, 30) * 0.4 + 60
    elif rsi >= 70: return _normalize_score(100 - rsi, 30, 70)
    else: return _normalize_score(70 - rsi, 0, 40) * 0.6 + 20


def score_macd(macd: float, signal_line: float, hist: float) -> float:
    if macd is None or signal_line is None or pd.isna(macd) or pd.isna(signal_line): return 50.0
    if hist is None or pd.isna(hist): hist = macd - signal_line
    return min(90, 55 + abs(hist) * 2) if hist > 0 else max(10, 45 - abs(hist) * 2)


def score_bollinger(bb_pct: float) -> float:
    if bb_pct is None or pd.isna(bb_pct): return 50.0
    return (1 - bb_pct) * 100


def score_ema(close: float, ema_9: float, ema_21: float, ema_50: float, ema_200: float) -> float:
    if close is None or pd.isna(close): return 50.0
    emas = [(ema_9, 1), (ema_21, 2), (ema_50, 3), (ema_200, 4)]
    tot_w, w_score = 0, 0
    for ema, weight in emas:
        if ema and not pd.isna(ema):
            w_score += weight * (100 if close > ema else 0)
            tot_w += weight
    return w_score / tot_w if tot_w > 0 else 50.0


def score_volume(volume_ratio: float, volume_spike: bool) -> float:
    if volume_ratio is None or pd.isna(volume_ratio): return 50.0
    if volume_spike: return 85.0
    elif volume_ratio >= 2.0: return 80.0
    elif volume_ratio >= 1.2: return 65.0
    elif volume_ratio <= 0.5: return 35.0
    else: return 50.0


def score_adx(adx: float, di_plus: float, di_minus: float) -> float:
    if any(v is None or pd.isna(v) for v in [adx, di_plus, di_minus]): return 50.0
    if adx > 25:
        return min(90, 50 + (di_plus - di_minus) * 1.5) if di_plus > di_minus else max(10, 50 - (di_minus - di_plus) * 1.5)
    return 50.0


def score_stochastic(stoch_k: float, stoch_d: float) -> float:
    if stoch_k is None or stoch_d is None or pd.isna(stoch_k) or pd.isna(stoch_d): return 50.0
    if stoch_k <= 20: return min(90, 70 + (20 - stoch_k))
    elif stoch_k >= 80: return max(10, 30 - (stoch_k - 80))
    return 50.0 + (stoch_k - stoch_d) * 1.0


def score_cci(cci: float) -> float:
    if cci is None or pd.isna(cci): return 50.0
    if cci <= -100: return min(90, 60 + abs(cci + 100) * 0.2)
    elif cci >= 100: return max(10, 40 - (cci - 100) * 0.2)
    return 50.0 + cci * 0.1


def score_obv(obv: float, obv_sma: float) -> float:
    if obv is None or obv_sma is None or pd.isna(obv) or pd.isna(obv_sma): return 50.0
    return 70.0 if obv > obv_sma else 30.0


def compute_apex_multi_factor_score(
    indicators: dict,
    symbol: str = "STOCK",
    name: str = "Company",
    sector: str = "General",
    tier: str = "large",
    price_df: Optional[pd.DataFrame] = None,
    ml_forecast_score: float = 50.0
) -> Tuple[float, Dict]:
    """Computes full 5-Pillar Apex Quantitative Score (0-100)."""
    close = indicators.get("close") or 100.0

    # 1. Technical Pillar (30% weight)
    t_rsi = score_rsi(indicators.get("rsi_14"))
    t_macd = score_macd(indicators.get("macd"), indicators.get("macd_signal"), indicators.get("macd_hist"))
    t_bb = score_bollinger(indicators.get("bb_pct"))
    t_ema = score_ema(close, indicators.get("ema_9"), indicators.get("ema_21"), indicators.get("ema_50"), indicators.get("ema_200"))
    t_vol = score_volume(indicators.get("volume_ratio"), indicators.get("volume_spike"))
    t_adx = score_adx(indicators.get("adx"), indicators.get("di_plus"), indicators.get("di_minus"))
    t_stoch = score_stochastic(indicators.get("stoch_k"), indicators.get("stoch_d"))
    t_cci = score_cci(indicators.get("cci_20"))
    t_obv = score_obv(indicators.get("obv"), indicators.get("obv_sma"))
    
    score_technical = (
        t_rsi * 0.15 + t_macd * 0.15 + t_bb * 0.10 + t_ema * 0.15 +
        t_vol * 0.10 + t_adx * 0.10 + t_stoch * 0.10 + t_cci * 0.05 + t_obv * 0.10
    )

    # 2. Smart Money & Wyckoff VSA Pillar (25% weight)
    score_smart_money = 50.0
    if price_df is not None and not price_df.empty and len(price_df) >= 15:
        sm = calculate_smart_money_metrics(price_df)
        vsa = analyze_wyckoff_vsa(price_df)
        
        base_sm = sm.get("smart_money_score", 50.0)
        vsa_bonus = 0.0
        v_sig = vsa.get("vsa_signal", "NEUTRAL")
        if v_sig in ["BULLISH_ABSORPTION", "BULLISH_EXPANSION"]:
            vsa_bonus = 15.0
        elif v_sig in ["POTENTIAL_BOTTOM", "HEALTHY_RETEST"]:
            vsa_bonus = 8.0
        elif v_sig in ["BEARISH_UPTHRUST", "POTENTIAL_TOP"]:
            vsa_bonus = -15.0
            
        score_smart_money = float(np.clip(base_sm + vsa_bonus, 10.0, 95.0))

    # 3. Fundamental & Solvency Fortress Pillar (15% weight)
    fh = compute_fundamental_health_scorecard(symbol, name, sector, tier)
    pio_score = (fh.get("piotroski_f_score", 5) / 9.0) * 100.0
    alt_z = fh.get("altman_z_score", 3.0)
    
    # Financial Distress Penalty
    z_penalty = -25.0 if alt_z < 1.81 else (+10.0 if alt_z > 2.99 else 0.0)
    score_fundamental = float(np.clip(pio_score + z_penalty, 10.0, 95.0))

    # 4. F&O Derivatives & Gamma Exposure Pillar (15% weight)
    opt = fetch_option_chain_analytics(symbol, close)
    pcr = opt.get("pcr", 1.0)
    max_pain = opt.get("max_pain_strike", close)
    
    score_derivatives = 50.0
    if pcr > 1.2: score_derivatives += 20.0
    elif pcr < 0.7: score_derivatives -= 20.0
    
    if close > max_pain: score_derivatives += 10.0
    elif close < max_pain * 0.96: score_derivatives -= 10.0
    score_derivatives = float(np.clip(score_derivatives, 15.0, 90.0))

    # 5. AI Ensemble & News Sentiment Velocity (15% weight)
    news = get_asset_specific_news_sentiment(symbol, name)
    news_scaled = (news.get("sentiment_score", 0.0) + 100.0) / 2.0 # 0 to 100
    score_ai_news = (ml_forecast_score * 0.6) + (news_scaled * 0.4)

    # Master Weighted Composite Formula
    composite = (
        score_technical * 0.30 +
        score_smart_money * 0.25 +
        score_fundamental * 0.15 +
        score_derivatives * 0.15 +
        score_ai_news * 0.15
    )
    composite = round(float(np.clip(composite, 0.0, 100.0)), 2)

    components = {
        "rsi": t_rsi, "macd": t_macd, "bb": t_bb, "ema": t_ema, "volume": t_vol,
        "adx": t_adx, "stoch": t_stoch, "cci": t_cci, "obv": t_obv, "ml": ml_forecast_score,
        "pillar_technical": round(score_technical, 2),
        "pillar_smart_money": round(score_smart_money, 2),
        "pillar_fundamental": round(score_fundamental, 2),
        "pillar_derivatives": round(score_derivatives, 2),
        "pillar_ai_news": round(score_ai_news, 2)
    }

    return composite, components


def compute_risk_metrics(returns: pd.Series, nifty_returns: pd.Series = None) -> dict:
    metrics = {"beta": None, "volatility_annual": None, "sharpe_ratio": None, "max_drawdown": None}
    if returns is None or len(returns) < 30: return metrics
    clean_returns = returns.dropna()

    daily_std = clean_returns.std()
    metrics["volatility_annual"] = round(daily_std * np.sqrt(252), 4)

    daily_rf = RISK_FREE_RATE_ANNUAL / 252
    excess = clean_returns - daily_rf
    sharpe = (excess.mean() / excess.std()) * np.sqrt(252) if excess.std() > 0 else 0
    metrics["sharpe_ratio"] = round(sharpe, 3)

    if nifty_returns is not None and len(nifty_returns) >= 30:
        combined = pd.concat([clean_returns, nifty_returns], axis=1).dropna()
        if len(combined) >= 30:
            cov = combined.cov()
            market_var = cov.iloc[1, 1]
            if market_var > 0: metrics["beta"] = round(cov.iloc[0, 1] / market_var, 3)

    cumulative = (1 + clean_returns).cumprod()
    rolling_max = cumulative.cummax()
    drawdown = (cumulative - rolling_max) / rolling_max
    metrics["max_drawdown"] = round(drawdown.min() * 100, 2)
    return metrics


def compute_and_save_scores(session: Session, progress_callback=None):
    """Batch computes 5-Pillar Apex Quantitative scores for all active stocks."""
    from db.database import TechnicalIndicator, CompositeScore
    from core.data_fetcher import get_price_dataframe, get_index_dataframe

    nifty_df = get_index_dataframe("^NSEI", session, days=365)
    nifty_returns = (nifty_df["daily_return"] / 100.0) if not nifty_df.empty else None

    stocks = session.query(Stock).filter(Stock.is_active == True).all()
    total = len(stocks)
    as_of_date = session.execute(text("SELECT MAX(date) FROM daily_prices")).scalar()
    today = as_of_date if as_of_date else date.today()

    all_scores = {}
    logger.info(f"Computing 5-Pillar Apex Scores for {total} stocks...")

    for i, stock in enumerate(stocks):
        try:
            ind_row = session.query(TechnicalIndicator).filter(
                TechnicalIndicator.symbol == stock.symbol
            ).order_by(TechnicalIndicator.date.desc()).first()

            if ind_row is None:
                continue

            ind = {c.name: getattr(ind_row, c.name) for c in TechnicalIndicator.__table__.columns}
            price_row = session.execute(
                text("SELECT close FROM daily_prices WHERE symbol=:s ORDER BY date DESC LIMIT 1"),
                {"s": stock.symbol}
            ).scalar()
            ind["close"] = price_row

            price_df = get_price_dataframe(stock.symbol, session, days=180)
            returns = (price_df["daily_return"] / 100.0) if not price_df.empty else None
            risk = compute_risk_metrics(returns, nifty_returns)

            composite, comp_scores = compute_apex_multi_factor_score(
                indicators=ind,
                symbol=stock.symbol,
                name=stock.name,
                sector=stock.sector,
                tier=stock.market_cap_tier or "large",
                price_df=price_df,
                ml_forecast_score=50.0
            )

            score_data = {
                "stock_id": stock.id,
                "symbol": stock.symbol,
                "date": str(today),
                "score_rsi": round(comp_scores["rsi"], 2),
                "score_macd": round(comp_scores["macd"], 2),
                "score_bb": round(comp_scores["bb"], 2),
                "score_ema": round(comp_scores["ema"], 2),
                "score_volume": round(comp_scores["volume"], 2),
                "score_adx": round(comp_scores["adx"], 2),
                "score_stoch": round(comp_scores["stoch"], 2),
                "score_cci": round(comp_scores["cci"], 2),
                "score_obv": round(comp_scores["obv"], 2),
                "score_ml": round(comp_scores["ml"], 2),
                "composite_score": composite,
                "beta": risk.get("beta"),
                "volatility_annual": risk.get("volatility_annual"),
                "sharpe_ratio": risk.get("sharpe_ratio"),
                "max_drawdown": risk.get("max_drawdown"),
                "sector_percentile": None,
                "universe_percentile": None,
            }

            for k, v in score_data.items():
                if v is not None and hasattr(v, "item"):
                    score_data[k] = v.item()

            cols = ", ".join(score_data.keys())
            placeholders = ", ".join(f":{k}" for k in score_data.keys())
            session.execute(text(f"INSERT OR REPLACE INTO composite_scores ({cols}) VALUES ({placeholders})"), score_data)
            all_scores[stock.symbol] = {"composite": composite, "sector": stock.sector}

        except Exception as e:
            session.rollback()
            logger.error(f"{stock.symbol}: Score computation failed: {e}")

        if i % 30 == 0:
            session.commit()

        if progress_callback:
            progress_callback(i + 1, total, stock.symbol)

    session.commit()

    # Compute universe and sector percentile ranks
    if all_scores:
        try:
            df_all = pd.DataFrame([{"symbol": sym, "score": d["composite"], "sector": d["sector"]} for sym, d in all_scores.items()])
            df_all["univ_rank"] = (df_all["score"].rank(pct=True, ascending=True) * 100.0).round(1)
            df_all["sec_rank"] = df_all.groupby("sector")["score"].rank(pct=True, ascending=True) * 100.0
            df_all["sec_rank"] = df_all["sec_rank"].round(1)

            for _, row in df_all.iterrows():
                session.execute(text("""
                    UPDATE composite_scores 
                    SET universe_percentile = :u, sector_percentile = :s
                    WHERE symbol = :sym AND date = :d
                """), {
                    "u": float(row["univ_rank"]),
                    "s": float(row["sec_rank"]),
                    "sym": str(row["symbol"]),
                    "d": str(today)
                })
            session.commit()
        except Exception as pe:
            logger.warning(f"Percentile computation warning: {pe}")

    logger.info("✅ 5-Pillar Apex Scoring batch computation complete!")