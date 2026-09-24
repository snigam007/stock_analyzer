"""
Direct execution of run_monthly_sip_backtest to check what XIRRs are produced.
"""
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from core.sip_audit_backtester import run_monthly_sip_backtest

engine = get_global_engine()
session = get_session(engine)

configs = {
    "Apex Alpha Champion": {
        "target_stock_count": 4,
        "exit_protocol": "ADAPTIVE_STRUCTURAL",
        "annual_step_up_pct": 10.0,
        "min_momentum_hurdle_pct": 30.0,
        "macro_hedge_pct": 0,
        "enable_sector_rotation_score": False
    },
    "Centurion Wealth Engine": {
        "target_stock_count": 4,
        "exit_protocol": "ADAPTIVE_STRUCTURAL",
        "annual_step_up_pct": 15.0,
        "min_momentum_hurdle_pct": 30.0,
        "macro_hedge_pct": 0,
        "enable_sector_rotation_score": False
    },
    "1000-Strategy Champion (SIP_0194)": {
        "target_stock_count": 6,
        "exit_protocol": "DYNAMIC_ATR",
        "annual_step_up_pct": 10.0,
        "min_momentum_hurdle_pct": 25.0,
        "macro_hedge_pct": 0,
        "enable_sector_rotation_score": True
    },
}

for name, cfg in configs.items():
    print(f"\n=======================================================")
    print(f"Strategy: {name}")
    print(f"=======================================================")
    for m in [12, 24, 36, 60]:
        res = run_monthly_sip_backtest(
            session=session,
            monthly_wallet=20000.0,
            strategy="PURE_STOCKS",
            months_lookback=m,
            risk_profile="RISKY",
            **cfg
        )
        xirr = res.get("annualized_xirr_pct")
        strat_xirr = res.get("strategy_xirr")
        invested = res.get("total_invested")
        curr_val = res.get("current_portfolio_value")
        alpha = res.get("alpha")
        trades = len(res.get("completed_trades", []))
        active = len(res.get("active_positions", []))
        print(f"Months: {m:2d} | annualized_xirr_pct: {xirr}% | strategy_xirr: {strat_xirr}% | Invested: {invested} | Value: {curr_val} | Alpha: {alpha}% | Completed: {trades} | Active: {active}")

session.close()
