"""
Composite Scoring Engine
Combines all 10 technical indicator scores + ML into a 0-100 composite score.
Also computes risk metrics: beta, volatility, Sharpe ratio, max drawdown.
"""
import logging
import warnings
from datetime import date, timedelta
from pathlib import Path
from typing import Optional
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

logger = logging.getLogger(__name__)

# Risk-free rate (approximate Indian T-bill rate)
RISK_FREE_RATE_ANNUAL = 0.065


def _normalize_score(raw: float, min_val: float, max_val: float) -> float:
    """Normalize a raw value to 0-100 range."""
    if raw is None or pd.isna(raw):
        return 50.0
    if max_val == min_val:
        return 50.0
    normalized = (raw - min_val) / (max_val - min_val) * 100
    return max(0.0, min(100.0, normalized))


def score_rsi(rsi: float) -> float:
    """RSI score: 0 = overbought, 100 = oversold."""
    if rsi is None or pd.isna(rsi):
        return 50.0
    # Invert: low RSI = high score (oversold = buy opportunity)
    if rsi <= 30:
        return _normalize_score(30 - rsi, 0, 30) * 0.4 + 60
    elif rsi >= 70:
        return _normalize_score(100 - rsi, 30, 70)
    else:
        # Linear between 30-70 → score 30-70 (with 50 RSI = 50 score)
        return _normalize_score(70 - rsi, 0, 40) * 0.6 + 20


def score_macd(macd: float, signal_line: float, hist: float) -> float:
    """MACD score based on momentum."""
    if macd is None or signal_line is None or pd.isna(macd) or pd.isna(signal_line):
        return 50.0
    if hist is None or pd.isna(hist):
        hist = macd - signal_line

    # Positive histogram = bullish
    if hist > 0:
        return min(90, 55 + abs(hist) * 2)
    else:
        return max(10, 45 - abs(hist) * 2)


def score_bollinger(bb_pct: float) -> float:
    """Bollinger %B score: low %B (near lower band) = high score."""
    if bb_pct is None or pd.isna(bb_pct):
        return 50.0
    # bb_pct: 0 = at lower band (buy), 1 = at upper band (sell)
    return (1 - bb_pct) * 100


def score_ema(close: float, ema_9: float, ema_21: float, ema_50: float, ema_200: float) -> float:
    """EMA alignment score."""
    if close is None or pd.isna(close):
        return 50.0

    emas = [(ema_9, 1), (ema_21, 2), (ema_50, 3), (ema_200, 4)]
    total_weight = 0
    weighted_score = 0

    for ema, weight in emas:
        if ema and not pd.isna(ema):
            if close > ema:
                weighted_score += weight * 100
            else:
                weighted_score += weight * 0
            total_weight += weight

    if total_weight == 0:
        return 50.0
    return weighted_score / total_weight


def score_volume(volume_ratio: float, trend_direction: str) -> float:
    """Volume confirmation score."""
    if volume_ratio is None or pd.isna(volume_ratio):
        return 50.0

    if trend_direction == "UP" and volume_ratio > 1.0:
        return min(90, 50 + (volume_ratio - 1) * 30)
    elif trend_direction == "DOWN" and volume_ratio > 1.0:
        return max(10, 50 - (volume_ratio - 1) * 30)
    elif volume_ratio < 0.5:
        return 45.0  # Low volume — weak conviction
    return 50.0


def score_adx(adx: float, di_plus: float, di_minus: float) -> float:
    """ADX directional score."""
    if adx is None or pd.isna(adx):
        return 50.0
    if adx < 15:
        return 50.0  # No trend

    if di_plus and di_minus and not pd.isna(di_plus) and not pd.isna(di_minus):
        if di_plus > di_minus:
            return min(90, 50 + adx * 0.5)
        else:
            return max(10, 50 - adx * 0.5)
    return 50.0


def score_stochastic(k: float, d: float) -> float:
    """Stochastic score."""
    if k is None or pd.isna(k):
        return 50.0
    return (100 - k)  # Low K = oversold = high score


def score_cci(cci: float) -> float:
    """CCI score."""
    if cci is None or pd.isna(cci):
        return 50.0
    # Map CCI (-300 to +300) to 0-100
    return _normalize_score(-cci, -300, 300)


def score_obv(obv: float, obv_sma: float) -> float:
    """OBV trend score."""
    if obv is None or obv_sma is None or pd.isna(obv) or pd.isna(obv_sma):
        return 50.0
    ratio = (obv / obv_sma) if obv_sma != 0 else 1.0
    return min(90, max(10, 50 + (ratio - 1) * 50))


def compute_composite_score(
    ind: dict,
    ml_score: float = 50.0,
    trend_direction: str = "SIDEWAYS",
) -> float:
    """
    Compute weighted composite score from all indicators.
    Returns float 0-100.
    """
    close = ind.get("close") or 0

    scores = {
        "rsi": score_rsi(ind.get("rsi_14")),
        "macd": score_macd(ind.get("macd"), ind.get("macd_signal"), ind.get("macd_hist")),
        "bb": score_bollinger(ind.get("bb_pct")),
        "ema": score_ema(close, ind.get("ema_9"), ind.get("ema_21"), ind.get("ema_50"), ind.get("ema_200")),
        "volume": score_volume(ind.get("volume_ratio"), trend_direction),
        "adx": score_adx(ind.get("adx"), ind.get("di_plus"), ind.get("di_minus")),
        "stoch": score_stochastic(ind.get("stoch_k"), ind.get("stoch_d")),
        "cci": score_cci(ind.get("cci_20")),
        "obv": score_obv(ind.get("obv"), ind.get("obv_sma")),
        "ml": ml_score,
    }

    weights = {
        "rsi": WEIGHT_RSI,
        "macd": WEIGHT_MACD,
        "bb": WEIGHT_BB,
        "ema": WEIGHT_EMA,
        "volume": WEIGHT_VOLUME,
        "adx": WEIGHT_ADX,
        "stoch": WEIGHT_STOCH,
        "cci": WEIGHT_CCI,
        "obv": WEIGHT_OBV,
        "ml": WEIGHT_ML,
    }

    composite = sum(scores[k] * weights[k] for k in scores)
    return round(min(100, max(0, composite)), 2), scores


def compute_risk_metrics(
    returns: pd.Series,
    nifty_returns: pd.Series = None,
) -> dict:
    """
    Compute beta, annualized volatility, Sharpe ratio, and max drawdown.
    """
    metrics = {
        "beta": None,
        "volatility_annual": None,
        "sharpe_ratio": None,
        "max_drawdown": None,
    }

    if returns is None or len(returns) < 30:
        return metrics

    clean_returns = returns.dropna()

    # Annualized volatility
    daily_std = clean_returns.std()
    metrics["volatility_annual"] = round(daily_std * np.sqrt(252), 4)

    # Sharpe ratio
    daily_rf = RISK_FREE_RATE_ANNUAL / 252
    excess = clean_returns - daily_rf
    sharpe = (excess.mean() / excess.std()) * np.sqrt(252) if excess.std() > 0 else 0
    metrics["sharpe_ratio"] = round(sharpe, 3)

    # Beta vs NIFTY
    if nifty_returns is not None and len(nifty_returns) >= 30:
        combined = pd.concat([clean_returns, nifty_returns], axis=1).dropna()
        if len(combined) >= 30:
            cov = combined.cov()
            market_var = cov.iloc[1, 1]
            if market_var > 0:
                metrics["beta"] = round(cov.iloc[0, 1] / market_var, 3)

    # Max Drawdown
    cumulative = (1 + clean_returns).cumprod()
    rolling_max = cumulative.cummax()
    drawdown = (cumulative - rolling_max) / rolling_max
    metrics["max_drawdown"] = round(drawdown.min() * 100, 2)

    return metrics


def compute_and_save_scores(session: Session, progress_callback=None):
    """Compute composite scores for all stocks and save to DB."""
    from db.database import TechnicalIndicator, CompositeScore
    from core.data_fetcher import get_price_dataframe, get_index_dataframe

    # Get NIFTY 50 returns for beta calculation
    nifty_df = get_index_dataframe("^NSEI", session, days=365)
    nifty_returns = nifty_df["daily_return"] / 100 if not nifty_df.empty else None

    stocks = session.query(Stock).filter(Stock.is_active == True).all()
    total = len(stocks)
    as_of_date = session.execute(text("SELECT MAX(date) FROM daily_prices")).scalar()
    today = as_of_date if as_of_date else date.today()

    # Sector scores for percentile computation (computed after all stocks)
    all_scores = {}

    logger.info(f"Computing composite scores for {total} stocks...")

    for i, stock in enumerate(stocks):
        try:
            # Get latest indicator
            ind_row = session.query(TechnicalIndicator).filter(
                TechnicalIndicator.symbol == stock.symbol
            ).order_by(TechnicalIndicator.date.desc()).first()

            if ind_row is None:
                continue

            ind = {c.name: getattr(ind_row, c.name) for c in TechnicalIndicator.__table__.columns}

            # Get current price
            price_row = session.execute(
                text("SELECT close FROM daily_prices WHERE symbol=:s ORDER BY date DESC LIMIT 1"),
                {"s": stock.symbol}
            ).scalar()
            ind["close"] = price_row

            trend = ind_row.trend_direction or "SIDEWAYS"
            composite, component_scores = compute_composite_score(ind, trend_direction=trend)

            # Get returns for risk metrics
            price_df = get_price_dataframe(stock.symbol, session, days=365)
            returns = (price_df["daily_return"] / 100) if not price_df.empty else None

            risk = compute_risk_metrics(returns, nifty_returns)

            score_data = {
                "score_rsi": round(component_scores["rsi"], 2),
                "score_macd": round(component_scores["macd"], 2),
                "score_bb": round(component_scores["bb"], 2),
                "score_ema": round(component_scores["ema"], 2),
                "score_volume": round(component_scores["volume"], 2),
                "score_adx": round(component_scores["adx"], 2),
                "score_stoch": round(component_scores["stoch"], 2),
                "score_cci": round(component_scores["cci"], 2),
                "score_obv": round(component_scores["obv"], 2),
                "score_ml": round(component_scores["ml"], 2),
                "composite_score": composite,
                "beta": risk.get("beta"),
                "volatility_annual": risk.get("volatility_annual"),
                "sharpe_ratio": risk.get("sharpe_ratio"),
                "max_drawdown": risk.get("max_drawdown"),
            }

            full_score_data = {
                "stock_id": stock.id,
                "symbol": stock.symbol,
                "date": str(today),
                **score_data,
                "sector_percentile": None,
                "universe_percentile": None,
            }
            # Clean numpy types
            for k, v in full_score_data.items():
                if v is not None and hasattr(v, "item"):
                    full_score_data[k] = v.item()

            cols = ", ".join(full_score_data.keys())
            placeholders = ", ".join(f":{k}" for k in full_score_data.keys())
            session.execute(text(f"INSERT OR REPLACE INTO composite_scores ({cols}) VALUES ({placeholders})"), full_score_data)

            all_scores[stock.symbol] = {"composite": composite, "sector": stock.sector}

        except Exception as e:
            session.rollback()
            logger.error(f"{stock.symbol}: Score computation failed: {e}")

        if i % 50 == 0:
            session.commit()

        if progress_callback:
            progress_callback(i + 1, total, stock.symbol)

    session.commit()

    # Compute sector and universe percentiles
    _compute_percentiles(all_scores, session, today)

    logger.info("✅ Composite scoring complete")


def _compute_percentiles(all_scores: dict, session: Session, today: date = None):
    """Update sector and universe percentile ranks."""
    if today is None:
        as_of = session.execute(text("SELECT MAX(date) FROM daily_prices")).scalar()
        if as_of:
            today = datetime.strptime(as_of[:10], "%Y-%m-%d").date() if isinstance(as_of, str) else as_of
        else:
            today = date.today()

    if not all_scores:
        return

    scores_series = pd.Series({s: v["composite"] for s, v in all_scores.items()})
    sector_map = {s: v["sector"] for s, v in all_scores.items()}

    for symbol, data in all_scores.items():
        # Universe percentile
        univ_pct = (scores_series < data["composite"]).sum() / len(scores_series) * 100

        # Sector percentile
        sector_stocks = {s: scores_series[s] for s in scores_series.index if sector_map.get(s) == data["sector"]}
        if sector_stocks:
            sec_series = pd.Series(sector_stocks)
            sec_pct = (sec_series < data["composite"]).sum() / len(sec_series) * 100
        else:
            sec_pct = 50.0

        session.execute(
            text("""
                UPDATE composite_scores
                SET universe_percentile=:up, sector_percentile=:sp
                WHERE symbol=:sym AND date=:d
            """),
            {"up": round(univ_pct, 1), "sp": round(sec_pct, 1), "sym": symbol, "d": str(today)}
        )

    session.commit()


def get_top_stocks_by_score(session: Session, limit: int = 15, sector: str = None) -> pd.DataFrame:
    """Get top N stocks by composite score for today."""
    query = """
        SELECT cs.symbol, s.name, s.sector, s.market_cap_tier,
               cs.composite_score, cs.universe_percentile, cs.sector_percentile,
               cs.beta, cs.volatility_annual, cs.sharpe_ratio, cs.max_drawdown,
               sig.signal, sig.signal_strength, sig.current_price,
               sig.buy_price, sig.target_price_1, sig.target_price_2, sig.stop_loss,
               sig.risk_reward_ratio, sig.risk_level, sig.key_reason,
               ind.trend_pattern, ind.trend_direction
        FROM composite_scores cs
        JOIN stocks s ON cs.symbol = s.symbol
        LEFT JOIN signals sig ON cs.symbol = sig.symbol AND cs.date = sig.date
        LEFT JOIN technical_indicators ind ON cs.symbol = ind.symbol AND cs.date = ind.date
        WHERE cs.date = (SELECT MAX(date) FROM composite_scores)
    """
    params = {}
    if sector:
        query += " AND s.sector = :sector"
        params["sector"] = sector

    query += " ORDER BY cs.composite_score DESC LIMIT :limit"
    params["limit"] = limit

    result = session.execute(text(query), params).fetchall()
    if not result:
        return pd.DataFrame()

    cols = [
        "symbol", "name", "sector", "tier", "composite_score",
        "universe_pct", "sector_pct", "beta", "volatility", "sharpe", "max_dd",
        "signal", "strength", "price", "buy_price", "target_1", "target_2", "stop_loss",
        "rr_ratio", "risk_level", "key_reason", "trend_pattern", "trend_direction"
    ]
    return pd.DataFrame(result, columns=cols)
