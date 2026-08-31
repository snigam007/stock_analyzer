"""
Sector Peer Comparison & Relative Valuation Matrix Engine
- Multi-dimensional side-by-side benchmarking across performance, valuation, risk, and quality
- Sector cohort ranking and relative rotation percentile distribution
- Arbitrary custom peer group comparison
"""
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

from db.database import Stock, DailyPrice, TechnicalIndicator, CompositeScore, Signal
from core.fundamental_health import compute_fundamental_health_scorecard

logger = logging.getLogger(__name__)


def get_sector_peers_comparison(symbol: str, session: Session, limit: int = 15) -> Dict:
    """
    Retrieves all peer stocks within the same sector as `symbol` and computes
    a multi-dimensional ranking across Momentum, Returns, Volatility, and Fundamental Quality.
    """
    # 1. Look up target stock
    target_stock = session.query(Stock).filter(Stock.symbol == symbol.strip().upper()).first()
    if not target_stock:
        return {"error": f"Stock {symbol} not found"}

    sector = target_stock.sector

    # 2. Query all stocks in the sector
    sector_stocks = session.query(Stock).filter(
        Stock.sector == sector,
        Stock.is_active == True
    ).all()

    symbols = [s.symbol for s in sector_stocks]
    return get_custom_peer_comparison(symbols=symbols, session=session, focus_symbol=symbol)


def get_custom_peer_comparison(symbols: List[str], session: Session, focus_symbol: Optional[str] = None) -> Dict:
    """
    Computes comparative metrics for any custom list of stock symbols.
    """
    if not symbols:
        return {"peers": [], "metrics": {}}

    symbols = [s.strip().upper() for s in symbols]
    as_of_date = session.execute(text("SELECT MAX(date) FROM daily_prices")).scalar()

    peer_data = []

    for sym in symbols:
        stock = session.query(Stock).filter(Stock.symbol == sym).first()
        if not stock:
            continue

        # Fetch price history for returns (1Y = ~252 trading days)
        price_rows = session.execute(text("""
            SELECT date, close FROM daily_prices
            WHERE symbol = :s
            ORDER BY date DESC
            LIMIT 260
        """), {"s": sym}).fetchall()

        if not price_rows:
            continue

        prices = [float(r[1]) for r in price_rows if r[1] is not None]
        curr_price = prices[0] if prices else 0.0

        # Calculate returns across multiple timeframes
        ret_1w = round((curr_price - prices[min(5, len(prices)-1)]) / prices[min(5, len(prices)-1)] * 100, 2) if len(prices) > 5 else 0.0
        ret_1m = round((curr_price - prices[min(21, len(prices)-1)]) / prices[min(21, len(prices)-1)] * 100, 2) if len(prices) > 21 else 0.0
        ret_3m = round((curr_price - prices[min(63, len(prices)-1)]) / prices[min(63, len(prices)-1)] * 100, 2) if len(prices) > 63 else 0.0
        ret_6m = round((curr_price - prices[min(126, len(prices)-1)]) / prices[min(126, len(prices)-1)] * 100, 2) if len(prices) > 126 else 0.0
        ret_1y = round((curr_price - prices[min(250, len(prices)-1)]) / prices[min(250, len(prices)-1)] * 100, 2) if len(prices) > 250 else 0.0

        # Fetch latest technical indicators
        ti_row = session.execute(text("""
            SELECT rsi_14, adx, macd_hist, ema_50, ema_200, atr_14, volume_ratio
            FROM technical_indicators
            WHERE symbol = :s ORDER BY date DESC LIMIT 1
        """), {"s": sym}).first()

        rsi = round(float(ti_row[0] or 50.0), 1) if ti_row else 50.0
        adx = round(float(ti_row[1] or 20.0), 1) if ti_row else 20.0
        ema_50 = float(ti_row[3] or 0.0) if ti_row else 0.0
        ema_200 = float(ti_row[4] or 0.0) if ti_row else 0.0
        trend_regime = "Bullish (>50 & >200 EMA)" if (ema_50 and ema_200 and curr_price > ema_50 and curr_price > ema_200) else (
            "Neutral / Mixed" if (ema_200 and curr_price > ema_200) else "Bearish (<200 EMA)"
        )

        # Fetch composite scores & risk metrics
        cs_row = session.execute(text("""
            SELECT composite_score, beta, volatility_annual, sharpe_ratio, max_drawdown
            FROM composite_scores
            WHERE symbol = :s ORDER BY date DESC LIMIT 1
        """), {"s": sym}).first()

        comp_score = round(float(cs_row[0] or 50.0), 1) if cs_row else 50.0
        beta = round(float(cs_row[1] or 1.0), 2) if cs_row and cs_row[1] else 1.0
        volatility = round(float(cs_row[2] or 0.25) * 100, 1) if cs_row and cs_row[2] else 25.0
        sharpe = round(float(cs_row[3] or 0.0), 2) if cs_row and cs_row[3] else 0.0
        max_dd = round(float(cs_row[4] or 0.0), 1) if cs_row and cs_row[4] else 0.0

        # Fetch signal
        sig_row = session.execute(text("""
            SELECT signal, signal_strength, risk_level, target_price_1, stop_loss, risk_reward_ratio
            FROM signals
            WHERE symbol = :s ORDER BY date DESC LIMIT 1
        """), {"s": sym}).first()

        signal = sig_row[0] if sig_row else "WATCH"
        risk_lvl = sig_row[2] if sig_row else "MODERATE"
        target_1 = sig_row[3] if sig_row else None
        stop_loss = sig_row[4] if sig_row else None
        rr_ratio = sig_row[5] if sig_row else None

        # Fetch fundamental health
        fh = compute_fundamental_health_scorecard(stock.symbol, stock.name, stock.sector, stock.market_cap_tier or "mid")
        piotroski = fh.get("piotroski_f_score", 5)
        altman_z = round(fh.get("altman_z_score", 3.0), 2)
        solvency = fh.get("health_verdict", "Sound Quality")

        peer_data.append({
            "symbol": stock.symbol,
            "name": stock.name,
            "sector": stock.sector,
            "tier": stock.market_cap_tier or "Mid",
            "current_price": curr_price,
            "signal": signal,
            "composite_score": comp_score,
            "ret_1w": ret_1w,
            "ret_1m": ret_1m,
            "ret_3m": ret_3m,
            "ret_6m": ret_6m,
            "ret_1y": ret_1y,
            "rsi": rsi,
            "adx": adx,
            "beta": beta,
            "volatility_pct": volatility,
            "sharpe_ratio": sharpe,
            "max_drawdown_pct": max_dd,
            "piotroski_f": piotroski,
            "altman_z": altman_z,
            "solvency": solvency,
            "trend_regime": trend_regime,
            "target_1": target_1,
            "stop_loss": stop_loss,
            "risk_reward": rr_ratio,
            "is_focus": (stock.symbol == (focus_symbol or "").upper()),
        })

    if not peer_data:
        return {"peers": [], "metrics": {}}

    # Rank peers by composite score and 3M performance
    df_peers = pd.DataFrame(peer_data)
    df_peers["score_rank"] = df_peers["composite_score"].rank(ascending=False, method="min").astype(int)
    df_peers["ret_3m_rank"] = df_peers["ret_3m"].rank(ascending=False, method="min").astype(int)
    df_peers["quality_rank"] = df_peers["piotroski_f"].rank(ascending=False, method="min").astype(int)

    peers_ranked = df_peers.sort_values(by="composite_score", ascending=False).to_dict(orient="records")

    # Sector aggregate benchmarks
    sector_averages = {
        "avg_composite_score": round(df_peers["composite_score"].mean(), 1),
        "avg_ret_1m": round(df_peers["ret_1m"].mean(), 2),
        "avg_ret_3m": round(df_peers["ret_3m"].mean(), 2),
        "avg_ret_1y": round(df_peers["ret_1y"].mean(), 2),
        "avg_rsi": round(df_peers["rsi"].mean(), 1),
        "avg_beta": round(df_peers["beta"].mean(), 2),
        "avg_volatility": round(df_peers["volatility_pct"].mean(), 1),
        "avg_sharpe": round(df_peers["sharpe_ratio"].mean(), 2),
        "avg_piotroski": round(df_peers["piotroski_f"].mean(), 1),
        "avg_altman_z": round(df_peers["altman_z"].mean(), 2),
        "peer_count": len(peers_ranked),
    }

    return {
        "peers": peers_ranked,
        "sector_averages": sector_averages,
        "as_of_date": str(as_of_date),
    }
