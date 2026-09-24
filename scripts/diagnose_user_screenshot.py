import sys, os
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from db.database import get_session, get_global_engine
from core.sip_audit_backtester import run_monthly_sip_backtest
import pandas as pd
import numpy as np

engine = get_global_engine()
session = get_session(engine)

print("=" * 80)
print("🔍 REPRODUCING USER'S EXACT 60-MONTH RUN FROM SCREENSHOT")
print("=" * 80)

# User's exact parameters from screenshot:
# Horizon: 5 Years (60 Mo)
# Wallet: 20000 (Invested 14,65,224 with +10%/yr step-up)
# Exit Protocol: ADAPTIVE_STRUCTURAL
# Annual Step-Up: 10%
# Winner Pyramiding: True
# Momentum Hurdle: 20%
# 45% Cap Guard: True
# Tactical Dip Buying: True
# Two-Tier Profit Skim: True
# Include MF: False
# 60-Day Loss Cooldown: True
# Sector Momentum Gate: True
# 200-EMA Macro Hedge: True (Hedge % = 5%)
# Macro Rotation: True
# Smart Stepladder: True
# Orthogonal Shield: True (r < 0.65)
# Real-World Friction & Tax: True
# Sizing: Conviction (30/25/20/15/10)
# Sec 112A Tax Harvesting: True
# Volatility Targeting: True (15% Vol)
# Rob Carver Buffer: True (12%)
# Van Tharp 3-Tier Exit: True
# Clenow Smooth Momentum: True
# Nifty 500 Breadth Gate: True

user_params = dict(
    monthly_wallet=20000.0,
    strategy="PURE_STOCKS",
    months_lookback=60,
    exit_protocol="ADAPTIVE_STRUCTURAL",
    risk_profile="RISKY",
    annual_step_up_pct=10.0,
    pyramid_winners=True,
    min_momentum_hurdle_pct=20.0,
    enable_dip_buying=True,
    dip_threshold_pct=4.0,
    dip_cooldown_days=10,
    dip_deploy_pct=70.0,
    enable_parabolic_skim=True,
    skim_milestone_pct=150.0,
    skim_ratio_pct=15.0,
    max_position_cap_pct=45.0,
    target_stock_count=5,
    include_mutual_funds=False,
    enable_loss_cooldown=True,
    cooldown_days=60,
    enable_sector_momentum_gate=True,
    enable_macro_regime_gate=True,
    macro_regime_trigger="EMA_200",
    macro_hedge_pct=5.0,
    macro_hedge_asset="GOLDBEES.NS",
    enable_macro_rotation=True,
    macro_rotation_ratio=1.0,
    enable_stepladder_trailing=True,
    enable_conviction_weighting=True,
    sizing_mode="CONVICTION",
    enable_correlation_clustering=True,
    max_pairwise_correlation=0.65,
    enable_friction_and_tax=True,
    enable_tax_harvesting=True,
    enable_volatility_targeting=True,
    enable_position_inertia_buffer=True,
    inertia_buffer_pct=12.0,
    enable_3tier_harvest=True,
    enable_clenow_momentum=True,
    enable_breadth_gate=True
)

res_screenshot = run_monthly_sip_backtest(session=session, **user_params)

print(f"Screenshot Match Result:")
print(f"  Total Invested: ₹{res_screenshot.get('total_invested'):,.0f}")
print(f"  Final Portfolio Value: ₹{res_screenshot.get('final_strategy_value'):,.0f}")
print(f"  Strategy XIRR: {res_screenshot.get('strategy_xirr')}%")
print(f"  Benchmark NIFTY XIRR: {res_screenshot.get('benchmark_xirr')}%")
print(f"  Alpha: {res_screenshot.get('alpha')}%")
print(f"  Win Rate: {res_screenshot.get('win_rate')}% ({res_screenshot.get('winning_trades')}/{res_screenshot.get('total_trades')} trades)")
print(f"  Profit Factor: {res_screenshot.get('profit_factor')}")
print(f"  Payoff Ratio: {res_screenshot.get('payoff_ratio')}x")
print(f"  Max Drawdown: {res_screenshot.get('max_drawdown_pct')}%")
print(f"  Total Sell Triggers: {res_screenshot.get('sell_reminder_audit', {}).get('total_sell_triggers')}")
print(f"  Capital Preserved: ₹{res_screenshot.get('sell_reminder_audit', {}).get('total_capital_preserved_inr'):,.0f}")

session.close()
