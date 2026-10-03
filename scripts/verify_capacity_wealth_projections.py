"""
scripts/verify_capacity_wealth_projections.py
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from db.database import get_global_engine, get_session
from core.monthly_sip_advisor import generate_monthly_sip_basket

def verify():
    s = get_session(get_global_engine())
    basket = generate_monthly_sip_basket(
        session=s,
        monthly_wallet=20000.0,
        strategy='PURE_STOCKS',
        annual_step_up_pct=10.0,
        target_stock_count=4,
        enable_dip_buying=True,
        enable_parabolic_skim=True
    )
    wp = basket['wealth_projections']
    print("\n--- WEALTH PROJECTIONS AUDIT ---")
    for k, v in wp.items():
        inv = v['invested']
        emp = v['projected_empirical']
        floor = v['projected_floor']
        xirr = v.get('stage_xirr', v.get('empirical_xirr', 0))
        print(f"{k:10s} | Invested: Rs. {inv:12,.0f} | Target (Empirical): Rs. {emp:14,.0f} ({emp/max(1,inv):.2f}x) | Baseline Floor: Rs. {floor:12,.0f} | XIRR: {xirr:.2f}%")
    s.close()

if __name__ == "__main__":
    verify()
