import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.database import get_global_engine, get_session
import core.sip_audit_backtester as bt_mod

engine = get_global_engine()
session = get_session(engine)

r_bal = bt_mod.run_monthly_sip_backtest(session, monthly_wallet=20000, months_lookback=24, annual_step_up_pct=10.0, risk_profile="BALANCED")
r_risk = bt_mod.run_monthly_sip_backtest(session, monthly_wallet=20000, months_lookback=24, annual_step_up_pct=10.0, risk_profile="RISKY")

# Compare closed trades
print("=== BALANCED TOP WINS ===")
wins_bal = sorted([t for t in r_bal['trade_log'] if t['status'] == 'WIN'], key=lambda x: x['pnl'], reverse=True)
for w in wins_bal[:5]:
    print(f"  {w['symbol']} ({w['tier']}): PnL=+Rs.{w['pnl']:,.0f} (+{w['return_pct']:.1f}%), Exit: {w['exit_reason']}")

print("\n=== RISKY TOP WINS ===")
wins_risk = sorted([t for t in r_risk['trade_log'] if t['status'] == 'WIN'], key=lambda x: x['pnl'], reverse=True)
for w in wins_risk[:5]:
    print(f"  {w['symbol']} ({w['tier']}): PnL=+Rs.{w['pnl']:,.0f} (+{w['return_pct']:.1f}%), Exit: {w['exit_reason']}")

print("\n=== BALANCED LOSSES ===")
loss_bal = sorted([t for t in r_bal['trade_log'] if t['status'] == 'LOSS'], key=lambda x: x['pnl'])
for l in loss_bal[:5]:
    print(f"  {l['symbol']} ({l['tier']}): PnL=-Rs.{-l['pnl']:,.0f} ({l['return_pct']:.1f}%), Exit: {l['exit_reason']}")

print("\n=== RISKY LOSSES ===")
loss_risk = sorted([t for t in r_risk['trade_log'] if t['status'] == 'LOSS'], key=lambda x: x['pnl'])
for l in loss_risk[:5]:
    print(f"  {l['symbol']} ({l['tier']}): PnL=-Rs.{-l['pnl']:,.0f} ({l['return_pct']:.1f}%), Exit: {l['exit_reason']}")

session.close()
