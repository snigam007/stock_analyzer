"""
FII / DII Institutional Flow Regime & Derivatives Positioning Engine
- FII & DII Cash Market Net Buying / Selling in ₹ Crores
- FII Index Futures Long / Short Exposure Ratio
- FII Call vs Put Options Net Open Interest Positioning
- Composite Smart Money Flow Sentiment Index (0 - 100)
"""
import logging
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Sample realistic trailing institutional flow data
INSTITUTIONAL_DAILY_FLOWS = [
    {"date": "2026-08-20", "fii_cash_cr": +1840.5, "dii_cash_cr": +2150.2, "fii_futures_long_pct": 54.2, "fii_call_oi": 420000, "fii_put_oi": 380000},
    {"date": "2026-08-21", "fii_cash_cr": +920.0, "dii_cash_cr": +1480.0, "fii_futures_long_pct": 56.8, "fii_call_oi": 445000, "fii_put_oi": 370000},
    {"date": "2026-08-24", "fii_cash_cr": -450.2, "dii_cash_cr": +1920.5, "fii_futures_long_pct": 53.4, "fii_call_oi": 430000, "fii_put_oi": 395000},
    {"date": "2026-08-25", "fii_cash_cr": +2310.8, "dii_cash_cr": +850.4, "fii_futures_long_pct": 59.1, "fii_call_oi": 480000, "fii_put_oi": 360000},
    {"date": "2026-08-26", "fii_cash_cr": +3140.0, "dii_cash_cr": +1120.0, "fii_futures_long_pct": 63.5, "fii_call_oi": 520000, "fii_put_oi": 340000},
]


def fetch_institutional_flows_dashboard() -> Dict:
    """Computes FII / DII institutional net positioning and flow momentum."""
    latest = INSTITUTIONAL_DAILY_FLOWS[-1]
    fii_cash_today = latest["fii_cash_cr"]
    dii_cash_today = latest["dii_cash_cr"]
    total_inst_inflow = round(fii_cash_today + dii_cash_today, 1)

    futures_long_pct = latest["fii_futures_long_pct"]
    call_put_ratio = round(latest["fii_call_oi"] / max(1, latest["fii_put_oi"]), 2)

    # 5-Day Cumulative Cash Inflows
    fii_5d_cum = round(sum(x["fii_cash_cr"] for x in INSTITUTIONAL_DAILY_FLOWS), 1)
    dii_5d_cum = round(sum(x["dii_cash_cr"] for x in INSTITUTIONAL_DAILY_FLOWS), 1)

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
        "fii_5d_cum_cr": fii_5d_cum,
        "dii_5d_cum_cr": dii_5d_cum,
        "fii_futures_long_pct": futures_long_pct,
        "fii_call_put_ratio": call_put_ratio,
        "sentiment_score": sentiment_score,
        "regime": regime,
        "regime_badge": regime_badge,
        "trailing_history": INSTITUTIONAL_DAILY_FLOWS
    }