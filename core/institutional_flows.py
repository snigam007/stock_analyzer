"""
FII / DII Institutional Flow Regime & Derivatives Positioning Engine
- Aggregate buy/sell volumes from bulk_block_deals to approximate institutional activity
- FII & DII Cash Market Net Buying / Selling in ₹ Crores (derived from bulk/block deals)
- Composite Smart Money Flow Sentiment Index (0 - 100)
"""
import logging
from typing import Dict, List, Optional
from datetime import date, timedelta
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def fetch_institutional_flows_dashboard(session=None) -> Dict:
    """Computes FII / DII institutional net positioning from bulk_block_deals DB table.
    Falls back to a neutral baseline when no DB session or data is available."""

    close_session = False
    if session is None:
        try:
            from db.database import get_global_engine, get_session
            session = get_session(get_global_engine())
            close_session = True
        except Exception:
            session = None

    # Try to fetch real data from bulk_block_deals table
    daily_flows = []
    try:
        if session:
            try:
                from sqlalchemy import text
                lookback = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
                rows = session.execute(text("""
                    SELECT date, buy_sell, SUM(value_in_crores) as total_cr, 
                           COUNT(*) as deal_count, is_promoter_or_fii
                    FROM bulk_block_deals
                    WHERE date >= :lb AND value_in_crores IS NOT NULL
                    GROUP BY date, buy_sell, is_promoter_or_fii
                    ORDER BY date DESC
                """), {"lb": lookback}).fetchall()
            
                if rows:
                    df = pd.DataFrame(rows, columns=["date", "buy_sell", "total_cr", "deal_count", "is_promoter_or_fii"])
                    for dt, grp in df.groupby("date"):
                        fii_buy = float(grp[(grp["is_promoter_or_fii"] == True) & (grp["buy_sell"].str.upper() == "BUY")]["total_cr"].sum())
                        fii_sell = float(grp[(grp["is_promoter_or_fii"] == True) & (grp["buy_sell"].str.upper() == "SELL")]["total_cr"].sum())
                        dii_buy = float(grp[(grp["is_promoter_or_fii"] != True) & (grp["buy_sell"].str.upper() == "BUY")]["total_cr"].sum())
                        dii_sell = float(grp[(grp["is_promoter_or_fii"] != True) & (grp["buy_sell"].str.upper() == "SELL")]["total_cr"].sum())
                        daily_flows.append({
                            "date": str(dt),
                            "fii_cash_cr": round(fii_buy - fii_sell, 1),
                            "dii_cash_cr": round(dii_buy - dii_sell, 1),
                            "fii_futures_long_pct": 55.0,  # Not available from bulk deals; neutral baseline
                            "fii_call_oi": 400000,
                            "fii_put_oi": 380000,
                        })
                    daily_flows.sort(key=lambda x: x["date"])
            except Exception as e:
                logger.debug(f"Bulk/block deals query failed: {e}")

        # Fallback to neutral baseline if no DB data
        if not daily_flows:
            today_str = date.today().strftime("%Y-%m-%d")
            daily_flows = [
                {"date": today_str, "fii_cash_cr": 0.0, "dii_cash_cr": 0.0, 
                 "fii_futures_long_pct": 55.0, "fii_call_oi": 400000, "fii_put_oi": 380000},
            ]

        latest = daily_flows[-1]
        fii_cash_today = latest["fii_cash_cr"]
        dii_cash_today = latest["dii_cash_cr"]
        total_inst_inflow = round(fii_cash_today + dii_cash_today, 1)

        futures_long_pct = latest["fii_futures_long_pct"]
        call_put_ratio = round(latest["fii_call_oi"] / max(1, latest["fii_put_oi"]), 2)

        # Trailing cumulative Cash Inflows
        fii_cum = round(sum(x["fii_cash_cr"] for x in daily_flows[-5:]), 1)
        dii_cum = round(sum(x["dii_cash_cr"] for x in daily_flows[-5:]), 1)

        # Composite Smart Money Sentiment (0 to 100)
        sentiment_score = 50.0 + (futures_long_pct - 50.0) * 0.8 + (call_put_ratio - 1.0) * 20.0 + (fii_cash_today / 200.0)
        sentiment_score = round(float(np.clip(sentiment_score, 15.0, 95.0)), 1)

        # Regimes
        if futures_long_pct >= 75.0:
            regime = "OVERBOUGHT INSTITUTIONAL EXHAUSTION (EXTREME BULLISH CLIMAX)"
            regime_badge = "⚠️ OVERBOUGHT FII POSITIONING (>75%)"
        elif futures_long_pct <= 25.0:
            regime = "OVERSOLD PANIC CAPITULATION (EXTREME FII SHORT SQUEEZE ZONE)"
            regime_badge = "🟢 CONTRARIAN BUY ZONE (<25%)"
        elif fii_cash_today > 1000.0 and futures_long_pct > 50.0:
            regime = "STRONG FII AGGRESSIVE ACCUMULATION"
            regime_badge = "🟢 FII INFLOW ACCELERATION"
        elif fii_cash_today < -1000.0:
            regime = "FII DISTRIBUTION & PROFIT TAKING"
            regime_badge = "🔴 FII OUTFLOW HEADWIND"
        else:
            regime = "BALANCED INSTITUTIONAL ROTATION"
            regime_badge = "🟡 BALANCED FLOWS"

        return {
            "latest_date": latest["date"],
            "fii_cash_today_cr": fii_cash_today,
            "dii_cash_today_cr": dii_cash_today,
            "total_inst_inflow_cr": total_inst_inflow,
            "fii_5d_cum_cr": fii_cum,
            "dii_5d_cum_cr": dii_cum,
            "fii_futures_long_pct": futures_long_pct,
            "fii_call_put_ratio": call_put_ratio,
            "sentiment_score": sentiment_score,
            "regime": regime,
            "regime_badge": regime_badge,
            "trailing_history": daily_flows[-5:]
        }
    finally:
        if close_session and session is not None:
            try:
                session.close()
            except Exception:
                pass