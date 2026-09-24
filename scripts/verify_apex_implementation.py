import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.getcwd())

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.monthly_sip_advisor import generate_monthly_sip_basket
from core.sip_audit_backtester import run_monthly_sip_backtest

DB_PATH = 'data/stock_analyzer.db'
engine = create_engine(f'sqlite:///{DB_PATH}', connect_args={'check_same_thread': False})
Session = sessionmaker(bind=engine)
session = Session()

print('=== 1. Testing generate_monthly_sip_basket() with New Defaults ===')
basket = generate_monthly_sip_basket(session=session)
assets = basket.get('assets', [])
print(f'Basket generated successfully! Asset count: {len(assets)}')
for a in assets:
    amt = a.get('allocated_amount', 0)
    shs = a.get('target_shares', 0)
    px = a.get('close_price', 0)
    sym = a.get('symbol')
    sec = a.get('sector')
    print(f"  - {sym} ({sec}): Rs {amt:,.0f} ({shs} shares @ Rs {px:,.1f})")

print('\n=== 2. Testing run_monthly_sip_backtest() Apex 1 (Default zero-override) ===')
res_apex = run_monthly_sip_backtest(session=session, months_lookback=60, annual_step_up_pct=10.0)
xirr1 = res_apex.get('strategy_xirr')
val1 = res_apex.get('final_strategy_value')
pf1 = res_apex.get('profit_factor')
pay1 = res_apex.get('payoff_ratio')
dd1 = res_apex.get('max_drawdown_pct')
print(f"Net XIRR: {xirr1}% | Final Corpus: Rs {val1:,.0f} | PF: {pf1} | Payoff: {pay1}x | Max DD: {dd1}%")

print('\n=== 3. Testing Centurion Alpha (15% Step-Up) ===')
res_cent = run_monthly_sip_backtest(session=session, months_lookback=60, annual_step_up_pct=15.0)
xirr2 = res_cent.get('strategy_xirr')
val2 = res_cent.get('final_strategy_value')
pf2 = res_cent.get('profit_factor')
pay2 = res_cent.get('payoff_ratio')
dd2 = res_cent.get('max_drawdown_pct')
print(f"Net XIRR: {xirr2}% | Final Corpus: Rs {val2:,.0f} | PF: {pf2} | Payoff: {pay2}x | Max DD: {dd2}%")

# Assertions
assert len(assets) > 0, "Expected at least 1 asset in monthly basket"
assert xirr1 == 63.46, f"Expected 63.46% XIRR for Apex 1, got {xirr1}"
assert val1 >= 5850000, f"Expected >= Rs 58.5L corpus, got {val1}"
assert xirr2 == 63.33, f"Expected 63.33% XIRR for Centurion, got {xirr2}"
assert val2 >= 6180000, f"Expected >= Rs 61.8L corpus, got {val2}"
print('\n>>> ALL EMPIRICAL VALIDATION CHECKS PASSED PERFECTLY! <<<')
