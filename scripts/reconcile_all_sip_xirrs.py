"""
scripts/reconcile_all_sip_xirrs.py
==================================
Reconciles every SIP XIRR baseline across the codebase:
1. 14.8% (from unified_walkforward_audit_report.json / run_5year_fullcycle_walkforward_audit.py)
2. 51.7% - 53.5% (current run of holy_grail_params on latest db snapshot)
3. 56.6% (BASE_CHAMP with 3% Gold hedge)
4. 60.8% (The 60%+ Frontier Holy Grail: 90% dip @ 3%, 10% skim @ 120%)
5. 62.7% - 62.9% (Rapid Micro-Dip / Apex Quad Alpha Champion)
"""

import sys
import os
import json
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from db.database import get_global_engine, get_session
from core.sip_audit_backtester import run_monthly_sip_backtest
from scripts.backtest_60_plus_alpha_frontiers import BASE_CHAMP

engine = get_global_engine()
session = get_session(engine)

configs = [
    {
        "name": "1. UI Dashboard Verified Champion (verify_sip_backtest_and_walkforward.py)",
        "params": {
            **BASE_CHAMP,
            "target_stock_count": 4,
            "monthly_wallet": 20000.0,
            "annual_step_up_pct": 10.0,
            "months_lookback": 60,
            "sizing_mode": "CONVICTION",
            "enable_conviction_weighting": True,
            "conviction_weights": [0.35, 0.28, 0.22, 0.15],
            "dip_threshold_pct": 3.0,
            "dip_deploy_pct": 90.0,
            "skim_milestone_pct": 120.0,
            "skim_ratio_pct": 10.0,
            "max_position_cap_pct": 50.0,
            "macro_hedge_pct": 0.0,
            "enable_macro_regime_gate": False,
            "enable_liquid_sweep": True,
            "liquid_yield_pct": 6.5
        }
    },
    {
        "name": "2. Rapid Micro-Dip Champion (62.9% in backtest_60_plus_alpha_frontiers.py)",
        "params": {
            **BASE_CHAMP,
            "target_stock_count": 4,
            "monthly_wallet": 20000.0,
            "annual_step_up_pct": 10.0,
            "months_lookback": 60,
            "dip_threshold_pct": 2.5,
            "dip_deploy_pct": 75.0,
            "macro_hedge_pct": 0.0,
            "enable_macro_regime_gate": False,
            "enable_liquid_sweep": True
        }
    },
    {
        "name": "3. The 60%+ Frontier Holy Grail (Variant 17)",
        "params": {
            **BASE_CHAMP,
            "target_stock_count": 4,
            "monthly_wallet": 20000.0,
            "annual_step_up_pct": 10.0,
            "months_lookback": 60,
            "dip_threshold_pct": 3.0,
            "dip_deploy_pct": 90.0,
            "skim_milestone_pct": 120.0,
            "skim_ratio_pct": 10.0,
            "max_position_cap_pct": 50.0,
            "macro_hedge_pct": 0.0,
            "enable_macro_regime_gate": False,
            "enable_liquid_sweep": True
        }
    },
    {
        "name": "4. BASE_CHAMP Classic (with 3% Gold Hedge Drag)",
        "params": {
            **BASE_CHAMP,
            "months_lookback": 60
        }
    }
]

print("=" * 110)
print(" 🔍 RECONCILING ALL SIP XIRR FIGURES ACROSS SCRIPTS (POINT-IN-TIME AUDIT)")
print("=" * 110)
for c in configs:
    res = run_monthly_sip_backtest(session, **c["params"])
    xirr = res.get("strategy_xirr", 0.0)
    corpus = res.get("final_strategy_value", 0.0)
    inv = res.get("total_invested", 0.0)
    pf = res.get("profit_factor", 0.0)
    dd = res.get("max_drawdown_pct", 0.0)
    print(f"{c['name']}")
    print(f"   -> Net XIRR: {xirr:.2f}% | Final Corpus: Rs. {corpus:,.2f} | Invested: Rs. {inv:,.2f} | PF: {pf:.2f}x | MaxDD: {dd:.1f}%")
    print("-" * 110)

session.close()
