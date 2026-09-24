import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.sip_audit_backtester import run_monthly_sip_backtest

DB_PATH = "data/stock_analyzer.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine)

CHAMP_KWARGS = dict(
    monthly_wallet=20000.0,
    strategy="PURE_STOCKS",
    months_lookback=60,
    exit_protocol="ADAPTIVE_STRUCTURAL",
    risk_profile="RISKY",
    annual_step_up_pct=10.0,
    pyramid_winners=True,
    enable_dip_buying=True,
    dip_threshold_pct=4.0,
    dip_deploy_pct=70.0,
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
    enable_3tier_harvest=False,
    enable_clenow_momentum=False,
    enable_breadth_gate=True,
    target_stock_count=5,
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

probes = [
    ("👑 Champ Baseline (Hurdle 30%, Equal, Cap 45%)", {}),
    ("⚡ Hurdle 25% (Earlier breakout participation)", {"min_momentum_hurdle_pct": 25.0}),
    ("⚡ Hurdle 28% (Optimal sweet spot calibration)", {"min_momentum_hurdle_pct": 28.0}),
    ("⚡ Dip Deployer: 80% on 3.5% Dip", {"dip_threshold_pct": 3.5, "dip_deploy_pct": 80.0}),
    ("⚡ Dip Deployer: 90% on 4.0% Dip", {"dip_threshold_pct": 4.0, "dip_deploy_pct": 90.0}),
    ("⚡ Skim Milestone 120% @ 10% Trim", {"skim_milestone_pct": 120.0, "skim_ratio_pct": 10.0}),
    ("⚡ Macro Hedge 2.0% (Lower drag in bull runs)", {"macro_hedge_pct": 2.0}),
    ("⚡ Macro Hedge 0.0% (Zero hedge pure alpha)", {"macro_hedge_pct": 0.0, "enable_macro_regime_gate": False}),
]

print("Running micro-probes for alpha elevation...")
session = Session()
try:
    for name, overrides in probes:
        cfg = CHAMP_KWARGS.copy()
        cfg.update(overrides)
        res = run_monthly_sip_backtest(session, **cfg)
        xirr = res.get("strategy_xirr", 0.0)
        corpus = res.get("final_strategy_value", 0.0)
        pf = res.get("profit_factor", 0.0)
        payoff = res.get("payoff_ratio", 0.0)
        dd = res.get("max_drawdown_pct", 0.0)
        delta = xirr - 55.70
        print(f"{name:<48} | XIRR: {xirr:5.2f}% ({delta:+5.2f}%) | Corpus: Rs.{corpus/1e5:5.2f}L | PF: {pf:4.2f} | Payoff: {payoff:5.2f}x | DD: {dd:4.1f}%")
finally:
    session.close()
