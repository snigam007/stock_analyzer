import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.database import get_global_engine, get_session
import core.sip_audit_backtester as bt_mod

engine = get_global_engine()
session = get_session(engine)

print(f"{'Horizon':<8} | {'Profile':<12} | {'Final Value':<14} | {'XIRR':<8} | {'Max DD':<8} | {'Win Rate':<8}")
print("-" * 70)

for m in [12, 24, 36, 60]:
    for rp in ["SAFE", "BALANCED", "RISKY"]:
        r = bt_mod.run_monthly_sip_backtest(session, monthly_wallet=20000, months_lookback=m, annual_step_up_pct=10.0, risk_profile=rp)
        print(f"{m} Months  | {rp:<12} | Rs.{r['final_strategy_value']:>10,.0f} | {r['strategy_xirr']:>6.1f}% | {r['max_drawdown_pct']:>6.1f}% | {r['win_rate']:>6.1f}%")
    print("-" * 70)

session.close()
