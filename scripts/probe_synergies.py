import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.sip_audit_backtester import run_monthly_sip_backtest

DB_PATH = "data/stock_analyzer.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine)

from scripts.probe_hyper_alpha import CHAMP_KWARGS

synergies = [
    ("👑 Champ Baseline (55.70%)", {}),
    ("🚀 Synergy 1: Dip 80% on 3.5% + Skim 120% @ 10% Trim", {
        "dip_threshold_pct": 3.5, "dip_deploy_pct": 80.0,
        "skim_milestone_pct": 120.0, "skim_ratio_pct": 10.0
    }),
    ("🚀 Synergy 2: Dip 80% on 3.5% + Skim 120% @ 10% Trim + Zero Hedge", {
        "dip_threshold_pct": 3.5, "dip_deploy_pct": 80.0,
        "skim_milestone_pct": 120.0, "skim_ratio_pct": 10.0,
        "macro_hedge_pct": 0.0, "enable_macro_regime_gate": False
    }),
    ("🚀 Synergy 3: Dip 85% on 3.5% + Skim 120% @ 10% Trim + LiquidBees 6.5%", {
        "dip_threshold_pct": 3.5, "dip_deploy_pct": 85.0,
        "skim_milestone_pct": 120.0, "skim_ratio_pct": 10.0,
        "enable_liquid_sweep": True, "liquid_yield_pct": 6.5
    }),
    ("🚀 Synergy 4: Dip 80% on 3.5% + Skim 100% @ 10% Trim + Hurdle 28%", {
        "dip_threshold_pct": 3.5, "dip_deploy_pct": 80.0,
        "skim_milestone_pct": 100.0, "skim_ratio_pct": 10.0,
        "min_momentum_hurdle_pct": 28.0
    }),
]

print("Running Synergy Grand Finales...")
session = Session()
try:
    for name, overrides in synergies:
        cfg = CHAMP_KWARGS.copy()
        cfg.update(overrides)
        res = run_monthly_sip_backtest(session, **cfg)
        xirr = res.get("strategy_xirr", 0.0)
        corpus = res.get("final_strategy_value", 0.0)
        pf = res.get("profit_factor", 0.0)
        payoff = res.get("payoff_ratio", 0.0)
        dd = res.get("max_drawdown_pct", 0.0)
        delta = xirr - 55.70
        print(f"{name:<68} | XIRR: {xirr:5.2f}% ({delta:+5.2f}%) | Corpus: Rs.{corpus/1e5:5.2f}L | PF: {pf:4.2f} | Payoff: {payoff:5.2f}x | DD: {dd:4.1f}%")
finally:
    session.close()
