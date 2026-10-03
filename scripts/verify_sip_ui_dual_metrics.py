import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.getcwd())

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.monthly_sip_advisor import generate_monthly_sip_basket

DB_PATH = 'data/stock_analyzer.db'
engine = create_engine(f'sqlite:///{DB_PATH}', connect_args={'check_same_thread': False})
Session = sessionmaker(bind=engine)
session = Session()

print('=== 1. Testing Dual Wealth Projections in generate_monthly_sip_basket ===')
basket = generate_monthly_sip_basket(session=session, monthly_wallet=20000, target_stock_count=4, annual_step_up_pct=10.0)

base_cagr = basket.get('expected_cagr_pct')
emp_xirr = basket.get('empirical_xirr_pct')
wp5 = basket.get('wealth_projections', {}).get('5_years', {})
floor_5y = wp5.get('projected_floor')
emp_5y = wp5.get('projected_empirical')
alpha_5y = wp5.get('net_alpha_corpus')
inv_5y = wp5.get('invested')

print(f"Conservative Baseline CAGR: {base_cagr}%/yr")
print(f"Empirical Strategy XIRR:   {emp_xirr}%/yr")
print(f"5Y Capital Invested:       Rs {inv_5y:,.0f}")
print(f"5Y Baseline Floor:         Rs {floor_5y:,.0f}")
print(f"5Y Empirical Strategy:     Rs {emp_5y:,.0f}")
print(f"5Y Net Strategy Alpha:     Rs {alpha_5y:,.0f}")

# Assertions
assert emp_xirr >= 60.0, f"Expected empirical XIRR >= 60%, got {emp_xirr}"
assert emp_5y >= 5800000.0, f"Expected 5Y empirical corpus >= Rs 58L, got {emp_5y}"
assert floor_5y > 0 and floor_5y < emp_5y, f"Expected floor ({floor_5y}) < empirical ({emp_5y})"
assert alpha_5y >= 3000000.0, f"Expected net alpha >= Rs 30L, got {alpha_5y}"

print('\n>>> DUAL METRICS & PROJECTIONS VALIDATION PASSED! <<<')
session.close()
