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


_CREATE_MISSED_ALPHA_AUDIT_TABLE = """
    CREATE TABLE IF NOT EXISTS missed_alpha_audit_log (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_date          TEXT NOT NULL,
        symbol              TEXT NOT NULL,
        name                TEXT,
        sector              TEXT,
        tier                TEXT,
        start_date          TEXT,
        end_date            TEXT,
        gain_pct            REAL,
        start_price         REAL,
        end_price           REAL,
        start_signal        TEXT,
        start_score         REAL,
        was_caught          INTEGER,
        bottleneck          TEXT,
        diagnosis           TEXT,
        pattern_catalyst    TEXT,
        actionable_takeaway TEXT,
        UNIQUE(audit_date, symbol, start_date)
    )
"""


def init_missed_alpha_audit_table(session: Session) -> None:
    """Ensure missed_alpha_audit_log table exists."""
    session.execute(text(_CREATE_MISSED_ALPHA_AUDIT_TABLE))
    session.commit()


def log_daily_missed_alpha_audit(
    session: Session,
    lookback_days: int = 5,
    min_gain_pct: float = 4.0
) -> Dict:
    """
    Logs today's Missed Alpha & False Negative Surveillance snapshot into persistent audit table.
    Snapshots both caught movers (True Positives) and missed movers (False Negatives).
    """
    init_missed_alpha_audit_table(session)
    res = scan_missed_opportunities(session, lookback_days=lookback_days, min_gain_pct=min_gain_pct)
    today_str = date.today().isoformat()
    inserted = 0

    # 1. Log Missed Movers (False Negatives)
    for m in res.get("missed_movers", []):
        try:
            session.execute(text("""
                INSERT OR IGNORE INTO missed_alpha_audit_log
                    (audit_date, symbol, name, sector, tier, start_date, end_date,
                     gain_pct, start_price, end_price, start_signal, start_score,
                     was_caught, bottleneck, diagnosis, pattern_catalyst, actionable_takeaway)
                VALUES
                    (:ad, :sym, :name, :sec, :tier, :sd, :ed,
                     :gain, :sp, :ep, :sig, :sc,
                     0, :btn, :diag, :pat, :act)
            """), {
                "ad": today_str, "sym": m["symbol"], "name": m.get("name", m["symbol"]),
                "sec": m.get("sector", "General"), "tier": m.get("tier", "Mid"),
                "sd": m.get("start_date", today_str), "ed": m.get("end_date", today_str),
                "gain": m.get("gain_pct", 0.0), "sp": m.get("start_price", 0.0), "ep": m.get("end_price", 0.0),
                "sig": m.get("start_signal", "WATCH"), "sc": m.get("start_score", 50.0),
                "btn": m.get("bottleneck", "Score Calibration"),
                "diag": m.get("diagnosis", ""), "pat": m.get("pattern_catalyst", ""),
                "act": m.get("actionable_takeaway", "")
            })
            inserted += 1
        except Exception:
            continue

    # 2. Log Caught Movers (True Positives)
    for c in res.get("caught_movers", []):
        try:
            session.execute(text("""
                INSERT OR IGNORE INTO missed_alpha_audit_log
                    (audit_date, symbol, name, sector, tier, start_date, end_date,
                     gain_pct, start_price, end_price, start_signal, start_score,
                     was_caught, bottleneck, diagnosis, pattern_catalyst, actionable_takeaway)
                VALUES
                    (:ad, :sym, :name, :sec, :tier, :sd, :ed,
                     :gain, :sp, :ep, 'BUY', :sc,
                     1, 'NONE', 'Successfully caught by engine BUY signal', 'Catalyst Confirmed', 'Alpha Captured')
            """), {
                "ad": today_str, "sym": c["symbol"], "name": c.get("name", c["symbol"]),
                "sec": c.get("sector", "General"), "tier": c.get("tier", "Mid"),
                "sd": c.get("start_date", today_str), "ed": c.get("end_date", today_str),
                "gain": c.get("gain_pct", 0.0), "sp": c.get("start_price", 0.0), "ep": c.get("end_price", 0.0),
                "sc": c.get("start_score", 65.0)
            })
            inserted += 1
        except Exception:
            continue

    session.commit()
    return {
        "audit_date": today_str,
        "new_records_logged": inserted,
        "total_movers": res["summary"].get("total_movers_detected", 0),
        "caught_count": res["summary"].get("caught_buyers", 0),
        "missed_count": res["summary"].get("missed_movers_count", 0),
        "capture_rate_pct": res["summary"].get("capture_rate_pct", 0.0),
        "top_bottleneck": res["summary"].get("top_bottleneck_factor", "None")
    }


def evaluate_missed_alpha_audit_accuracy(
    session: Session,
    days: int = 60
) -> Dict:
    """
    Computes rigorous statistical audit and accuracy analysis of False Negatives (Missed Alpha):
      - Capture Rate (True Positive %) vs False Negative Rate (%)
      - Total & Average Alpha Missed (%)
      - Bottleneck Factor Distribution (Why signals were missed)
      - Sectoral Vulnerability Concentration
      - Actionable Algorithmic Calibration Insights
    """
    init_missed_alpha_audit_table(session)
    since_date = (date.today() - timedelta(days=days)).isoformat()

    rows = session.execute(text("""
        SELECT symbol, name, sector, tier, gain_pct, start_signal, start_score,
               was_caught, bottleneck, diagnosis, pattern_catalyst, actionable_takeaway,
               audit_date
        FROM missed_alpha_audit_log
        WHERE audit_date >= :since
        ORDER BY audit_date DESC, gain_pct DESC
    """), {"since": since_date}).fetchall()

    if not rows:
        # If no audit records exist yet, seed with current scan
        log_daily_missed_alpha_audit(session)
        rows = session.execute(text("""
            SELECT symbol, name, sector, tier, gain_pct, start_signal, start_score,
                   was_caught, bottleneck, diagnosis, pattern_catalyst, actionable_takeaway,
                   audit_date
            FROM missed_alpha_audit_log
            ORDER BY audit_date DESC, gain_pct DESC
        """)).fetchall()

    cols = [
        "symbol", "name", "sector", "tier", "gain_pct", "start_signal", "start_score",
        "was_caught", "bottleneck", "diagnosis", "pattern_catalyst", "actionable_takeaway",
        "audit_date"
    ]
    df = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)

    if df.empty:
        return {
            "total_movers": 0, "total_caught": 0, "total_missed": 0,
            "capture_rate_pct": 0.0, "false_negative_rate_pct": 0.0,
            "avg_missed_gain_pct": 0.0, "total_missed_alpha_pct": 0.0,
            "bottleneck_distribution": {}, "sector_distribution": {},
            "quant_insights": ["No mover audit records found."], "df": df
        }

    total_movers = len(df)
    caught_df = df[df["was_caught"] == 1]
    missed_df = df[df["was_caught"] == 0]

    total_caught = len(caught_df)
    total_missed = len(missed_df)

    capture_rate = round(total_caught / max(1, total_movers) * 100.0, 1)
    fn_rate = round(total_missed / max(1, total_movers) * 100.0, 1)

    avg_missed_gain = round(missed_df["gain_pct"].mean(), 2) if not missed_df.empty else 0.0
    total_missed_alpha = round(missed_df["gain_pct"].sum(), 2) if not missed_df.empty else 0.0

    # Bottleneck counts
    bottleneck_dist = {}
    if not missed_df.empty:
        for btn, grp in missed_df.groupby("bottleneck"):
            bottleneck_dist[btn] = {
                "count": len(grp),
                "pct_of_missed": round(len(grp) / max(1, total_missed) * 100.0, 1),
                "avg_gain": round(grp["gain_pct"].mean(), 2)
            }

    # Sector distribution of missed moves
    sector_dist = {}
    if not missed_df.empty:
        for sec, grp in missed_df.groupby("sector"):
            sector_dist[sec] = len(grp)

    # Automated Quant Calibration Insights
    insights = []
    if total_missed > 0:
        top_btn = max(bottleneck_dist.items(), key=lambda x: x[1]["count"])[0] if bottleneck_dist else "None"
        insights.append(
            f"🔍 **Dominant Bottleneck:** '{top_btn}' accounted for {bottleneck_dist.get(top_btn, {}).get('pct_of_missed', 0)}% of all uncaught movers."
        )
        if "Volume" in top_btn:
            insights.append(
                "💡 **Volume Threshold Calibration:** Early stage multi-day breakouts often exhibit dry pre-breakout contraction. Relax volume expansion hurdles when multi-session Volatility Contraction (VCP) or bullish candlestick formations are present."
            )
        elif "RSI" in top_btn:
            insights.append(
                "💡 **Momentum Filter Tuning:** Stocks emerging from multi-week bases frequently start with neutral RSI (45-52). Introducing intraday breakout triggers or 10-day price momentum will capture moves 1-2 sessions earlier."
            )
        elif "EMA" in top_btn:
            insights.append(
                "💡 **Mean-Reversion Gate:** High Piotroski score (>7/9) stocks bouncing off 200 EMA support were filtered out by the 50 EMA barrier. Allowing contrarian quality reversals captures sharp turnaround alpha."
            )

        top_sector = max(sector_dist.items(), key=lambda x: x[1])[0] if sector_dist else "General"
        insights.append(
            f"🏭 **Sector Vulnerability:** Sector '{top_sector}' registered the highest false negatives ({sector_dist.get(top_sector, 0)} movers). Consider sector-relative RS thresholds rather than absolute market thresholds."
        )
    else:
        insights.append("✅ **Pristine Capture:** Engine capture rate is 100% with zero false negatives recorded in this horizon.")

    return {
        "total_movers": total_movers,
        "total_caught": total_caught,
        "total_missed": total_missed,
        "capture_rate_pct": capture_rate,
        "false_negative_rate_pct": fn_rate,
        "avg_missed_gain_pct": avg_missed_gain,
        "total_missed_alpha_pct": total_missed_alpha,
        "bottleneck_distribution": bottleneck_dist,
        "sector_distribution": sector_dist,
        "quant_insights": insights,
        "df": df,
    }

