import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.database import get_global_engine, get_session
import core.sip_audit_backtester as bt_mod

engine = get_global_engine()
session = get_session(engine)

for m in [24, 36, 60]:
    r_bal = bt_mod.run_monthly_sip_backtest(session, monthly_wallet=20000, months_lookback=m, annual_step_up_pct=10.0, risk_profile="BALANCED", enable_conviction_weighting=False)
    r_risk_eq = bt_mod.run_monthly_sip_backtest(session, monthly_wallet=20000, months_lookback=m, annual_step_up_pct=10.0, risk_profile="RISKY", enable_conviction_weighting=False)
    print(f"{m}M -> BALANCED: XIRR={r_bal['strategy_xirr']:.2f}%, Final=Rs.{r_bal['final_strategy_value']:,.0f} | RISKY (equal): XIRR={r_risk_eq['strategy_xirr']:.2f}%, Final=Rs.{r_risk_eq['final_strategy_value']:,.0f}")

session.close()
