"""
Relative Rotation Graphs (RRG) & Sector Money Flow Matrix (JdK Method)
- Computes normalized RS-Ratio and RS-Momentum benchmarked against NIFTY 50 (^NSEI)
- Categorizes Indian Sectors into 4 Dynamic Quadrants:
  🟢 Leading (Top Right), 🟡 Weakening (Bottom Right), 🔴 Lagging (Bottom Left), 🔵 Improving (Top Left)
- Computes historical rotation tails to detect early institutional capital shifts
"""
import logging
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


def compute_sector_rrg_matrix(session: Session, lookback_weeks: int = 14) -> Dict:
    """
    Computes JdK Relative Rotation Graph (RRG) matrix for all Indian market sectors
    benchmarked against NIFTY 50 (^NSEI).
    """
    # 1. Fetch benchmark (NIFTY 50) prices
    nifty_rows = session.execute(text("""
        SELECT date, close FROM index_prices
        WHERE symbol = '^NSEI' AND close IS NOT NULL
        ORDER BY date DESC LIMIT :lim
    """), {"lim": lookback_weeks * 7}).fetchall()

    if not nifty_rows or len(nifty_rows) < 20:
        return {"error": "Insufficient benchmark NIFTY 50 data."}

    df_nifty = pd.DataFrame(nifty_rows, columns=["date", "benchmark_close"]).sort_values("date").reset_index(drop=True)
    df_nifty["date"] = pd.to_datetime(df_nifty["date"])
    df_nifty["benchmark_close"] = df_nifty["benchmark_close"].astype(float)

    # 2. Fetch distinct sectors
    sectors = session.execute(text("""
        SELECT DISTINCT sector FROM stocks WHERE is_active=1 AND sector IS NOT NULL
    """)).fetchall()

    sector_results = []

    for (sec_name,) in sectors:
        # Fetch aggregated daily average price for this sector
        sec_rows = session.execute(text("""
            SELECT dp.date, AVG(dp.close) as sec_close
            FROM daily_prices dp
            JOIN stocks s ON dp.symbol = s.symbol
            WHERE s.sector = :sec AND dp.close IS NOT NULL
            GROUP BY dp.date
            ORDER BY dp.date DESC LIMIT :lim
        """), {"sec": sec_name, "lim": lookback_weeks * 7}).fetchall()

        if len(sec_rows) < 20:
            continue

        df_sec = pd.DataFrame(sec_rows, columns=["date", "sec_close"]).sort_values("date").reset_index(drop=True)
        df_sec["date"] = pd.to_datetime(df_sec["date"])
        df_sec["sec_close"] = df_sec["sec_close"].astype(float)

        # Merge with NIFTY
        merged = pd.merge(df_sec, df_nifty, on="date", how="inner").sort_values("date").reset_index(drop=True)
        if len(merged) < 15:
            continue

        # 3. JdK Relative Strength calculations
        # Raw RS = Sector Price / Benchmark Price
        merged["raw_rs"] = (merged["sec_close"] / merged["benchmark_close"]) * 1000.0

        # RS-Ratio = 10-period normalized moving average of Raw RS
        rs_mean = merged["raw_rs"].rolling(window=10, min_periods=5).mean()
        rs_std = merged["raw_rs"].rolling(window=10, min_periods=5).std().replace(0, 1.0)
        merged["rs_ratio"] = 100.0 + ((merged["raw_rs"] - rs_mean) / rs_std) * 2.5

        # RS-Momentum = 5-period ROC of RS-Ratio
        merged["rs_momentum"] = 100.0 + (merged["rs_ratio"] - merged["rs_ratio"].shift(5)) * 1.5
        merged = merged.dropna().reset_index(drop=True)

        if len(merged) < 4:
            continue

        curr = merged.iloc[-1]
        rs_r = round(float(curr["rs_ratio"]), 2)
        rs_m = round(float(curr["rs_momentum"]), 2)

        # Determine Quadrant
        if rs_r >= 100.0 and rs_m >= 100.0:
            quadrant = "🟢 Leading"
            quad_color = "#00c875"
            advice = "Overweight / Institutional Leader"
        elif rs_r >= 100.0 and rs_m < 100.0:
            quadrant = "🟡 Weakening"
            quad_color = "#f0a500"
            advice = "Take Partial Profits / Momentum Fading"
        elif rs_r < 100.0 and rs_m < 100.0:
            quadrant = "🔴 Lagging"
            quad_color = "#ff4b4b"
            advice = "Underweight / Lacks Momentum"
        else:
            quadrant = "🔵 Improving"
            quad_color = "#00a8ff"
            advice = "Accumulate Early / Emerging Strength"

        # Extract 4-point historical tail trajectory for trail rendering
        tail_points = []
        step = max(1, len(merged) // 5)
        for idx in range(max(0, len(merged) - 4 * step), len(merged), step):
            tail_points.append({
                "date": merged["date"].iloc[idx].strftime("%Y-%m-%d"),
                "rs_ratio": round(float(merged["rs_ratio"].iloc[idx]), 2),
                "rs_momentum": round(float(merged["rs_momentum"].iloc[idx]), 2),
            })

        sector_results.append({
            "sector": sec_name,
            "rs_ratio": rs_r,
            "rs_momentum": rs_m,
            "quadrant": quadrant,
            "quad_color": quad_color,
            "advice": advice,
            "tail": tail_points,
        })

    return {
        "benchmark": "NIFTY 50 (^NSEI)",
        "total_sectors": len(sector_results),
        "sectors": sorted(sector_results, key=lambda x: x["rs_ratio"], reverse=True),
    }