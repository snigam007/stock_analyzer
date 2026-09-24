"""
Complete verification of backtesting across:
1. 1000-Strategy Champion (SIP_0194)
2. Apex Alpha Champion
3. Centurion Wealth Engine
4. All other institutional presets

Runs run_monthly_sip_backtest across 1Y (12M), 2Y (24M), 3Y (36M), and 5Y (60M).
Outputs exact XIRR, Alpha, Total Invested, Final Value, Profit Factor, Payoff Ratio, Max DD.
"""
import sys
from pathlib import Path
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from core.sip_audit_backtester import run_monthly_sip_backtest

engine = get_global_engine()
session = get_session(engine)

test_presets = {
    "🌟 1000-Strategy Champion (SIP_0194)": {
        "target_stock_count": 6,
        "exit_protocol": "DYNAMIC_ATR",
        "annual_step_up_pct": 10.0,
        "min_momentum_hurdle_pct": 25.0,
        "macro_hedge_pct": 0,
        "enable_sector_rotation_score": True,
        "enable_loss_cooldown": True,
        "cooldown_days": 60,
    },
    "👑 Apex Alpha Champion": {
        "target_stock_count": 4,
        "exit_protocol": "ADAPTIVE_STRUCTURAL",
        "annual_step_up_pct": 10.0,
        "min_momentum_hurdle_pct": 30.0,
        "macro_hedge_pct": 0,
        "enable_sector_rotation_score": False,
        "enable_loss_cooldown": True,
        "cooldown_days": 60,
    },
    "🏆 Centurion Wealth Engine": {
        "target_stock_count": 4,
        "exit_protocol": "ADAPTIVE_STRUCTURAL",
        "annual_step_up_pct": 15.0,
        "min_momentum_hurdle_pct": 30.0,
        "macro_hedge_pct": 0,
        "enable_sector_rotation_score": False,
        "enable_loss_cooldown": True,
        "cooldown_days": 60,
    },
    "🛡️ Capital Preservation Fortress": {
        "target_stock_count": 5,
        "exit_protocol": "ADAPTIVE_STRUCTURAL",
        "annual_step_up_pct": 0.0,
        "min_momentum_hurdle_pct": 15.0,
        "macro_hedge_pct": 10.0,
        "enable_sector_rotation_score": False,
        "enable_loss_cooldown": True,
        "cooldown_days": 60,
    },
}

horizons = [12, 24, 36, 60]
results = []

print("=" * 95)
print(f"{'PRESET NAME':<38} | {'HORIZON':<7} | {'STRAT XIRR':<11} | {'BENCH XIRR':<11} | {'ALPHA':<9} | {'INVESTED':<10} | {'FINAL VALUE':<11} | {'MAX DD'}")
print("=" * 95)

for name, cfg in test_presets.items():
    for h in horizons:
        res = run_monthly_sip_backtest(
            session=session,
            monthly_wallet=20000.0,
            strategy="PURE_STOCKS",
            months_lookback=h,
            risk_profile="RISKY",
            **cfg
        )
        s_xirr = res.get("strategy_xirr")
        b_xirr = res.get("benchmark_xirr")
        alpha = res.get("alpha")
        inv = res.get("total_invested")
        val = res.get("final_strategy_value")
        dd = res.get("max_drawdown_pct")
        
        results.append({
            "Preset": name,
            "Horizon": f"{h}M",
            "Strategy_XIRR": s_xirr,
            "Benchmark_XIRR": b_xirr,
            "Alpha": alpha,
            "Invested": inv,
            "Final_Value": val,
            "Max_DD": dd,
            "Profit_Factor": res.get("profit_factor"),
            "Payoff_Ratio": res.get("payoff_ratio"),
            "Win_Rate": res.get("win_rate")
        })
        print(f"{name:<38} | {h:2d} Mo   | {s_xirr:+8.2f}%   | {b_xirr:+8.2f}%   | {alpha:+7.2f}% | ₹{inv:9,.0f} | ₹{val:10,.0f} | {dd:5.1f}%")

session.close()

df = pd.DataFrame(results)
df.to_csv("scripts/verified_presets_backtest_results.csv", index=False)
print("\nSaved detailed backtest comparison to scripts/verified_presets_backtest_results.csv")
