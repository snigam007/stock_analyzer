"""Debug: inspect actual result structure from backtester"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.sip_audit_backtester import run_monthly_sip_backtest

engine = create_engine("sqlite:///data/stock_analyzer.db", connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine)
session = Session()

result = run_monthly_sip_backtest(
    session=session,
    monthly_wallet=20000.0,
    strategy="PURE_STOCKS",
    months_lookback=12,   # short run for speed
    exit_protocol="ADAPTIVE_STRUCTURAL",
    risk_profile="RISKY",
    annual_step_up_pct=10.0,
    pyramid_winners=True,
    sizing_mode="EQUAL",
    enable_stepladder_trailing=True,
)
session.close()

print("Top-level keys:", list(result.keys()))
for k, v in result.items():
    if isinstance(v, dict):
        print(f"\n  {k} (dict):")
        for kk, vv in v.items():
            print(f"    {kk}: {vv}")
    elif isinstance(v, (list, tuple)):
        print(f"\n  {k} (list, len={len(v)})")
    else:
        print(f"  {k}: {v}")
