#!/usr/bin/env python3
"""
scripts/run_production_champion_backtest.py

Runs the finalized production champion strategy:
"Multi-Lookback Persistence + Winner Pyramiding & 3-Tier Scaling"
across both:
1. 60-Day Stress Consolidation (July 1, 2026 to Sept 22, 2026)
2. 1-Year Full Cycle (Sept 22, 2025 to Sept 22, 2026)

Outputs comprehensive comparative performance metrics.
"""
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.backtest_broad_spectrum_strategies import run_spectrum_simulation

print("=" * 125)
print("🚀 RUNNING PRODUCTION CHAMPION STRATEGY BACKTEST")
print("Strategy: Multi-Lookback Persistence + Jesse Livermore Pyramiding & 3-Tier Scaling")
print("=" * 125)

params = {
    "max_slots": 6,
    "entry_mode": "MULTI_LOOKBACK",
    "exit_mode": "THREE_TIER_SCALE",
    "pyramid_on_win": True,
    "t1_atr": 1.6,
    "t2_atr": 3.2,
    "t3_atr": 6.0,
    "sl_atr": 1.5,
    "time_stop_days": 6,
    "min_gain_for_breakeven": 4.5
}

# 1. 60-Day Stress Period
print("\n[1/2] Simulating 60-Day Stress Consolidation Period (2026-07-01 to 2026-09-22)...")
r_60d = run_spectrum_simulation(
    strategy_id="PROD_60D",
    strategy_name="Champion: Multi-Lookback + Pyramiding (60-Day Stress)",
    start_date="2026-07-01",
    end_date="2026-09-22",
    **params
)

# 2. 1-Year Multi-Regime Cycle
print("\n[2/2] Simulating 1-Year Multi-Regime Full Cycle (2025-09-22 to 2026-09-22)...")
r_1yr = run_spectrum_simulation(
    strategy_id="PROD_1YR",
    strategy_name="Champion: Multi-Lookback + Pyramiding (1-Year Full Cycle)",
    start_date="2025-09-22",
    end_date="2026-09-22",
    **params
)

print("\n" + "=" * 125)
print(f"{'Simulation Horizon':<32} | {'Period Ret':<10} | {'Benchmark':<10} | {'Alpha':<8} | {'XIRR':<8} | {'Win %':<6} | {'PF':<5} | {'PR':<5} | {'Max DD':<6}")
print("-" * 125)
for r in [r_60d, r_1yr]:
    print(f"{r['name']:<32} | {r['return_pct']:+8.2f}% | {r['benchmark_pct']:+8.2f}% | {r['alpha_pct']:+7.2f}% | {r['xirr']:+7.1f}% | {r['win_rate']:5.1f}% | {r['profit_factor']:4.2f} | {r['payoff_ratio']:4.2f}x | {r['max_dd']:5.1f}%")
print("=" * 125)

print("\n📊 DETAILED EXECUTION AUDIT:")
for label, r in [("60-Day Stress", r_60d), ("1-Year Full Cycle", r_1yr)]:
    print(f"\n▶️ {label}:")
    print(f"   • Total Trades: {r['trades']} ({r['wins']} Wins, {r['losses']} Losses)")
    print(f"   • Average Win: +{r['avg_win']:.2f}% | Average Loss: {r['avg_loss']:.2f}%")
    print(f"   • Payoff Ratio: {r['payoff_ratio']:.2f}x (Expectancy: {((r['win_rate']/100)*r['avg_win'] + ((100-r['win_rate'])/100)*r['avg_loss']):+.2f}% / trade)")
    print(f"   • Max Portfolio Drawdown: {r['max_dd']:.1f}%")
    print(f"   • Annualized Cash-Flow XIRR: {r['xirr']:+.1f}%")
