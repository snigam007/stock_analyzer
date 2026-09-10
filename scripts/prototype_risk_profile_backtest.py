import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.database import get_global_engine, get_session
from sqlalchemy import text
from datetime import datetime, timedelta
import pandas as pd
import math
import numpy as np

# We can import run_monthly_sip_backtest and test what happens if we patch it
import core.sip_audit_backtester as bt_mod

engine = get_global_engine()
session = get_session(engine)

# Let's inspect current returns across risk profiles
print("Testing current backtest function:")
for rp in ["SAFE", "BALANCED", "RISKY"]:
    res = bt_mod.run_monthly_sip_backtest(session, monthly_wallet=20000, months_lookback=36, annual_step_up_pct=10.0, risk_profile=rp)
    print(f"Current {rp} 36M -> Final: Rs.{res['final_strategy_value']:,.0f}, XIRR: {res['strategy_xirr']:.2f}%, Trades: {res['total_trades']}, WinRate: {res['win_rate']:.1f}%")

session.close()
