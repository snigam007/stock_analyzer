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
    start_date = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")

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
                    AVG(p.daily_return) as daily_ret,
                    COUNT(DISTINCT p.symbol) as total_stocks,
                    SUM(CASE WHEN p.daily_return > 0 THEN 1 ELSE 0 END) as stocks_up,
                    SUM(CASE WHEN p.daily_return < 0 THEN 1 ELSE 0 END) as stocks_down,
                    SUM(CASE WHEN p.daily_return = 0 THEN 1 ELSE 0 END) as stocks_flat
                FROM daily_prices p
                JOIN stocks s ON p.symbol = s.symbol
                WHERE s.sector = :sector AND p.date = :today
            """), {"sector": sector, "today": today.strftime("%Y-%m-%d")}).fetchone()

            # Multi-period returns
            weekly = session.execute(text("""
                SELECT AVG(p.daily_return) * 5 FROM daily_prices p
                JOIN stocks s ON p.symbol = s.symbol
                WHERE s.sector = :sector
                AND p.date >= :start
            """), {"sector": sector, "start": (today - timedelta(days=7)).strftime("%Y-%m-%d")}).scalar()

            monthly = session.execute(text("""
                SELECT AVG(p.daily_return) * 21 FROM daily_prices p
                JOIN stocks s ON p.symbol = s.symbol
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
                sa_data = {
                    "sector": sector,
                    "date": str(today),
                    "daily_return_avg": round(stats[0] or 0, 3),
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
