"""
Debug script to run backtest for:
- Centurion
- Apex Alpha
- 1000 Strategy Champion (SIP_0194)
using run_monthly_sip_backtest with the exact arguments passed from Page 16.
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from core.sip_audit_backtester import run_monthly_sip_backtest
import importlib
p16 = importlib.import_module("pages.16_Monthly_SIP_and_Sell_Radar")
INSTITUTIONAL_PRESETS = p16.INSTITUTIONAL_PRESETS

engine = get_global_engine()
session = get_session(engine)

print("=" * 80)
print("TESTING BACKTEST CALLS FOR INSTITUTIONAL PRESETS")
print("=" * 80)

for name, cfg in INSTITUTIONAL_PRESETS.items():
    if "Centurion" in name or "Apex Alpha" in name or "1000-Strategy" in name:
        print(f"\n--- Running for: {name} ---")
        print(f"Config: {cfg}")
        # Let's see what arguments Page 16 passes
        stepup_val = 10.0
        if "step_up" in cfg:
            stepup_str = cfg["step_up"]
            stepup_val = float(stepup_str.replace(" / Year (Recommended)", "").replace(" / Year", "").replace("+", "").replace("%/yr", "").replace("%", "").strip())
        
        target_stocks = cfg.get("target_stocks", 4)
        proto_code = cfg.get("proto_code", "ADAPTIVE_STRUCTURAL")
        risk_code = cfg.get("risk_code", "RISKY")
        macro_hedge_pct = cfg.get("macro_hedge_pct", 0)
        hurdle_val = 25.0 if "25%" in cfg.get("hurdle_mode", "") else (30.0 if "30%" in cfg.get("hurdle_mode", "") else 20.0)
        sector_boost = cfg.get("sector_boost", False)
        
        # Test 12 Months (1 Year) and 24 Months (2 Years)
        for m in [12, 24, 60]:
            res = run_monthly_sip_backtest(
                session=session,
                monthly_wallet=20000.0,
                strategy="PURE_STOCKS",
                months_lookback=m,
                exit_protocol=proto_code,
                risk_profile=risk_code,
                annual_step_up_pct=stepup_val,
                target_stock_count=target_stocks,
                min_momentum_hurdle_pct=hurdle_val,
                macro_hedge_pct=macro_hedge_pct,
                enable_sector_rotation_score=sector_boost
            )
            print(f"Months: {m:2d} | XIRR: {res.get('annualized_xirr_pct')}% | Total Invested: ₹{res.get('total_invested'):,.0f} | Current Value: ₹{res.get('current_portfolio_value'):,.0f} | Trades: {len(res.get('completed_trades', []))}")

session.close()
