"""
Sector Analysis Engine
- Sector performance tracking
- Cross-sector correlation matrix
- Sector rotation detection
- Direct/inverse inter-sector impact rules
"""
import logging
import warnings
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import sys

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import SECTOR_CORRELATIONS
from db.database import (
    get_session, Stock, DailyPrice, SectorAnalysis, SectorCorrelation,
    Signal, CompositeScore
)

logger = logging.getLogger(__name__)


def get_sector_returns(session: Session, days: int = 90) -> pd.DataFrame:
    """
    Get average daily returns per sector for the last N days.
    Returns DataFrame: index=date, columns=sectors.
    """
    as_of = session.execute(text("SELECT MAX(date) FROM daily_prices")).scalar()
    if as_of:
        ref_date = datetime.strptime(str(as_of)[:10], "%Y-%m-%d").date() if isinstance(as_of, str) else as_of
    else:
        ref_date = date.today()

    start_date = (ref_date - timedelta(days=days)).strftime("%Y-%m-%d")

    result = session.execute(text("""
        SELECT p.date, s.sector, AVG(p.daily_return) as avg_return
        FROM daily_prices p
        JOIN stocks s ON p.symbol = s.symbol
        WHERE p.date >= :start
        GROUP BY p.date, s.sector
        ORDER BY p.date, s.sector
    """), {"start": start_date}).fetchall()

    if not result:
        return pd.DataFrame()

    df = pd.DataFrame(result, columns=["date", "sector", "avg_return"])
    df["date"] = pd.to_datetime(df["date"])

    # Pivot: rows=date, cols=sector
    pivot = df.pivot(index="date", columns="sector", values="avg_return")
    return pivot


def compute_sector_correlations(sector_returns: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    """
    Compute rolling correlation matrix between sectors.
    Returns a long-format DataFrame with sector pairs.
    """
    if sector_returns.empty:
        return pd.DataFrame()

    # Use last `window` days
    recent = sector_returns.tail(window).dropna(how="all")

    if recent.shape[0] < 10:
        return pd.DataFrame()

    corr_matrix = recent.corr()
    return corr_matrix


def compute_sector_performance(session: Session) -> pd.DataFrame:
    """
    Compute multi-period performance for each sector.
    """
    as_of = session.execute(text("SELECT MAX(date) FROM daily_prices")).scalar()
    if as_of:
        today = datetime.strptime(str(as_of)[:10], "%Y-%m-%d").date() if isinstance(as_of, str) else as_of
    else:
        today = date.today()

    periods = {
        "1D": 1, "1W": 7, "1M": 30, "3M": 90, "6M": 180, "YTD": (today - date(today.year, 1, 1)).days
    }

    sector_list = session.execute(
        text("SELECT DISTINCT sector FROM stocks WHERE is_active=1")
    ).scalars().all()

    records = []
    for sector in sector_list:
        row = {"sector": sector}
        for period_name, days in periods.items():
            start = (today - timedelta(days=days)).strftime("%Y-%m-%d")
            result = session.execute(text("""
                SELECT AVG(p.daily_return) * :days as period_return
                FROM daily_prices p
                JOIN stocks s ON p.symbol = s.symbol
                WHERE s.sector = :sector AND p.date >= :start AND p.daily_return IS NOT NULL
            """), {"sector": sector, "start": start, "days": days}).scalar()
            row[period_name] = round(result or 0, 2)
        records.append(row)

    return pd.DataFrame(records)


def get_cross_sector_impacts() -> List[Dict]:
    """
    Return the pre-defined and ML-derived cross-sector impact rules.
    Each rule describes how movement in one sector affects another.
    """
    impacts = []
    for (sec_a, sec_b), (direction, lag, description) in SECTOR_CORRELATIONS.items():
        impacts.append({
            "from_sector": sec_a,
            "to_sector": sec_b,
            "direction": direction,       # +1 positive, -1 inverse, 0 neutral
            "lag_days": lag,
            "description": description,
            "impact_type": "DIRECT" if direction == 1 else ("INVERSE" if direction == -1 else "NEUTRAL"),
        })
    return impacts


def detect_sector_rotation(sector_returns: pd.DataFrame) -> Dict:
    """
    Detect sector rotation by comparing recent performance vs longer-term.
    Returns sectors gaining momentum vs losing momentum.
    """
    if sector_returns.empty:
        return {"gaining": [], "losing": [], "neutral": []}

    recent_5d = sector_returns.tail(5).mean()
    recent_20d = sector_returns.tail(20).mean()

    gaining = []
    losing = []
    neutral = []

    for sector in sector_returns.columns:
        short = recent_5d.get(sector, 0) or 0
        longer = recent_20d.get(sector, 0) or 0
        momentum = short - longer

        if momentum > 0.02:
            gaining.append({"sector": sector, "momentum": round(momentum, 3)})
        elif momentum < -0.02:
            losing.append({"sector": sector, "momentum": round(momentum, 3)})
        else:
            neutral.append({"sector": sector, "momentum": round(momentum, 3)})

    # Sort
    gaining = sorted(gaining, key=lambda x: x["momentum"], reverse=True)
    losing = sorted(losing, key=lambda x: x["momentum"])

    return {"gaining": gaining, "losing": losing, "neutral": neutral}


def get_sector_signal(sector: str, session: Session) -> str:
    """
    Aggregate signal for a sector based on individual stock signals.
    """
    result = session.execute(text("""
        SELECT
            SUM(CASE WHEN sig.signal='BUY' THEN 1 ELSE 0 END) as buy_count,
            SUM(CASE WHEN sig.signal='SELL' THEN 1 ELSE 0 END) as sell_count,
            SUM(CASE WHEN sig.signal='WATCH' THEN 1 ELSE 0 END) as watch_count,
            COUNT(*) as total
        FROM signals sig
        JOIN stocks s ON sig.symbol = s.symbol
        WHERE s.sector = :sector
        AND sig.date = (SELECT MAX(date) FROM signals)
    """), {"sector": sector}).fetchone()

    if result is None or result[3] == 0:
        return "WATCH"

    buy_count = result[0] or 0
    sell_count = result[1] or 0
    total = result[3] or 1

    buy_pct = buy_count / total
    sell_pct = sell_count / total

    if buy_pct >= 0.30 and buy_pct > sell_pct:
        return "BUY"
    elif sell_pct >= 0.30 and sell_pct > buy_pct:
        return "SELL"
    return "WATCH"


def compute_and_save_sector_analysis(session: Session):
    """Compute and save sector analysis for today."""
    as_of = session.execute(text("SELECT MAX(date) FROM daily_prices")).scalar()
    if as_of:
        if isinstance(as_of, str):
            today = datetime.strptime(as_of[:10], "%Y-%m-%d").date()
        else:
            today = as_of
    else:
        today = date.today()

    sectors = session.execute(
        text("SELECT DISTINCT sector FROM stocks WHERE is_active=1")
    ).scalars().all()

    for sector in sectors:
        try:
            # Performance metrics
            stats = session.execute(text("""
                SELECT
                    AVG(COALESCE(p.daily_return, (p.close - prev.close) / prev.close)) as daily_ret,
                    COUNT(DISTINCT p.symbol) as total_stocks,
                    SUM(CASE WHEN COALESCE(p.daily_return, (p.close - prev.close) / prev.close) > 0.0005 THEN 1 ELSE 0 END) as stocks_up,
                    SUM(CASE WHEN COALESCE(p.daily_return, (p.close - prev.close) / prev.close) < -0.0005 THEN 1 ELSE 0 END) as stocks_down,
                    SUM(CASE WHEN ABS(COALESCE(p.daily_return, (p.close - prev.close) / prev.close)) <= 0.0005 THEN 1 ELSE 0 END) as stocks_flat
                FROM daily_prices p
                JOIN stocks s ON p.symbol = s.symbol
                LEFT JOIN daily_prices prev ON prev.symbol = p.symbol
                  AND prev.date = (SELECT MAX(d2.date) FROM daily_prices d2 WHERE d2.symbol = p.symbol AND d2.date < p.date)
                WHERE s.sector = :sector AND p.date = :today
            """), {"sector": sector, "today": today.strftime("%Y-%m-%d")}).fetchone()

            # Multi-period returns
            weekly = session.execute(text("""
                SELECT AVG(COALESCE(p.daily_return, (p.close - prev.close) / prev.close)) * 5 * 100.0 FROM daily_prices p
                JOIN stocks s ON p.symbol = s.symbol
                LEFT JOIN daily_prices prev ON prev.symbol = p.symbol
                  AND prev.date = (SELECT MAX(d2.date) FROM daily_prices d2 WHERE d2.symbol = p.symbol AND d2.date < p.date)
                WHERE s.sector = :sector
                AND p.date >= :start
            """), {"sector": sector, "start": (today - timedelta(days=7)).strftime("%Y-%m-%d")}).scalar()

            monthly = session.execute(text("""
                SELECT AVG(COALESCE(p.daily_return, (p.close - prev.close) / prev.close)) * 21 * 100.0 FROM daily_prices p
                JOIN stocks s ON p.symbol = s.symbol
                LEFT JOIN daily_prices prev ON prev.symbol = p.symbol
                  AND prev.date = (SELECT MAX(d2.date) FROM daily_prices d2 WHERE d2.symbol = p.symbol AND d2.date < p.date)
                WHERE s.sector = :sector
                AND p.date >= :start
            """), {"sector": sector, "start": (today - timedelta(days=30)).strftime("%Y-%m-%d")}).scalar()

            # Score stats
            score_stats = session.execute(text("""
                SELECT AVG(cs.composite_score), COUNT(CASE WHEN sig.signal='BUY' THEN 1 END),
                       COUNT(CASE WHEN sig.signal='SELL' THEN 1 END)
                FROM composite_scores cs
                JOIN stocks s ON cs.symbol = s.symbol
                LEFT JOIN signals sig ON cs.symbol = sig.symbol AND cs.date = sig.date
                WHERE s.sector = :sector AND cs.date = :today
            """), {"sector": sector, "today": today.strftime("%Y-%m-%d")}).fetchone()

            sector_signal = get_sector_signal(sector, session)

            if stats:
                total = stats[1] or 1
                raw_daily = float(stats[0] or 0.0)
                # Store as true percentage (e.g. -0.52% instead of -0.0052)
                daily_pct = round(raw_daily * 100.0, 2) if abs(raw_daily) < 0.20 else round(raw_daily, 2)
                sa_data = {
                    "sector": sector,
                    "date": str(today),
                    "daily_return_avg": daily_pct,
                    "weekly_return": round(weekly or 0, 2),
                    "monthly_return": round(monthly or 0, 2),
                    "total_stocks": stats[1] or 0,
                    "stocks_up": stats[2] or 0,
                    "stocks_down": stats[3] or 0,
                    "stocks_unchanged": stats[4] or 0,
                    "advance_decline_ratio": round((stats[2] or 0) / total, 3),
                    "avg_composite_score": round(score_stats[0] or 50, 2) if score_stats else 50.0,
                    "buy_signals_count": score_stats[1] or 0 if score_stats else 0,
                    "sell_signals_count": score_stats[2] or 0 if score_stats else 0,
                    "sector_signal": sector_signal,
                }
                cols = ", ".join(sa_data.keys())
                placeholders = ", ".join(f":{k}" for k in sa_data.keys())
                session.execute(text(f"INSERT OR REPLACE INTO sector_analysis ({cols}) VALUES ({placeholders})"), sa_data)

        except Exception as e:
            session.rollback()
            logger.error(f"Sector analysis failed for {sector}: {e}")

    # Compute correlation matrix
    try:
        sector_returns = get_sector_returns(session, days=90)
        if not sector_returns.empty:
            corr_30 = compute_sector_correlations(sector_returns, window=30)
            corr_90 = compute_sector_correlations(sector_returns, window=90)

            sectors_list = corr_30.columns.tolist()
            for sec_a in sectors_list:
                for sec_b in sectors_list:
                    if sec_a >= sec_b:
                        continue
                    sc_data = {
                        "date": str(today),
                        "sector_a": sec_a,
                        "sector_b": sec_b,
                        "correlation_30d": round(corr_30.loc[sec_a, sec_b] if sec_b in corr_30.columns else 0, 4),
                        "correlation_90d": round(corr_90.loc[sec_a, sec_b] if sec_b in corr_90.columns else 0, 4),
                    }
                    cols = ", ".join(sc_data.keys())
                    placeholders = ", ".join(f":{k}" for k in sc_data.keys())
                    session.execute(text(f"INSERT OR REPLACE INTO sector_correlations ({cols}) VALUES ({placeholders})"), sc_data)
    except Exception as e:
        session.rollback()
        logger.error(f"Correlation computation failed: {e}")

    session.commit()
    logger.info("✅ Sector analysis saved")


def calculate_sector_relative_strength(session: Session) -> Dict[str, Dict]:
    """
    Computes 20-day and 50-day Mansfield Relative Strength for all sectors against NIFTY 50 (^NSEI).
    Classifies each sector into:
      - LEADING:    RS_20d > 0 and RS_50d > 0 (Strong institutional inflows)
      - IMPROVING:  RS_20d > 0 and RS_50d <= 0 (Early turnaround / bottoming)
      - WEAKENING:  RS_20d <= 0 and RS_50d > 0 (Momentum stalling / distribution)
      - LAGGING:    RS_20d <= 0 and RS_50d <= 0 (Chronic underperformance)
    """
    try:
        # Get latest benchmark dates and returns
        nifty_rows = session.execute(text("""
            SELECT date, close FROM index_prices 
            WHERE symbol = '^NSEI' 
            ORDER BY date DESC LIMIT 60
        """)).fetchall()

        nifty_ret_20d = 0.0
        nifty_ret_50d = 0.0
        if len(nifty_rows) >= 20:
            c_latest = float(nifty_rows[0][1])
            c_20 = float(nifty_rows[min(19, len(nifty_rows)-1)][1])
            nifty_ret_20d = (c_latest - c_20) / c_20 * 100.0
            if len(nifty_rows) >= 50:
                c_50 = float(nifty_rows[min(49, len(nifty_rows)-1)][1])
                nifty_ret_50d = (c_latest - c_50) / c_50 * 100.0

        # Query sector performance across active stocks
        sector_perf = session.execute(text("""
            WITH latest_p AS (
                SELECT symbol, close, date,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
                FROM daily_prices
            ),
            p_20 AS (
                SELECT symbol, close
                FROM (
                    SELECT symbol, close,
                           ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
                    FROM daily_prices
                ) WHERE rn = 20
            ),
            p_50 AS (
                SELECT symbol, close
                FROM (
                    SELECT symbol, close,
                           ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
                    FROM daily_prices
                ) WHERE rn = 50
            )
            SELECT s.sector,
                   AVG((lp.close - p20.close) / p20.close * 100.0) as ret_20d,
                   AVG((lp.close - COALESCE(p50.close, p20.close)) / COALESCE(p50.close, p20.close) * 100.0) as ret_50d,
                   COUNT(DISTINCT s.symbol) as stock_count
            FROM stocks s
            JOIN latest_p lp ON s.symbol = lp.symbol AND lp.rn = 1
            JOIN p_20 p20 ON s.symbol = p20.symbol
            LEFT JOIN p_50 p50 ON s.symbol = p50.symbol
            WHERE s.is_active = 1 AND s.sector IS NOT NULL AND s.sector != ''
            GROUP BY s.sector
        """)).fetchall()

        results = {}
        for row in sector_perf:
            sec = str(row[0])
            s_ret_20 = float(row[1] or 0.0)
            s_ret_50 = float(row[2] or 0.0)
            count = int(row[3] or 0)

            rs_20 = round(s_ret_20 - nifty_ret_20d, 2)
            rs_50 = round(s_ret_50 - nifty_ret_50d, 2)

            if rs_20 > 0 and rs_50 > 0:
                classification = "LEADING"
                badge = "🟢 Leading"
                health_score = 90
            elif rs_20 > 0 and rs_50 <= 0:
                classification = "IMPROVING"
                badge = "⚪ Improving"
                health_score = 70
            elif rs_20 <= 0 and rs_50 > 0:
                classification = "WEAKENING"
                badge = "🟡 Weakening"
                health_score = 45
            else:
                classification = "LAGGING"
                badge = "🔴 Lagging"
                health_score = 25

            results[sec] = {
                "sector": sec,
                "classification": classification,
                "badge": badge,
                "health_score": health_score,
                "ret_20d": round(s_ret_20, 2),
                "ret_50d": round(s_ret_50, 2),
                "rs_20d": rs_20,
                "rs_50d": rs_50,
                "stock_count": count,
                "is_gated": bool(classification == "LAGGING" and rs_20 < -2.0)
            }

        return results

    except Exception as e:
        logger.error(f"Failed to calculate sector relative strength: {e}")
        return {}


# Module-level cache for sector relative strength
_SECTOR_RS_CACHE = {}
_SECTOR_RS_TIMESTAMP = None


def get_sector_regime_gate(sector: str, session: Optional[Session] = None) -> Dict:
    """
    Returns gating metadata for a specific sector:
    whether new BUY allocations are approved, RS badge, and alpha friction.
    """
    global _SECTOR_RS_CACHE, _SECTOR_RS_TIMESTAMP
    now = datetime.now()
    if not _SECTOR_RS_CACHE or not _SECTOR_RS_TIMESTAMP or (now - _SECTOR_RS_TIMESTAMP).total_seconds() > 300:
        if session is None:
            session = get_session()
        _SECTOR_RS_CACHE = calculate_sector_relative_strength(session)
        _SECTOR_RS_TIMESTAMP = now

    meta = _SECTOR_RS_CACHE.get(sector, {
        "sector": sector,
        "classification": "IMPROVING",
        "badge": "⚪ Neutral",
        "health_score": 50,
        "rs_20d": 0.0,
        "rs_50d": 0.0,
        "is_gated": False
    })
    return meta

