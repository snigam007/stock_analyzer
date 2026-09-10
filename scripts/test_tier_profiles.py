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

# Let's inspect returns when SAFE requires large-caps, BALANCED balances large+mid, and RISKY is pure high-momentum alpha
stocks_meta = session.execute(text("SELECT symbol, name, sector, market_cap_tier FROM stocks WHERE is_active = 1")).fetchall()
stock_sector_map = {r[0]: (r[1] or r[0], r[2] or "General") for r in stocks_meta}
stock_meta_map = {r[0]: {"name": r[1] or r[0], "sector": r[2] or "General", "tier": (r[3] or "mid").lower()} for r in stocks_meta}

beta_rows = session.execute(text("SELECT symbol, AVG(beta) FROM composite_scores GROUP BY symbol")).fetchall()
stock_beta_map = {r[0]: float(r[1]) if r[1] is not None else 1.0 for r in beta_rows}

print("Loaded metadata. Ready to test tier profile constraints.")
session.close()
