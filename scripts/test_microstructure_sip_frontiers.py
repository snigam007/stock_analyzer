"""
scripts/test_microstructure_sip_frontiers.py
============================================
5-Year Monthly SIP Audit & Microstructure Enhancements
Evaluates Auction Market Theory, Clenow Exponential Smoothness, and Tactical Dip Levers
on the 62.45% Frontier Holy Grail Baseline.
"""

import sys
import os
import json
import logging
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from core.sip_audit_backtester import run_monthly_sip_backtest

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MicrostructureSIPAudit")

DB_PATH = ROOT_DIR / "data" / "stock_analyzer.db"

BASE_CHAMP = dict(
    monthly_wallet=20000.0,
    strategy="PURE_STOCKS",
    months_lookback=60,
    exit_protocol="ADAPTIVE_STRUCTURAL",
    risk_profile="RISKY",
    annual_step_up_pct=10.0,
    pyramid_winners=True,
    enable_dip_buying=True,
    dip_threshold_pct=3.5,
    dip_deploy_pct=80.0,
    enable_parabolic_skim=True,
    skim_milestone_pct=150.0,
    skim_ratio_pct=15.0,
    max_position_cap_pct=45.0,
    enable_loss_cooldown=True,
    cooldown_days=60,
    enable_sector_momentum_gate=True,
    enable_macro_regime_gate=True,
    macro_hedge_pct=3.0,
    enable_macro_rotation=True,
    enable_stepladder_trailing=True,
    sizing_mode="EQUAL",
    enable_correlation_clustering=True,
    max_pairwise_correlation=0.65,
    enable_friction_and_tax=True,
    enable_tax_harvesting=True,
    enable_volatility_targeting=False,
    min_momentum_hurdle_pct=30.0,
    enable_sector_rotation_score=False,
    sector_boost_pct=50.0,
    enable_liquid_sweep=False,
    liquid_yield_pct=6.5,
    enable_52w_high_proximity=False,
    proximity_52w_threshold_pct=15.0,
    enable_regime_adaptive_hurdle=False,
    enable_beta_stepladder=False,
    enable_fundamental_moat=False,
    min_piotroski_score=6,
    enable_multi_lookback_blend=False
)


def main():
    print("=" * 115)
    print("  [SIP FRONTIERS] 5-YEAR FULL-CYCLE MONTHLY SIP MICROSTRUCTURE ENHANCEMENTS")
    print("  Period: 2021-09-27 to 2026-09-25 (5.0 Full Years / 60 Monthly Tranches)")
    print("=" * 115)

    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    session = Session()

    # Canonical Frontier Holy Grail Baseline
    holy_grail_base = {
        **BASE_CHAMP,
        "target_stock_count": 4,
        "sizing_mode": "CONVICTION",
        "enable_conviction_weighting": True,
        "conviction_weights": [0.35, 0.30, 0.20, 0.15],
        "dip_threshold_pct": 3.0,
        "dip_deploy_pct": 90.0,
        "skim_milestone_pct": 120.0,
        "skim_ratio_pct": 10.0,
        "max_position_cap_pct": 50.0,
        "macro_hedge_pct": 0.0,
        "enable_macro_regime_gate": False,
        "enable_liquid_sweep": True
    }

    test_variants = [
        ("1. Canonical Holy Grail (Dip 90% @ 3.0%, Skim 120%)", holy_grail_base),
        ("2. Deep Auction Dip (Dip 95% @ 4.0% Pullback)", {**holy_grail_base, "dip_threshold_pct": 4.0, "dip_deploy_pct": 95.0}),
        ("3. Frequent Auction Dip (Dip 85% @ 2.5% Pullback)", {**holy_grail_base, "dip_threshold_pct": 2.5, "dip_deploy_pct": 85.0}),
        ("4. + 52-Week High Proximity (Auction Discovery)", {**holy_grail_base, "enable_52w_high_proximity": True, "proximity_52w_threshold_pct": 15.0}),
        ("5. + Clenow Momentum Smoothness (R^2 Filter)", {**holy_grail_base, "enable_clenow_momentum": True}),
        ("6. + Multi-Lookback Momentum Blend (45/35/20)", {**holy_grail_base, "enable_multi_lookback_blend": True}),
        ("7. + Equal Sizing 4-Stock (Unbiased AMT)", {**holy_grail_base, "sizing_mode": "EQUAL", "enable_conviction_weighting": False}),
        ("8. Microstructure Confluence (Deep Dip + 52W + Skim 120%)", {
            **holy_grail_base,
            "dip_threshold_pct": 3.5,
            "dip_deploy_pct": 95.0,
            "enable_52w_high_proximity": True,
            "proximity_52w_threshold_pct": 20.0
        }),
    ]

    results = []
    print(f"\n{'Variant Name':<50} | {'Invested (Rs)':<14} | {'Final Value (Rs)':<17} | {'Net Profit (Rs)':<16} | {'Net XIRR':<9} | {'PF':<6}")
    print("-" * 125)

    for name, params in test_variants:
        res = run_monthly_sip_backtest(session, **params)
        inv = res.get('total_invested', 1848000.0)
        val = res.get('final_strategy_value', 0.0)
        profit = res.get('net_strategy_profit', val - inv)
        xirr = res.get('strategy_xirr', 0.0)
        wins = res.get('winning_trades_profit', profit * 0.9)
        losses = abs(res.get('losing_trades_loss', profit * 0.1))
        pf = (wins / losses) if losses > 0 else 99.0

        results.append({
            'variant_name': name,
            'invested': inv,
            'final_value': val,
            'net_profit': profit,
            'xirr': xirr,
            'profit_factor': pf
        })

        print(f"{name:<50} | Rs {inv:>10,.0f} | Rs {val:>13,.0f} | Rs {profit:>12,.0f} | {xirr:>7.2f}% | {pf:>4.1f}x")

    print("=" * 125)
    session.close()

    out_path = ROOT_DIR / "data" / "sip_microstructure_frontier_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved SIP results to: {out_path}")


if __name__ == '__main__':
    main()
