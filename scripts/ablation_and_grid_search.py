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

# Base dictionary matching user's 60-month run
base_params = dict(
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

print("=" * 100)
print("🔬 STEP 1: ABLATION STUDY — TOGGLING OFF INDIVIDUAL FEATURES FROM 60M BASELINE")
print("=" * 100)

ablation_tests = [
    ("Current Screenshot Baseline (All ON)", {}),
    ("NO Volatility Targeting (15% Vol OFF)", {"enable_volatility_targeting": False}),
    ("NO Van Tharp 3-Tier Exit (OFF)", {"enable_3tier_harvest": False}),
    ("NO Smart Stepladder Trailing (OFF)", {"enable_stepladder_trailing": False}),
    ("NO Clenow Momentum (Pure 6M Momentum)", {"enable_clenow_momentum": False}),
    ("NO 60-Day Loss Cooldown (OFF)", {"enable_loss_cooldown": False}),
    ("NO Sector Momentum Gate (OFF)", {"enable_sector_momentum_gate": False}),
    ("NO Macro Hedge / Breadth Gate (100% Equity)", {"enable_macro_regime_gate": False, "enable_breadth_gate": False}),
    ("NO Two-Tier Profit Skim (OFF)", {"enable_parabolic_skim": False}),
    ("NO Tactical Dip Buying (OFF)", {"enable_dip_buying": False}),
    ("NO Winner Pyramiding (OFF)", {"pyramid_winners": False}),
    ("NO Momentum Hurdle (0% Hurdle)", {"min_momentum_hurdle_pct": 0.0}),
    ("Sizing: Equal Risk Contribution (ERC)", {"sizing_mode": "ERC", "enable_conviction_weighting": False}),
    ("Sizing: Equal Weight (20% each)", {"sizing_mode": "EQUAL", "enable_conviction_weighting": False}),
    ("Protocol: Dynamic ATR Stops", {"exit_protocol": "DYNAMIC_ATR"}),
    ("Protocol: Structural Trailing", {"exit_protocol": "STRUCTURAL_TRAILING"}),
    ("Protocol: Uncapped Buy & Hold", {"exit_protocol": "BUY_AND_HOLD"}),
]

records = []
for name, overrides in ablation_tests:
    p = base_params.copy()
    p.update(overrides)
    res = run_monthly_sip_backtest(session=session, **p)
    records.append({
        "configuration": name,
        "xirr": res.get("strategy_xirr"),
        "profit_factor": res.get("profit_factor"),
        "payoff_ratio": res.get("payoff_ratio"),
        "win_rate": res.get("win_rate"),
        "max_drawdown": res.get("max_drawdown_pct"),
        "final_value": res.get("final_strategy_value"),
        "total_trades": res.get("total_trades"),
        "wins": res.get("winning_trades"),
        "losses": res.get("losing_trades"),
    })
    print(f"Done: {name} -> XIRR: {res.get('strategy_xirr')}% | PF: {res.get('profit_factor')} | Payoff: {res.get('payoff_ratio')}x | DD: {res.get('max_drawdown_pct')}%")

df_ablation = pd.DataFrame(records)
print("\n" + "=" * 100)
print("📊 ABLATION SUMMARY TABLE (60 MONTHS)")
print("=" * 100)
print(df_ablation[["configuration", "xirr", "profit_factor", "payoff_ratio", "win_rate", "max_drawdown", "final_value"]].to_string(index=False))

session.close()
