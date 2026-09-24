import sys, os
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from db.database import get_session, get_global_engine
from core.sip_audit_backtester import run_monthly_sip_backtest
import pandas as pd
import itertools

engine = get_global_engine()
session = get_session(engine)

print("=" * 100)
print("🚀 RUNNING COMPREHENSIVE COMBINATORIAL SEARCH FOR THE OPTIMAL PORTFOLIO ENGINE")
print("=" * 100)

protocols = ["ADAPTIVE_STRUCTURAL", "DYNAMIC_ATR", "STRUCTURAL_TRAILING", "BUY_AND_HOLD"]
sizings = ["ERC", "CONVICTION", "EQUAL"]
tharp_options = [False, True]
clenow_options = [False, True]
stepladder_options = [True, False]
macro_hedge_pcts = [5.0, 10.0]

# Generate parameter combinations
combos = []
for proto in protocols:
    for sz in sizings:
        for tharp in tharp_options:
            for clenow in clenow_options:
                for step in stepladder_options:
                    for h_pct in macro_hedge_pcts:
                        combos.append({
                            "exit_protocol": proto,
                            "sizing_mode": sz,
                            "enable_conviction_weighting": (sz == "CONVICTION"),
                            "enable_3tier_harvest": tharp,
                            "enable_clenow_momentum": clenow,
                            "enable_stepladder_trailing": step,
                            "macro_hedge_pct": h_pct,
                        })

print(f"Total Combinations to Evaluate: {len(combos)}")

results_60m = []
for idx, c in enumerate(combos):
    params = dict(
        monthly_wallet=20000.0,
        strategy="PURE_STOCKS",
        months_lookback=60,
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
        macro_hedge_asset="GOLDBEES.NS",
        enable_macro_rotation=True,
        macro_rotation_ratio=1.0,
        enable_correlation_clustering=True,
        max_pairwise_correlation=0.65,
        enable_friction_and_tax=True,
        enable_tax_harvesting=True,
        enable_volatility_targeting=False, # Ablation proved vol targeting dragged returns
        enable_position_inertia_buffer=True,
        inertia_buffer_pct=12.0,
        enable_breadth_gate=True
    )
    params.update(c)
    res = run_monthly_sip_backtest(session=session, **params)
    
    score = (
        (res.get("strategy_xirr", 0.0) or 0.0) * 0.40 +
        (res.get("profit_factor", 0.0) or 0.0) * 10.0 * 0.30 +
        (res.get("payoff_ratio", 0.0) or 0.0) * 5.0 * 0.15 -
        (res.get("max_drawdown_pct", 0.0) or 0.0) * 0.15
    )
    
    results_60m.append({
        "id": idx + 1,
        "proto": c["exit_protocol"][:10],
        "sizing": c["sizing_mode"],
        "3tier": c["enable_3tier_harvest"],
        "clenow": c["enable_clenow_momentum"],
        "step": c["enable_stepladder_trailing"],
        "hedge_pct": c["macro_hedge_pct"],
        "xirr": res.get("strategy_xirr"),
        "profit_factor": res.get("profit_factor"),
        "payoff": res.get("payoff_ratio"),
        "win_rate": res.get("win_rate"),
        "max_dd": res.get("max_drawdown_pct"),
        "final_val": res.get("final_strategy_value"),
        "score": round(score, 2)
    })
    
    if (idx + 1) % 10 == 0 or idx == len(combos) - 1:
        print(f"Evaluated {idx + 1}/{len(combos)} combos...")

df_res = pd.DataFrame(results_60m)
df_res.to_csv("scripts/grid_results_60m.csv", index=False)

print("\n" + "=" * 100)
print("🏆 TOP 10 COMBINATIONS BY COMPOSITE QUANT SCORE (XIRR + Profit Factor + Payoff + Drawdown)")
print("=" * 100)
top_score = df_res.sort_values("score", ascending=False).head(10)
print(top_score[["id", "proto", "sizing", "3tier", "clenow", "step", "hedge_pct", "xirr", "profit_factor", "payoff", "win_rate", "max_dd", "final_val", "score"]].to_string(index=False))

print("\n" + "=" * 100)
print("🚀 TOP 5 COMBINATIONS BY MAXIMUM NET XIRR (Pure Alpha)")
print("=" * 100)
top_xirr = df_res.sort_values("xirr", ascending=False).head(5)
print(top_xirr[["id", "proto", "sizing", "3tier", "clenow", "step", "hedge_pct", "xirr", "profit_factor", "payoff", "max_dd", "final_val"]].to_string(index=False))

print("\n" + "=" * 100)
print("🎯 TOP 5 COMBINATIONS BY MAXIMUM PROFIT FACTOR")
print("=" * 100)
top_pf = df_res.sort_values("profit_factor", ascending=False).head(5)
print(top_pf[["id", "proto", "sizing", "3tier", "clenow", "step", "hedge_pct", "xirr", "profit_factor", "payoff", "win_rate", "max_dd"]].to_string(index=False))

print("\n" + "=" * 100)
print("🛡️ TOP 5 COMBINATIONS BY MINIMUM DRAWDOWN")
print("=" * 100)
top_dd = df_res.sort_values("max_dd", ascending=True).head(5)
print(top_dd[["id", "proto", "sizing", "3tier", "clenow", "step", "hedge_pct", "xirr", "profit_factor", "payoff", "max_dd"]].to_string(index=False))

session.close()
