import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.database import get_global_engine, get_session
from sqlalchemy import text
from datetime import datetime, timedelta
import pandas as pd
import math

engine = get_global_engine()
session = get_session(engine)

# Load metadata
stocks_meta = session.execute(text("SELECT symbol, name, sector, market_cap_tier FROM stocks WHERE is_active = 1")).fetchall()
stock_sector_map = {r[0]: (r[1] or r[0], r[2] or "General") for r in stocks_meta}
stock_meta_map = {r[0]: {"name": r[1] or r[0], "sector": r[2] or "General", "tier": (r[3] or "mid").lower()} for r in stocks_meta}
beta_rows = session.execute(text("SELECT symbol, AVG(beta) FROM composite_scores GROUP BY symbol")).fetchall()
stock_beta_map = {r[0]: float(r[1]) if r[1] is not None else 1.0 for r in beta_rows}

print("Metadata loaded. Testing query with 6M and 3M momentum...")

# Test candidate selection for a sample date (e.g. 2024-01-02)
sample_date = "2024-01-02"
past_180d = "2023-07-06"
past_90d = "2023-10-04"

q = f"""
    SELECT dp.symbol, dp.close,
           (dp.close - dp_6m.close) / dp_6m.close as ret_6m,
           (dp.close - dp_3m.close) / dp_3m.close as ret_3m
    FROM daily_prices dp
    JOIN daily_prices dp_6m ON dp.symbol = dp_6m.symbol
    JOIN daily_prices dp_3m ON dp.symbol = dp_3m.symbol
    WHERE dp.date = '{sample_date}'
    AND dp_6m.date = (SELECT MIN(date) FROM daily_prices WHERE date >= '{past_180d}')
    AND dp_3m.date = (SELECT MIN(date) FROM daily_prices WHERE date >= '{past_90d}')
    AND dp.close BETWEEN 70.0 AND 10000.0
    ORDER BY ( (dp.close - dp_6m.close)/dp_6m.close * 0.6 + (dp.close - dp_3m.close)/dp_3m.close * 0.4 ) DESC
    LIMIT 30
"""
rows = session.execute(text(q)).fetchall()
print(f"Sample candidates on {sample_date}: {len(rows)}")
for r in rows[:5]:
    sym = r[0]
    tier = stock_meta_map.get(sym, {}).get("tier", "mid")
    beta = stock_beta_map.get(sym, 1.0)
    print(f"  {sym} ({tier}, beta={beta:.2f}): close={r[1]:.1f}, 6M={r[2]*100:+.1f}%, 3M={r[3]*100:+.1f}%")

session.close()
