#!/usr/bin/env python3
"""
scripts/test_trending_market_multiplication.py

Tests Strategy 10 (Super-Alpha Hybrid) and top contenders across the 1-Year Full Cycle (2025-09-22 to 2026-09-22)
to verify how the strategy multiplies investments across normal and trending market regimes.
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

print("=" * 135)
print("🚀 TESTING 1-YEAR CYCLE MULTIPLICATION (2025-09-22 TO 2026-09-22)")
print("=" * 135)

models = [
    ("Super-Alpha Hybrid (Multi-Lookback + 3-Tier Runner, 6 Slots)", {
        "max_slots": 6,
        "entry_mode": "MULTI_LOOKBACK",
        "exit_mode": "THREE_TIER_SCALE",
        "t1_atr": 1.6,
        "t2_atr": 3.2,
        "t3_atr": 6.0,
        "sl_atr": 1.5,
        "time_stop_days": 6
    }),
    ("Multi-Lookback Z-Blend (Regime-Adaptive Exits, 8 Slots)", {
        "max_slots": 8,
        "entry_mode": "MULTI_LOOKBACK",
        "exit_mode": "REGIME_ADAPTIVE",
        "t1_atr": 1.8,
        "sl_atr": 1.5,
        "time_stop_days": 6
    }),
    ("Jesse Livermore Winner Pyramiding (Multi-Lookback, 6 Slots)", {
        "max_slots": 6,
        "entry_mode": "MULTI_LOOKBACK",
        "exit_mode": "REGIME_ADAPTIVE",
        "pyramid_on_win": True,
        "t1_atr": 1.8,
        "sl_atr": 1.5,
        "time_stop_days": 6
    }),
    ("Bimodal Regime-Adaptive (Clean Symmetrical 1.5 ATR)", {
        "max_slots": 8,
        "entry_mode": "TREND_MOMENTUM",
        "exit_mode": "REGIME_ADAPTIVE",
        "t1_atr": 1.5,
        "sl_atr": 1.5,
        "time_stop_days": 6
    })
]

results = []
for name, p in models:
    print(f"\n▶️ Running 1-Year Backtest: {name}...")
    r = run_spectrum_simulation(
        strategy_id="1YR_TEST",
        strategy_name=name,
        start_date="2025-09-22",
        end_date="2026-09-22",
        **p
    )
    results.append(r)
    print(f"   • Return: {r['return_pct']:+.2f}% | Alpha vs NIFTY: {r['alpha_pct']:+.2f}% | XIRR: {r['xirr']:+.1f}%")
    print(f"   • Win Rate: {r['win_rate']}% ({r['wins']}W / {r['losses']}L) | PF: {r['profit_factor']:.2f} | PR: {r['payoff_ratio']:.2f}x")
    print(f"   • Avg Win: +{r['avg_win']:.2f}% | Avg Loss: {r['avg_loss']:.2f}% | Max DD: {r['max_dd']:.1f}%")

print("\n" + "=" * 135)
print(f"{'Strategy Name':<65} | {'Return':<7} | {'Alpha':<7} | {'XIRR':<7} | {'Win %':<5} | {'PF':<5} | {'PR':<5} | {'Max DD':<6}")
print("-" * 135)
for r in results:
    print(f"{r['name']:<65} | {r['return_pct']:+5.2f}% | {r['alpha_pct']:+5.2f}% | {r['xirr']:+5.1f}% | {r['win_rate']:4.1f}% | {r['profit_factor']:4.2f} | {r['payoff_ratio']:4.2f}x | {r['max_dd']:5.1f}%")
print("=" * 135)
print(f"Benchmark NIFTY 50 1-Year Return: {results[0]['benchmark_pct']:+.2f}%\n")
