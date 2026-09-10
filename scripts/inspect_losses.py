import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.database import get_global_engine, get_session
import core.sip_audit_backtester as bt_mod

engine = get_global_engine()
session = get_session(engine)

res_36 = bt_mod.run_monthly_sip_backtest(
    session, monthly_wallet=20000, months_lookback=36, annual_step_up_pct=10.0,
    risk_profile="BALANCED", enable_conviction_weighting=False
)

res_36_conv = bt_mod.run_monthly_sip_backtest(
    session, monthly_wallet=20000, months_lookback=36, annual_step_up_pct=10.0,
    risk_profile="RISKY", enable_conviction_weighting=True
)

print(f"Equal Weight 36M: Losses={res_36['losing_trades']}, TotalLoss=Rs.{res_36['avg_loss_inr'] * res_36['losing_trades']:,.0f}, AvgWin=Rs.{res_36['avg_win_inr']:,.0f}")
print(f"Conviction 36M:   Losses={res_36_conv['losing_trades']}, TotalLoss=Rs.{res_36_conv['avg_loss_inr'] * res_36_conv['losing_trades']:,.0f}, AvgWin=Rs.{res_36_conv['avg_win_inr']:,.0f}")

session.close()
