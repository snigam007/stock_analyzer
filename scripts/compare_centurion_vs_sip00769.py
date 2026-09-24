import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from db.database import get_global_engine, get_session
from core.sip_audit_backtester import run_monthly_sip_backtest

session = get_session()

print("=" * 110)
print(f"{'STRATEGY':<35} | {'HORIZON':<7} | {'XIRR':<8} | {'ALPHA':<8} | {'MAX DD':<8} | {'INVESTED':<12} | {'FINAL VALUE':<12} | {'PAYOFF'}")
print("=" * 110)

# Centurion configuration
centurion_cfg = {
    "target_stock_count": 4,
    "exit_protocol": "ADAPTIVE_STRUCTURAL",
    "annual_step_up_pct": 15.0,
    "min_momentum_hurdle_pct": 30.0,
    "enable_dip_buying": True,
    "enable_parabolic_skim": True,
}

# SIP_00769 configuration
sip_00769_cfg = {
    "target_stock_count": 3,
    "exit_protocol": "DYNAMIC_ATR",
    "annual_step_up_pct": 20.0,
    "min_momentum_hurdle_pct": 40.0,
    "pyramid_winners": True,
    "enable_dip_buying": False,
}

# SIP_00769 with Dip Buying & Parabolic Skim enabled
sip_00769_boosted_cfg = {
    "target_stock_count": 3,
    "exit_protocol": "DYNAMIC_ATR",
    "annual_step_up_pct": 20.0,
    "min_momentum_hurdle_pct": 40.0,
    "pyramid_winners": True,
    "enable_dip_buying": True,
    "enable_parabolic_skim": True,
}

test_configs = [
    ("🏆 Centurion Wealth Engine", centurion_cfg),
    ("🌟 SIP_00769 (Apex Concentrated)", sip_00769_cfg),
    ("🚀 SIP_00769 + Dip & Skim Synergy", sip_00769_boosted_cfg),
]

for name, cfg in test_configs:
    for h in [12, 24, 36, 60]:
        res = run_monthly_sip_backtest(
            session=session,
            monthly_wallet=20000.0,
            strategy="PURE_STOCKS",
            months_lookback=h,
            risk_profile="RISKY",
            **cfg
        )
        xirr = res.get("strategy_xirr", 0.0)
        alpha = res.get("alpha", 0.0)
        dd = res.get("max_drawdown_pct", 0.0)
        inv = res.get("total_invested", 0.0)
        val = res.get("final_strategy_value", 0.0)
        pr = res.get("payoff_ratio", 0.0)
        print(f"{name:<35} | {h} Mo   | {xirr:+6.2f}% | {alpha:+6.2f}% | {dd:6.2f}% | ₹{inv:10,.0f} | ₹{val:10,.0f} | {pr:5.2f}x")

session.close()
