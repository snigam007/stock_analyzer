"""
Missed Alpha & False Negative Surveillance Engine
- Continuously scans the entire universe (285+ stocks) for uncaught winners (>+4% to +10% moves on WATCH ratings)
- Performs automated quant post-mortems on why high-velocity moves were missed
- Identifies lagging indicators, volume anomalies, and score bottlenecks
"""
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

from db.database import Stock, DailyPrice, Signal, CompositeScore, TechnicalIndicator
from core.candlestick_patterns import get_patterns_for_symbol

logger = logging.getLogger(__name__)


def scan_missed_opportunities(
    session: Session,
    lookback_days: int = 5,
    min_gain_pct: float = 4.0
) -> Dict:
    """
    Scans all active stocks across the universe over the last `lookback_days`.
    Identifies stocks that produced large gains (>= min_gain_pct) despite having a WATCH
    rating or sub-threshold score, and diagnoses the root cause.
    """
    # 1. Get latest available date
    max_d = session.execute(text("SELECT MAX(date) FROM daily_prices")).scalar()
    if not max_d:
        return {"summary": {}, "missed_movers": []}

    # 2. Get price performance over lookback_days
    query = """
        WITH ranked_prices AS (
            SELECT
                symbol, date, close, volume,
                ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
            FROM daily_prices
        ),
        start_and_end AS (
            SELECT
                p_end.symbol,
                p_end.close as end_price,
                p_end.date as end_date,
                p_start.close as start_price,
                p_start.date as start_date,
                p_start.volume as start_volume,
                p_end.volume as end_volume,
                ROUND((p_end.close - p_start.close) / p_start.close * 100.0, 2) as gain_pct
            FROM ranked_prices p_end
            JOIN ranked_prices p_start ON p_end.symbol = p_start.symbol AND p_start.rn = :lb
            WHERE p_end.rn = 1 AND p_start.close > 0
        )
        SELECT
            se.symbol, s.name, s.sector, s.market_cap_tier,
            se.start_price, se.end_price, se.gain_pct, se.start_date, se.end_date,
            se.start_volume, se.end_volume,
            COALESCE(sig.signal, 'WATCH') as start_signal,
            COALESCE(cs.composite_score, 50.0) as start_score,
            ti.rsi_14, ti.adx, ti.macd_hist, ti.ema_50, ti.volume_ratio
        FROM start_and_end se
        JOIN stocks s ON se.symbol = s.symbol
        LEFT JOIN signals sig ON se.symbol = sig.symbol AND sig.date = se.start_date
        LEFT JOIN composite_scores cs ON se.symbol = cs.symbol AND cs.date = se.start_date
        LEFT JOIN technical_indicators ti ON se.symbol = ti.symbol AND ti.date = se.start_date
        WHERE se.gain_pct >= :min_gain AND s.is_active = 1
        ORDER BY se.gain_pct DESC
    """
    rows = session.execute(text(query), {"lb": lookback_days, "min_gain": min_gain_pct}).fetchall()

    missed_movers = []
    caught_movers = []
    bottleneck_counts = {}

    for r in rows:
        sym = r[0]
        name = r[1]
        sector = r[2]
        tier = r[3] or "Mid"
        start_p = float(r[4] or 0)
        end_p = float(r[5] or 0)
        gain = float(r[6] or 0)
        st_date = str(r[7])
        end_date = str(r[8])
        sig = r[11] or "WATCH"
        score = float(r[12] or 50.0)
        rsi = float(r[13] or 50.0) if r[13] is not None else 50.0
        adx = float(r[14] or 20.0) if r[14] is not None else 20.0
        macd_h = float(r[15] or 0.0) if r[15] is not None else 0.0
        ema_50 = float(r[16] or 0.0) if r[16] is not None else 0.0
        vol_ratio = float(r[17] or 1.0) if r[17] is not None else 1.0

        # Check if BUY was triggered on Day 0 OR during the incubation window
        was_caught = (sig == "BUY")
        if not was_caught:
            incubation_buys = session.execute(text("""
                SELECT COUNT(*) FROM signals
                WHERE symbol = :s AND signal = 'BUY' AND date >= :st AND date <= :en
            """), {"s": sym, "st": st_date, "en": end_date}).scalar()
            if incubation_buys and incubation_buys > 0:
                was_caught = True

        item = {
            "symbol": sym, "name": name, "sector": sector, "tier": tier,
            "start_price": start_p, "end_price": end_p, "gain_pct": gain,
            "start_signal": sig, "start_score": score,
            "rsi": rsi, "adx": adx, "vol_ratio": vol_ratio,
        }

        if was_caught:
            caught_movers.append(item)
            continue

        # ── Automated Quant Post-Mortem Diagnosis ─────────────────────────────
        reasons = []
        bottleneck = "Score Calibration"

        if score < 56.0:
            reasons.append(f"Sub-threshold composite score ({score:.1f}/100)")
        if rsi < 48.0:
            reasons.append(f"RSI was sluggish ({rsi:.1f}) prior to sudden surge")
            bottleneck = "RSI Momentum Lag"
        elif rsi > 68.0 and adx < 22.0:
            reasons.append("Filtered by Chop Guard (RSI > 68 in low ADX)")
            bottleneck = "ADX Chop Guard"

        if vol_ratio < 1.0:
            reasons.append(f"Dry pre-breakout volume ({vol_ratio:.2f}x avg)")
            bottleneck = "Volume Pre-Breakout Dryness"

        if ema_50 and start_p < ema_50:
            reasons.append("Was trading below 50 EMA (mean reversion bounce)")
            bottleneck = "Below 50 EMA Filter"

        if not reasons:
            reasons.append(f"Composite score ({score:.1f}) was within WATCH band (50-59)")

        # Check for candlestick catalyst
        pats = get_patterns_for_symbol(sym, session, limit=3)
        pat_str = f"Formed {pats[0]['pattern_name']}" if pats else "No early pattern"

        item["bottleneck"] = bottleneck
        item["diagnosis"] = " • ".join(reasons)
        item["pattern_catalyst"] = pat_str
        item["actionable_takeaway"] = (
            "Monitor volume expansion early on Day 1" if "Volume" in bottleneck else (
                "Allow mean-reversion setups when Piotroski >= 7" if "EMA" in bottleneck else
                "Incorporate intraday momentum trigger"
            )
        )

        bottleneck_counts[bottleneck] = bottleneck_counts.get(bottleneck, 0) + 1
        missed_movers.append(item)

    top_bottleneck = max(bottleneck_counts.items(), key=lambda x: x[1])[0] if bottleneck_counts else "None"
    avg_missed_gain = np.mean([m["gain_pct"] for m in missed_movers]) if missed_movers else 0.0

    summary = {
        "total_movers_detected": len(rows),
        "caught_buyers": len(caught_movers),
        "missed_movers_count": len(missed_movers),
        "capture_rate_pct": round(len(caught_movers) / max(1, len(rows)) * 100, 1),
        "avg_missed_gain_pct": round(avg_missed_gain, 2),
        "top_bottleneck_factor": top_bottleneck,
        "lookback_days": lookback_days,
        "min_gain_pct": min_gain_pct,
    }

    return {
        "summary": summary,
        "missed_movers": missed_movers,
        "caught_movers": caught_movers,
    }
