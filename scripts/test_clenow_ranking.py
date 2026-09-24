"""
scripts/test_clenow_ranking.py
Test Andreas Clenow Exponential Trend Smoothness (R^2 * Slope) vs simple 6M Momentum.
"""

import sys
from pathlib import Path
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import math
import numpy as np
import pandas as pd
from db.database import get_global_engine, get_session
from sqlalchemy import text


def compute_clenow_momentum(prices: pd.Series) -> float:
    """Computes Clenow Score = Annualized Exponential Slope * R^2."""
    if len(prices) < 60:
        return 0.0
    p = prices.dropna()
    if len(p) < 60 or (p <= 0).any():
        return 0.0

    y = np.log(p.values)
    x = np.arange(len(y))

    # Linear regression on log prices: y = alpha + beta * x
    cov = np.cov(x, y)
    var_x = cov[0, 0]
    cov_xy = cov[0, 1]
    if var_x < 1e-6:
        return 0.0

    beta = cov_xy / var_x
    # R^2
    corr = np.corrcoef(x, y)[0, 1]
    r_squared = float(corr ** 2) if not np.isnan(corr) else 0.0

    # Annualized slope
    annualized_slope = (math.exp(beta * 252.0) - 1.0) * 100.0

    # Clenow score
    return annualized_slope * r_squared


def main():
    engine = get_global_engine()
    session = get_session(engine)

    print("=" * 70)
    print("🔬 TESTING ANDREAS CLENOW EXPONENTIAL TREND SMOOTHNESS (R² × SLOPE)")
    print("=" * 70)

    # Fetch 1-year daily prices for active stocks
    query = text("""
        SELECT symbol, date, close FROM daily_prices
        WHERE date >= '2023-01-01' AND close > 0
        ORDER BY symbol, date ASC
    """)
    df = pd.read_sql_query(query, session.bind)
    session.close()

    print(f"Total price rows loaded: {len(df):,}")
    symbols = df["symbol"].unique()
    print(f"Total distinct symbols: {len(symbols)}")

    results = []
    for sym in symbols:
        sub = df[df["symbol"] == sym].sort_values("date")
        if len(sub) >= 90:
            p_series = sub["close"]
            clenow = compute_clenow_momentum(p_series.tail(126))
            ret_6m = (p_series.iloc[-1] - p_series.iloc[-126]) / p_series.iloc[-126] * 100.0 if len(p_series) >= 126 else 0.0
            results.append({
                "symbol": sym,
                "ret_6m_pct": round(ret_6m, 1),
                "clenow_score": round(clenow, 2),
                "last_price": round(p_series.iloc[-1], 2)
            })

    res_df = pd.DataFrame(results)
    print("\n--- TOP 10 BY RAW 6M RETURN ---")
    print(res_df.sort_values("ret_6m_pct", ascending=False).head(10).to_string(index=False))

    print("\n--- TOP 10 BY CLENOW SMOOTH MOMENTUM (R² × SLOPE) ---")
    print(res_df.sort_values("clenow_score", ascending=False).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
