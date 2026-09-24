import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.mf_sip_planner import run_mf_sip_backtest, CURATED_MF_BASKETS

engine = create_engine('sqlite:///data/stock_analyzer.db')
Session = sessionmaker(bind=engine)
session = Session()

print("=" * 90)
print("🏛️ 60-MONTH MUTUAL FUNDS SIP BACKTEST (₹20,000 / Month + 10% Step-Up)")
print("=" * 90)

for b_key, b_info in CURATED_MF_BASKETS.items():
    res = run_mf_sip_backtest(
        session,
        budget=20000.0,
        frequency='MONTHLY',
        basket_key=b_key,
        months_lookback=60,
        annual_step_up_pct=10.0
    )
    if "error" in res:
        print(f"{b_key:<25} | ERROR: {res['error']}")
    else:
        xirr = res.get('portfolio_xirr', 0.0)
        val = res.get('portfolio_final_value', 0.0) / 100000.0
        inv = res.get('total_invested', 0.0) / 100000.0
        n_xirr = res.get('benchmark_xirr', 0.0)
        alpha = res.get('alpha_xirr', 0.0)
        print(f"{b_info['title']:<38} | XIRR: {xirr:5.1f}% | Corpus: ₹{val:5.2f}L | Invested: ₹{inv:5.2f}L | Nifty XIRR: {n_xirr:5.1f}% | Alpha: {alpha:+5.1f}%")

session.close()
print("=" * 90)
