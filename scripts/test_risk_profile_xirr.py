import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.database import get_global_engine, get_session
from core.sip_audit_backtester import run_monthly_sip_backtest

engine = get_global_engine()
session = get_session(engine)

for m in [12, 24, 36, 60]:
    res = run_monthly_sip_backtest(session, monthly_wallet=20000, months_lookback=m, annual_step_up_pct=10.0)
    print(f"Months: {m} -> Invested: Rs.{res['total_invested']:,.0f}, Final: Rs.{res['final_strategy_value']:,.0f}, XIRR: {res['strategy_xirr']:.2f}%, NIFTY: {res['benchmark_xirr']:.2f}%, Trades: {res['total_trades']}")

session.close()
