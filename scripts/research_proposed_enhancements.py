"""
scripts/research_proposed_enhancements.py
Quantitative Backtest Engine for Advanced Alpha & Drawdown Reduction Frontiers:
1. Baseline: Current Production Strategy (Adaptive Structural + Correlation Shield + Inertia Buffer)
2. Model A: Andreas Clenow Exponential Trend Smoothness (R^2 * Slope)
3. Model B: Van Tharp 3-Tier Asymmetric Harvest (+20% BE lock, +50% Chandelier 3x ATR, 34% Moonbag)
4. Model C: Nifty 500 Market Breadth Circuit Breaker (% > 50 EMA)
5. Model D: Equal Risk Contribution (ERC / ATR Risk Parity Sizing)
6. Model E: Portfolio Equity Curve 20-Day SMA Drawdown Breaker
7. Model F: All-Combined Apex Systematic Strategy
"""

import sys
from pathlib import Path

# Fix Windows stdout encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import math
import pandas as pd
import numpy as np
from datetime import datetime, date
from sqlalchemy import text
from db.database import get_global_engine, get_session
from core.sip_audit_backtester import run_monthly_sip_backtest
from core.walk_forward_cpcv import compute_deflated_sharpe_ratio


def compute_metrics_from_result(res: dict) -> dict:
    eq_curve = res.get("equity_curve", [])
    if not eq_curve or len(eq_curve) < 20:
        return {}

    eq_df = pd.DataFrame(eq_curve)
    strat_returns = []
    for i in range(1, len(eq_curve)):
        p_e = eq_curve[i - 1]["strategy_equity"]
        c_e = eq_curve[i]["strategy_equity"]
        p_c = eq_curve[i - 1]["capital_invested"]
        c_c = eq_curve[i]["capital_invested"]
        d_c = c_c - p_c
        if p_e > 0:
            strat_returns.append((c_e - d_c - p_e) / p_e)

    r_arr = np.array(strat_returns, dtype=float)
    r_arr = r_arr[np.isfinite(r_arr)]

    # Net XIRR
    xirr = res.get("friction_and_tax_audit", {}).get("net_in_pocket_xirr", res.get("strategy_xirr", 0.0))
    if not xirr or math.isnan(xirr):
        xirr = res.get("strategy_xirr", 0.0)

    # Annualized Return & Vol
    mean_ret = float(np.mean(r_arr)) if len(r_arr) > 0 else 0.0
    vol_daily = float(np.std(r_arr)) if len(r_arr) > 0 else 0.01
    ann_vol = vol_daily * math.sqrt(252.0)
    ann_ret = (1.0 + mean_ret) ** 252.0 - 1.0

    # Max Drawdown
    peak = eq_df["strategy_equity"].cummax()
    dd_series = (eq_df["strategy_equity"] - peak) / peak
    max_dd = float(dd_series.min()) * 100.0

    # Sharpe (rf = 6.5%)
    rf_daily = 0.065 / 252.0
    excess_ret = r_arr - rf_daily
    excess_std = float(np.std(excess_ret)) if len(excess_ret) > 0 else 0.01
    sharpe = float(np.mean(excess_ret) / max(1e-6, excess_std) * math.sqrt(252.0))

    # Calmar Ratio
    calmar = abs(xirr / max(0.1, abs(max_dd)))

    # Trades & Profit Factor / Payoff Ratio
    win_rate = res.get("win_rate", 0.0)
    profit_factor = res.get("profit_factor", 0.0)
    payoff_ratio = res.get("payoff_ratio", 0.0)
    closed = res.get("all_closed_positions", [])

    # Skewness & Kurtosis from DSR audit or return array
    dsr = res.get("dsr_audit", {})
    skewness = dsr.get("skewness", float(pd.Series(r_arr).skew()))
    kurt = dsr.get("kurtosis", float(pd.Series(r_arr).kurtosis() + 3.0))
    pbo = dsr.get("prob_backtest_overfitting_pct", 5.0)

    return {
        "xirr": round(xirr, 2),
        "cagr": round(ann_ret * 100.0, 2),
        "max_dd": round(max_dd, 2),
        "sharpe": round(sharpe, 2),
        "calmar": round(calmar, 2),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "payoff_ratio": round(payoff_ratio, 2),
        "skewness": round(skewness, 2),
        "kurtosis": round(kurt, 2),
        "pbo_pct": pbo,
        "final_equity": round(eq_df["strategy_equity"].iloc[-1], 2),
        "total_invested": round(res.get("total_invested", 0.0), 2),
        "closed_trades": len(closed)
    }


def main():
    engine = get_global_engine()
    session = get_session(engine)
    print("=" * 80)
    print("🚀 QUANTITATIVE COMPARATIVE RESEARCH & EMPIRICAL BACKTESTING")
    print("Testing 6 Frontiers for XIRR Boost, Profit Ratio Expansion & Drawdown Truncation")
    print("=" * 80)

    models_config = [
        {
            "name": "1. Baseline (Current Production)",
            "params": {
                "exit_protocol": "ADAPTIVE_STRUCTURAL",
                "sizing_mode": "CONVICTION",
                "enable_stepladder_trailing": True,
                "enable_correlation_clustering": True,
                "enable_position_inertia_buffer": True,
                "enable_volatility_targeting": False,
                "macro_hedge_pct": 10.0,
            }
        },
        {
            "name": "2. Model A: Equal Risk Contribution (ERC Sizing)",
            "params": {
                "exit_protocol": "ADAPTIVE_STRUCTURAL",
                "sizing_mode": "INVERSE_VOL",
                "enable_stepladder_trailing": True,
                "enable_correlation_clustering": True,
                "enable_position_inertia_buffer": True,
                "enable_volatility_targeting": False,
                "macro_hedge_pct": 10.0,
            }
        },
        {
            "name": "3. Model B: Dynamic Volatility Targeting (15% Vol Parity)",
            "params": {
                "exit_protocol": "ADAPTIVE_STRUCTURAL",
                "sizing_mode": "CONVICTION",
                "enable_stepladder_trailing": True,
                "enable_correlation_clustering": True,
                "enable_position_inertia_buffer": True,
                "enable_volatility_targeting": True,
                "target_volatility_pct": 15.0,
                "macro_hedge_pct": 10.0,
            }
        },
        {
            "name": "4. Model C: Smart Stepladder + Parabolic Skims (Multi-Tier)",
            "params": {
                "exit_protocol": "ADAPTIVE_STRUCTURAL",
                "sizing_mode": "CONVICTION",
                "enable_stepladder_trailing": True,
                "enable_parabolic_skim": True,
                "skim_milestone_pct": 100.0,
                "skim_ratio_pct": 25.0,
                "enable_correlation_clustering": True,
                "enable_position_inertia_buffer": True,
                "macro_hedge_pct": 10.0,
            }
        },
        {
            "name": "5. Model D: Macro Defense + Defensive Rotation (Gold Shield)",
            "params": {
                "exit_protocol": "ADAPTIVE_STRUCTURAL",
                "sizing_mode": "CONVICTION",
                "enable_stepladder_trailing": True,
                "enable_macro_regime_gate": True,
                "macro_hedge_pct": 20.0,
                "enable_macro_rotation": True,
                "macro_rotation_ratio": 1.0,
                "enable_correlation_clustering": True,
                "enable_position_inertia_buffer": True,
            }
        },
        {
            "name": "6. Model E: Institutional Apex (ERC + Stepladder + Vol Target + Macro)",
            "params": {
                "exit_protocol": "ADAPTIVE_STRUCTURAL",
                "sizing_mode": "INVERSE_VOL",
                "enable_stepladder_trailing": True,
                "enable_parabolic_skim": True,
                "skim_milestone_pct": 100.0,
                "skim_ratio_pct": 25.0,
                "enable_volatility_targeting": True,
                "target_volatility_pct": 16.0,
                "enable_macro_regime_gate": True,
                "macro_hedge_pct": 15.0,
                "enable_macro_rotation": True,
                "enable_correlation_clustering": True,
                "enable_position_inertia_buffer": True,
            }
        }
    ]

    results_table = []

    for cfg in models_config:
        print(f"\nRunning backtest for: {cfg['name']}...")
        try:
            res = run_monthly_sip_backtest(
                session=session,
                monthly_wallet=20000.0,
                strategy="PURE_STOCKS",
                months_lookback=36,
                risk_profile="BALANCED",
                annual_step_up_pct=10.0,
                enable_friction_and_tax=True,
                enable_tax_harvesting=True,
                **cfg["params"]
            )
            m = compute_metrics_from_result(res)
            m["model_name"] = cfg["name"]
            results_table.append(m)
            print(f"  --> Net XIRR: {m['xirr']}% | Max Drawdown: {m['max_dd']}% | Sharpe: {m['sharpe']} | Profit Factor: {m['profit_factor']} | Payoff: {m['payoff_ratio']}x | Win Rate: {m['win_rate']}%")
        except Exception as e:
            print(f"  Error testing {cfg['name']}: {e}")

    session.close()

    if results_table:
        df_results = pd.DataFrame(results_table)
        print("\n" + "=" * 105)
        print("📊 FINAL QUANTITATIVE COMPARISON MATRIX (36-Month Empirical Backtest)")
        print("=" * 105)
        cols = ["model_name", "xirr", "max_dd", "sharpe", "calmar", "profit_factor", "payoff_ratio", "win_rate", "skewness", "kurtosis", "pbo_pct"]
        print(df_results[cols].to_string(index=False))

    return results_table


if __name__ == "__main__":
    main()
