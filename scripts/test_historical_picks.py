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

# Load stocks meta and beta map
stocks_meta = session.execute(text("SELECT symbol, name, sector, market_cap_tier FROM stocks WHERE is_active = 1")).fetchall()
stock_sector_map = {r[0]: (r[1] or r[0], r[2] or "General") for r in stocks_meta}
stock_meta_map = {r[0]: {"name": r[1] or r[0], "sector": r[2] or "General", "tier": (r[3] or "mid").lower()} for r in stocks_meta}
beta_rows = session.execute(text("SELECT symbol, AVG(beta) FROM composite_scores GROUP BY symbol")).fetchall()
stock_beta_map = {r[0]: float(r[1]) if r[1] is not None else 1.0 for r in beta_rows}

print("Testing candidate query and ranking across 5 random historical dates...")
sample_dates = ["2022-01-03", "2023-01-02", "2023-06-01", "2024-01-02", "2024-06-03"]

for sd in sample_dates:
    p_180 = (datetime.strptime(sd, "%Y-%m-%d").date() - timedelta(days=180)).strftime("%Y-%m-%d")
    p_90 = (datetime.strptime(sd, "%Y-%m-%d").date() - timedelta(days=90)).strftime("%Y-%m-%d")
    q = f"""
        SELECT dp.symbol, dp.close, 
               (dp.close - dp_past.close) / dp_past.close as ret_6m,
               (dp.close - COALESCE(dp_3m.close, dp_past.close)) / COALESCE(dp_3m.close, dp_past.close) as ret_3m
        FROM daily_prices dp
        JOIN daily_prices dp_past ON dp.symbol = dp_past.symbol
        LEFT JOIN daily_prices dp_3m ON dp.symbol = dp_3m.symbol AND dp_3m.date = (
            SELECT MIN(date) FROM daily_prices WHERE date >= '{p_90}'
        )
        WHERE dp.date = '{sd}'
        AND dp_past.date = (
            SELECT MIN(date) FROM daily_prices WHERE date >= '{p_180}'
        )
        AND dp.close BETWEEN 70.0 AND 10000.0
        ORDER BY ret_6m DESC
        LIMIT 60
    """
    rows = session.execute(text(q)).fetchall()
    
    # Safe picks
    safe_picks = [r[0] for r in rows if stock_meta_map.get(r[0], {}).get("tier") == "large" or stock_beta_map.get(r[0], 1.0) <= 1.05][:5]
    
    # Risky picks (dual momentum: 6M + 3M)
    risky_cands = [r for r in rows if (r[3] is not None and r[3] > -0.02)]
    risky_cands.sort(key=lambda x: (x[2]*0.6 + (x[3] or 0.0)*0.4), reverse=True)
    risky_picks = [r[0] for r in risky_cands][:5]
    
    print(f"Date: {sd}")
    print(f"  SAFE:  {safe_picks}")
    print(f"  RISKY: {risky_picks}")

session.close()
