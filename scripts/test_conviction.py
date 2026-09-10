import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.database import get_global_engine, get_session
import core.sip_audit_backtester as bt_mod

engine = get_global_engine()
session = get_session(engine)

# Let's test with conviction weighting enabled vs disabled
res_normal = bt_mod.run_monthly_sip_backtest(session, monthly_wallet=20000, months_lookback=60, annual_step_up_pct=10.0, enable_conviction_weighting=False)
res_conv = bt_mod.run_monthly_sip_backtest(session, monthly_wallet=20000, months_lookback=60, annual_step_up_pct=10.0, enable_conviction_weighting=True)

print(f"Normal Equal: Final Rs.{res_normal['final_strategy_value']:,.0f}, XIRR: {res_normal['strategy_xirr']:.2f}%, WinRate: {res_normal['win_rate']:.1f}%")
print(f"Conviction:   Final Rs.{res_conv['final_strategy_value']:,.0f}, XIRR: {res_conv['strategy_xirr']:.2f}%, WinRate: {res_conv['win_rate']:.1f}%")

session.close()
