"""
Quantitative Exploration Suite: 18 Advanced Levers & Synergies Targeting 70%+ Net XIRR.

Testing:
1. Baseline: 62.25% Holy Grail Benchmark (5 stocks, 50% cap, 90% @ 3% dip, 120% @ 10% skim, LiquidBees, 0% hedge)
2. 4-Stock Concentration Basket with Holy Grail settings
3. 3-Stock Hyper-Concentration Basket with Holy Grail settings
4. Dip Deployer Hyper-Aggressive: 95% Cash on 2.5% Dip
5. Dip Deployer Hyper-Aggressive: 95% Cash on 3.0% Dip
6. Skim Milestone Optimization: +110% @ 8% Trim
7. Skim Milestone Optimization: +100% @ 8% Trim
8. Skim Milestone Optimization: +120% @ 8% Trim
9. Sizing Mode: Power Conviction (35/25/20/12/8) + Holy Grail
10. Sizing Mode: Hyper Conviction (40/25/18/11/6) + Holy Grail
11. Annual Step-Up: 15% (vs 10%) + Holy Grail
12. Annual Step-Up: 20% (vs 10%) + Holy Grail
13. Combined Apex 1: 4-Stock Basket + Dip 95% (3.0%) + Skim 120% (8%) + Cap 50%
14. Combined Apex 2: 3-Stock Basket + Dip 90% (3.0%) + Skim 120% (10%) + Cap 50%
15. Combined Apex 3: 3-Stock Basket + Dip 95% (2.5%) + Skim 110% (8%) + Cap 55%
16. Combined Apex 4: 4-Stock Basket + Dip 90% (3.0%) + Skim 110% (8%) + Cap 50%
17. The 70%+ Centurion Alpha: 4-Stock Basket + Step-Up 15% + Dip 95% (3.0%) + Skim 120% (8%) + Cap 50%
18. The 70%+ Super-Centurion Alpha: 3-Stock Basket + Step-Up 15% + Dip 95% (2.5%) + Skim 110% (8%) + Cap 55%
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

HOLY_GRAIL_BASE = dict(
    monthly_wallet=20000.0,
    strategy="PURE_STOCKS",
    months_lookback=60,
    exit_protocol="ADAPTIVE_STRUCTURAL",
    risk_profile="RISKY",
    annual_step_up_pct=10.0,
    pyramid_winners=True,
    enable_dip_buying=True,
    dip_threshold_pct=3.0,
    dip_deploy_pct=90.0,
    enable_parabolic_skim=True,
    skim_milestone_pct=120.0,
    skim_ratio_pct=10.0,
    max_position_cap_pct=50.0,
    enable_loss_cooldown=True,
    cooldown_days=60,
    enable_sector_momentum_gate=True,
    enable_macro_regime_gate=False,
    macro_hedge_pct=0.0,
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
    enable_liquid_sweep=True,
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
    # ── Benchmark: 62.25% Holy Grail ──
    ("👑 Current Benchmark: 62.25% Holy Grail (5 Stocks, Cap 50%, Dip 90% @ 3%)", {}),
    
    # ── Group 1: Concentration Variations (4 Stocks & 3 Stocks) ──
    ("🎯 4-Stock Concentration Basket (@ 25% eq) + Holy Grail Base", {
        "target_stock_count": 4
    }),
    ("🎯 3-Stock Hyper-Concentration Basket (@ 33.3% eq) + Holy Grail Base", {
        "target_stock_count": 3
    }),
    
    # ── Group 2: Ultra-Sensitive Dip Deployer Calibrations ──
    ("⚡ Dip Deployer: 95% Cash on 3.0% Dip", {
        "dip_deploy_pct": 95.0
    }),
    ("⚡ Dip Deployer: 95% Cash on 2.5% Dip", {
        "dip_threshold_pct": 2.5, "dip_deploy_pct": 95.0
    }),
    ("⚡ Dip Deployer: 100% Cash on 2.8% Dip", {
        "dip_threshold_pct": 2.8, "dip_deploy_pct": 100.0
    }),
    
    # ── Group 3: Skim Milestone Refinements ──
    ("💰 Skim Milestone +110% @ 8% Trim", {
        "skim_milestone_pct": 110.0, "skim_ratio_pct": 8.0
    }),
    ("💰 Skim Milestone +100% @ 8% Trim", {
        "skim_milestone_pct": 100.0, "skim_ratio_pct": 8.0
    }),
    ("💰 Skim Milestone +120% @ 8% Trim", {
        "skim_milestone_pct": 120.0, "skim_ratio_pct": 8.0
    }),
    
    # ── Group 4: Conviction Power Sizing ──
    ("⚖️ Conviction Power Sizing (35/25/20/12/8) + Holy Grail", {
        "sizing_mode": "CONVICTION"
    }),
    
    # ── Group 5: Annual Step-Up Acceleration ──
    ("📈 Annual Step-Up: +15%/yr (vs 10%)", {
        "annual_step_up_pct": 15.0
    }),
    ("📈 Annual Step-Up: +20%/yr (vs 10%)", {
        "annual_step_up_pct": 20.0
    }),
    
    # ── Group 6: Grand Apex Synergies Targeting 70%+ Alpha ──
    ("💎 Apex 1: 4 Stocks + Dip 95% (3.0%) + Skim 120% (8%) + Cap 50%", {
        "target_stock_count": 4, "dip_deploy_pct": 95.0,
        "skim_milestone_pct": 120.0, "skim_ratio_pct": 8.0
    }),
    ("💎 Apex 2: 3 Stocks + Dip 90% (3.0%) + Skim 120% (10%) + Cap 50%", {
        "target_stock_count": 3,
        "skim_milestone_pct": 120.0, "skim_ratio_pct": 10.0
    }),
    ("💎 Apex 3: 3 Stocks + Dip 95% (2.5%) + Skim 110% (8%) + Cap 55%", {
        "target_stock_count": 3, "dip_threshold_pct": 2.5, "dip_deploy_pct": 95.0,
        "skim_milestone_pct": 110.0, "skim_ratio_pct": 8.0, "max_position_cap_pct": 55.0
    }),
    ("💎 Apex 4: 4 Stocks + Dip 95% (2.8%) + Skim 110% (8%) + Cap 52%", {
        "target_stock_count": 4, "dip_threshold_pct": 2.8, "dip_deploy_pct": 95.0,
        "skim_milestone_pct": 110.0, "skim_ratio_pct": 8.0, "max_position_cap_pct": 52.0
    }),
    ("🏆 The 70%+ Centurion Alpha: 4 Stocks + Step-Up 15% + Dip 95% (3.0%) + Skim 120% (8%)", {
        "target_stock_count": 4, "annual_step_up_pct": 15.0,
        "dip_deploy_pct": 95.0, "skim_milestone_pct": 120.0, "skim_ratio_pct": 8.0
    }),
    ("🏆 The 70%+ Super-Centurion Alpha: 3 Stocks + Step-Up 15% + Dip 95% (2.5%) + Skim 110% (8%) + Cap 55%", {
        "target_stock_count": 3, "annual_step_up_pct": 15.0, "dip_threshold_pct": 2.5, "dip_deploy_pct": 95.0,
        "skim_milestone_pct": 110.0, "skim_ratio_pct": 8.0, "max_position_cap_pct": 55.0
    }),
]

print("=" * 125)
print("🚀 TARGETING 70.0%+ NET XIRR: 18 ADVANCED QUANTITATIVE ALPHA CANDIDATES (60-MONTH POINT-IN-TIME BACKTEST)")
print("=" * 125)

results = []
session = Session()
try:
    for idx, (name, overrides) in enumerate(CANDIDATES):
        t0 = time.time()
        cfg = HOLY_GRAIL_BASE.copy()
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
        delta_bench = xirr - 62.25
        
        results.append({
            "name": name, "xirr": xirr, "delta": delta_bench,
            "corpus": corpus, "trades": trades, "win_rate": win_rate,
            "pf": pf, "payoff": payoff, "dd": dd, "calmar": calmar
        })
        
        print(f"[{idx+1:02d}/{len(CANDIDATES):02d}] {name:<80} | XIRR: {xirr:5.2f}% ({delta_bench:+5.2f}%) | Corpus: ₹{corpus/1e5:5.2f}L | PF: {pf:4.2f} | Payoff: {payoff:5.2f}x | DD: {dd:4.1f}% | ({elapsed:.1f}s)")
finally:
    session.close()

results.sort(key=lambda x: x["xirr"], reverse=True)

print("\n" + "=" * 135)
print("🏆 FINAL LEADERBOARD: TARGETING 70%+ NET XIRR (RANKED BY NET XIRR)")
print("=" * 135)
print(f"{'Rank':<4} | {'Strategy Variant':<80} | {'Net XIRR':<10} | {'Δ vs 62.3%':<11} | {'Final Corpus':<14} | {'Max DD':<7} | {'PF':<5} | {'Payoff':<8} | {'Calmar'}")
print("-" * 135)
for r_idx, r in enumerate(results):
    prefix = "👑" if r["xirr"] >= 70.0 else ("⭐" if r["xirr"] >= 65.0 else ("⚡" if r["xirr"] >= 62.25 else "  "))
    print(f"{r_idx+1:2d}   | {prefix} {r['name']:<78} | {r['xirr']:7.2f}%  | {r['delta']:+8.2f}%   | ₹{r['corpus']:12,.0f} | {r['dd']:5.1f}% | {r['pf']:4.2f} | {r['payoff']:5.2f}x | {r['calmar']:5.2f}")
print("=" * 135)
