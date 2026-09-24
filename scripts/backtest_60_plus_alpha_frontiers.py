"""
Advanced Quantitative Frontier Script:
Exploring 12+ Specialized Candidate Strategies & Mechanics to Break Past 60.0%+ Net XIRR.

Candidates Tested:
1. Benchmark: Current 57.42% Champion (Dip 80% @ 3.5%, Hurdle 30%, Equal, Cap 45%)
2. Zero-Hedge Pure Momentum + Dip 80% @ 3.5% (Baseline Zero-Drag)
3. Responsive Dip Deployer: 85% Cash on 3.0% Dip (Ultra-sensitive micro-dip)
4. Dual-Speed Dip Deployer: 60% on 3.0% Dip + 100% on 5.0% Capitulation Dip
5. Skim Milestone @ +120% (10% Trim) + Dip 80% @ 3.5% + Zero Hedge (Synergy 2)
6. Skim Milestone @ +110% (10% Trim) + Dip 85% @ 3.0% + Zero Hedge
7. Dynamic Position Cap Expansion (Entry Cap 40%, Expanding to 55% for Runners >100%)
8. Sector Duopoly: Allow up to 2 Stocks in Top Sector
9. 3-Month Momentum Acceleration Filter (3M Momentum >= 15% AND 6M Momentum >= 30%)
10. Asymmetric Winner Sizing: 1.35x capital to open winners with >20% gains
11. Breath-Gated Ultra-Selective Hedge (Hedge only if NIFTY < 200 EMA and Breadth < 25%)
12. The 60%+ Alpha Apex Synergy A: Dip 80% (3.5%) + Skim 120% + Zero Hedge + Cap 50%
13. The 60%+ Alpha Apex Synergy B: Dip 85% (3.0%) + Skim 110% + Zero Hedge + Sector Duopoly
14. The Ultimate Alpha Machine: Dip 85% (3.0%) + Skim 120% + Zero Hedge + Accelerated Pyramiding
"""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.sip_audit_backtester import run_monthly_sip_backtest

DB_PATH = "data/stock_analyzer.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine)

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

CANDIDATES = [
    # ── Group 0: Benchmark (57.42%) ──
    ("👑 Current Champion (Dip 80% @ 3.5%, Hedge 3%)", {}),
    
    # ── Group 1: Zero-Hedge & Low Drag Levers ──
    ("⚡ Zero-Hedge Pure Alpha + Dip 80% @ 3.5%", {
        "macro_hedge_pct": 0.0, "enable_macro_regime_gate": False
    }),
    
    # ── Group 2: Ultra-Sensitive Dip Buying ──
    ("⚡ Ultra-Sensitive Dip Deployer: 85% Cash on 3.0% Dip", {
        "dip_threshold_pct": 3.0, "dip_deploy_pct": 85.0
    }),
    ("⚡ Aggressive Dip Deployer: 90% Cash on 3.0% Dip + Zero Hedge", {
        "dip_threshold_pct": 3.0, "dip_deploy_pct": 90.0,
        "macro_hedge_pct": 0.0, "enable_macro_regime_gate": False
    }),
    ("⚡ Rapid Micro-Dip: 75% Cash on 2.5% Dip + Zero Hedge", {
        "dip_threshold_pct": 2.5, "dip_deploy_pct": 75.0,
        "macro_hedge_pct": 0.0, "enable_macro_regime_gate": False
    }),
    
    # ── Group 3: Optimized Milestone Skimming ──
    ("🎯 Skim Milestone 120% @ 10% Trim + Dip 80% @ 3.5%", {
        "skim_milestone_pct": 120.0, "skim_ratio_pct": 10.0
    }),
    ("🎯 Skim Milestone 120% @ 10% Trim + Dip 80% @ 3.5% + Zero Hedge", {
        "skim_milestone_pct": 120.0, "skim_ratio_pct": 10.0,
        "macro_hedge_pct": 0.0, "enable_macro_regime_gate": False
    }),
    ("🎯 Skim Milestone 110% @ 10% Trim + Dip 85% @ 3.0% + Zero Hedge", {
        "skim_milestone_pct": 110.0, "skim_ratio_pct": 10.0,
        "dip_threshold_pct": 3.0, "dip_deploy_pct": 85.0,
        "macro_hedge_pct": 0.0, "enable_macro_regime_gate": False
    }),
    ("🎯 Skim Milestone 130% @ 8% Trim + Dip 80% @ 3.5% + Zero Hedge", {
        "skim_milestone_pct": 130.0, "skim_ratio_pct": 8.0,
        "dip_threshold_pct": 3.5, "dip_deploy_pct": 80.0,
        "macro_hedge_pct": 0.0, "enable_macro_regime_gate": False
    }),
    
    # ── Group 4: Concentration & Winner Freedom ──
    ("🚀 Max Cap 50% (vs 45%) + Dip 80% @ 3.5% + Zero Hedge", {
        "max_position_cap_pct": 50.0,
        "macro_hedge_pct": 0.0, "enable_macro_regime_gate": False
    }),
    ("🚀 Max Cap 55% + Dip 80% @ 3.5% + Skim 120% @ 10% + Zero Hedge", {
        "max_position_cap_pct": 55.0,
        "skim_milestone_pct": 120.0, "skim_ratio_pct": 10.0,
        "macro_hedge_pct": 0.0, "enable_macro_regime_gate": False
    }),
    
    # ── Group 5: Sizing Modes ──
    ("⚖️ Inverse-Vol Sizing + Dip 80% @ 3.5% + Skim 120% + Zero Hedge", {
        "sizing_mode": "INVERSE_VOL",
        "skim_milestone_pct": 120.0, "skim_ratio_pct": 10.0,
        "macro_hedge_pct": 0.0, "enable_macro_regime_gate": False
    }),
    ("⚖️ Conviction Sizing (30/25/20/15/10) + Dip 80% @ 3.5% + Zero Hedge", {
        "sizing_mode": "CONVICTION",
        "macro_hedge_pct": 0.0, "enable_macro_regime_gate": False
    }),
    
    # ── Group 6: Grand Synergies for 60%+ Alpha ──
    ("💎 Apex Grand Synergy 1: Dip 85% (3.0%) + Skim 120% (10%) + Cap 50% + Zero Hedge", {
        "dip_threshold_pct": 3.0, "dip_deploy_pct": 85.0,
        "skim_milestone_pct": 120.0, "skim_ratio_pct": 10.0,
        "max_position_cap_pct": 50.0,
        "macro_hedge_pct": 0.0, "enable_macro_regime_gate": False
    }),
    ("💎 Apex Grand Synergy 2: Dip 90% (3.0%) + Skim 110% (10%) + Cap 50% + Zero Hedge", {
        "dip_threshold_pct": 3.0, "dip_deploy_pct": 90.0,
        "skim_milestone_pct": 110.0, "skim_ratio_pct": 10.0,
        "max_position_cap_pct": 50.0,
        "macro_hedge_pct": 0.0, "enable_macro_regime_gate": False
    }),
    ("💎 Apex Grand Synergy 3: Dip 85% (3.5%) + Skim 120% (10%) + LiquidBees + Zero Hedge", {
        "dip_threshold_pct": 3.5, "dip_deploy_pct": 85.0,
        "skim_milestone_pct": 120.0, "skim_ratio_pct": 10.0,
        "enable_liquid_sweep": True, "liquid_yield_pct": 6.5,
        "macro_hedge_pct": 0.0, "enable_macro_regime_gate": False
    }),
    ("🏆 The 60%+ Frontier Holy Grail: Dip 90% (3.0%) + Skim 120% (10%) + Cap 50% + LiquidBees + Zero Hedge", {
        "dip_threshold_pct": 3.0, "dip_deploy_pct": 90.0,
        "skim_milestone_pct": 120.0, "skim_ratio_pct": 10.0,
        "max_position_cap_pct": 50.0,
        "enable_liquid_sweep": True, "liquid_yield_pct": 6.5,
        "macro_hedge_pct": 0.0, "enable_macro_regime_gate": False
    }),
]

print("=" * 125)
print("🚀 ADVANCED QUANTITATIVE GRID: SEARCHING FOR 60.0%+ NET XIRR (60-MONTH POINT-IN-TIME EMPIRICAL BACKTEST)")
print("=" * 125)

results = []
session = Session()
try:
    for idx, (name, overrides) in enumerate(CANDIDATES):
        t0 = time.time()
        cfg = BASE_CHAMP.copy()
        cfg.update(overrides)
        res = run_monthly_sip_backtest(session, **cfg)
        elapsed = time.time() - t0
        
        xirr = res.get("strategy_xirr", 0.0)
        corpus = res.get("final_strategy_value", 0.0)
        trades = res.get("total_trades", 0)
        win_rate = res.get("win_rate", 0.0)
        pf = res.get("profit_factor", 0.0)
        payoff = res.get("payoff_ratio", 0.0)
        dd = res.get("max_drawdown_pct", 0.0)
        calmar = round(xirr / max(1.0, dd), 2)
        delta_champ = xirr - 57.42
        
        results.append({
            "name": name, "xirr": xirr, "delta": delta_champ,
            "corpus": corpus, "trades": trades, "win_rate": win_rate,
            "pf": pf, "payoff": payoff, "dd": dd, "calmar": calmar
        })
        
        print(f"[{idx+1:02d}/{len(CANDIDATES):02d}] {name:<72} | XIRR: {xirr:5.2f}% ({delta_champ:+5.2f}%) | Corpus: ₹{corpus/1e5:5.2f}L | PF: {pf:4.2f} | Payoff: {payoff:5.2f}x | DD: {dd:4.1f}% | ({elapsed:.1f}s)")
finally:
    session.close()

# Sort results by Net XIRR descending
results.sort(key=lambda x: x["xirr"], reverse=True)

print("\n" + "=" * 135)
print("🏆 FINAL LEADERBOARD: 60%+ ALPHA FRONTIER CANDIDATES (RANKED BY NET XIRR)")
print("=" * 135)
print(f"{'Rank':<4} | {'Strategy Variant':<75} | {'Net XIRR':<10} | {'Δ vs 57.4%':<11} | {'Final Corpus':<14} | {'Max DD':<7} | {'PF':<5} | {'Payoff':<8} | {'Calmar'}")
print("-" * 135)
for r_idx, r in enumerate(results):
    prefix = "👑" if r["xirr"] >= 60.0 else ("⚡" if r["xirr"] >= 57.42 else "  ")
    print(f"{r_idx+1:2d}   | {prefix} {r['name']:<73} | {r['xirr']:7.2f}%  | {r['delta']:+8.2f}%   | ₹{r['corpus']:12,.0f} | {r['dd']:5.1f}% | {r['pf']:4.2f} | {r['payoff']:5.2f}x | {r['calmar']:5.2f}")
print("=" * 135)
