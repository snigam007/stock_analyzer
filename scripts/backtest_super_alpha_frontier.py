"""
Quantitative Exploration Suite: Next-Gen Alpha Engines & Re-Engineered Smart Capital Recycler.
Evaluating:
1. Re-Engineered Smart Capital Recycler (Pyramids winners first, checks Nifty 50-EMA, 20D high confirmation)
2. Quality Momentum Ratio (Sortino/Smoothness: Ret / Volatility)
3. Jesse Livermore Winner Pyramiding (1.5x allocation on proven >20% gainers)
4. Tax-Alpha LTCG Bridge (3.5% trailing stop cushion on Day 315-365)
5. Mansfield Relative Strength vs NIFTY (+12% outperformance gate)
6. Combinations with 4-Stock Basket, 15% Step-Up, and Apex Dip/Skim Settings.
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
    enable_regime_adaptive_hurdle=False,
    enable_beta_stepladder=False,
    enable_fundamental_moat=False,
    enable_multi_lookback_blend=False,
    enable_momentum_convexity=False,
    enable_sector_duopoly=False,
    enable_tiered_trailing_ratchet=False,
    enable_intra_month_recycling=False,
    enable_dynamic_cap_expansion=False,
    expanded_cap_pct=55.0,
    enable_smart_capital_recycler=False,
    enable_quality_momentum=False,
    enable_livermore_pyramiding=False,
    enable_tax_ltcg_bridge=False,
    enable_mansfield_rs=False
)

CANDIDATES = [
    # ── Benchmarks ──
    ("👑 Benchmark 1: 62.25% Holy Grail (5 Stocks Base)", {}),
    ("💎 Benchmark 2: 63.46% Apex 1 (4 Stocks + Dip 95% + Skim 8%)", {
        "target_stock_count": 4, "dip_deploy_pct": 95.0,
        "skim_milestone_pct": 120.0, "skim_ratio_pct": 8.0
    }),
    ("🏆 Benchmark 3: 63.33% Centurion (4 Stocks + Step-Up 15% + Dip 95% + Skim 8%)", {
        "target_stock_count": 4, "annual_step_up_pct": 15.0, "dip_deploy_pct": 95.0,
        "skim_milestone_pct": 120.0, "skim_ratio_pct": 8.0
    }),

    # ── Individual Levers on Holy Grail 5-Stock Base ──
    ("⚡ Re-Engineered Smart Capital Recycler (5 Stocks)", {
        "enable_smart_capital_recycler": True
    }),
    ("⚡ Quality Momentum Ratio (5 Stocks, Ret/Vol)", {
        "enable_quality_momentum": True
    }),
    ("⚡ Jesse Livermore Pyramiding (5 Stocks, 1.5x on >20% gainers)", {
        "enable_livermore_pyramiding": True
    }),
    ("⚡ Tax-Alpha LTCG Bridge (5 Stocks, 3.5% Day 315-365 stop buffer)", {
        "enable_tax_ltcg_bridge": True
    }),
    ("⚡ Mansfield Relative Strength (5 Stocks, +12% vs NIFTY)", {
        "enable_mansfield_rs": True
    }),

    # ── Individual Levers on 4-Stock Concentration Basket ──
    ("🚀 4 Stocks + Re-Engineered Smart Capital Recycler", {
        "target_stock_count": 4, "enable_smart_capital_recycler": True
    }),
    ("🚀 4 Stocks + Quality Momentum Ratio", {
        "target_stock_count": 4, "enable_quality_momentum": True
    }),
    ("🚀 4 Stocks + Jesse Livermore Pyramiding", {
        "target_stock_count": 4, "enable_livermore_pyramiding": True
    }),
    ("🚀 4 Stocks + Tax-Alpha LTCG Bridge", {
        "target_stock_count": 4, "enable_tax_ltcg_bridge": True
    }),
    ("🚀 4 Stocks + Mansfield Relative Strength", {
        "target_stock_count": 4, "enable_mansfield_rs": True
    }),

    # ── Synergies with Apex 1 Settings (4 Stocks + Dip 95% + Skim 8%) ──
    ("💎 Apex + Smart Capital Recycler", {
        "target_stock_count": 4, "dip_deploy_pct": 95.0, "skim_milestone_pct": 120.0, "skim_ratio_pct": 8.0,
        "enable_smart_capital_recycler": True
    }),
    ("💎 Apex + Tax-Alpha LTCG Bridge", {
        "target_stock_count": 4, "dip_deploy_pct": 95.0, "skim_milestone_pct": 120.0, "skim_ratio_pct": 8.0,
        "enable_tax_ltcg_bridge": True
    }),
    ("💎 Apex + Jesse Livermore Pyramiding", {
        "target_stock_count": 4, "dip_deploy_pct": 95.0, "skim_milestone_pct": 120.0, "skim_ratio_pct": 8.0,
        "enable_livermore_pyramiding": True
    }),
    ("💎 Apex + Smart Recycler + Tax-Alpha LTCG Bridge", {
        "target_stock_count": 4, "dip_deploy_pct": 95.0, "skim_milestone_pct": 120.0, "skim_ratio_pct": 8.0,
        "enable_smart_capital_recycler": True, "enable_tax_ltcg_bridge": True
    }),
    ("💎 Apex + Smart Recycler + Livermore Pyramiding", {
        "target_stock_count": 4, "dip_deploy_pct": 95.0, "skim_milestone_pct": 120.0, "skim_ratio_pct": 8.0,
        "enable_smart_capital_recycler": True, "enable_livermore_pyramiding": True
    }),
    ("🔥 The Titan Apex: 4 Stocks + Dip 95% + Skim 8% + Smart Recycler + Livermore + Tax Bridge", {
        "target_stock_count": 4, "dip_deploy_pct": 95.0, "skim_milestone_pct": 120.0, "skim_ratio_pct": 8.0,
        "enable_smart_capital_recycler": True, "enable_livermore_pyramiding": True, "enable_tax_ltcg_bridge": True
    }),
    ("🏆 The Titan Centurion: Titan Apex + 15% Annual Step-Up", {
        "target_stock_count": 4, "annual_step_up_pct": 15.0, "dip_deploy_pct": 95.0, "skim_milestone_pct": 120.0, "skim_ratio_pct": 8.0,
        "enable_smart_capital_recycler": True, "enable_livermore_pyramiding": True, "enable_tax_ltcg_bridge": True
    }),
    ("🏆 The Titan Super-Centurion: Titan Apex + 20% Annual Step-Up", {
        "target_stock_count": 4, "annual_step_up_pct": 20.0, "dip_deploy_pct": 95.0, "skim_milestone_pct": 120.0, "skim_ratio_pct": 8.0,
        "enable_smart_capital_recycler": True, "enable_livermore_pyramiding": True, "enable_tax_ltcg_bridge": True
    })
]

print("=" * 135)
print("🚀 NEXT-GEN QUANTITATIVE ALPHA FRONTIER: RE-ENGINEERED RECYCLER & ASYMMETRIC DRIVERS (60-MONTH POINT-IN-TIME)")
print("=" * 135)

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
        smart_cnt = res.get("smart_recycled_count", 0)
        calmar = round(xirr / max(1.0, dd), 2)
        delta_bench = xirr - 62.25
        
        results.append({
            "name": name, "xirr": xirr, "delta": delta_bench,
            "corpus": corpus, "trades": trades, "win_rate": win_rate,
            "pf": pf, "payoff": payoff, "dd": dd, "calmar": calmar,
            "smart_cnt": smart_cnt
        })
        
        print(f"[{idx+1:02d}/{len(CANDIDATES):02d}] {name:<80} | XIRR: {xirr:5.2f}% ({delta_bench:+5.2f}%) | Corpus: ₹{corpus/1e5:5.2f}L | PF: {pf:4.2f} | Payoff: {payoff:5.2f}x | DD: {dd:4.1f}% | Recycled: {smart_cnt:2d} | ({elapsed:.1f}s)")
finally:
    session.close()

results.sort(key=lambda x: x["xirr"], reverse=True)

print("\n" + "=" * 145)
print("🏆 FINAL LEADERBOARD: NEXT-GEN ALPHA FRONTIER (RANKED BY NET XIRR)")
print("=" * 145)
print(f"{'Rank':<4} | {'Strategy Variant':<80} | {'Net XIRR':<10} | {'Δ vs 62.3%':<11} | {'Final Corpus':<14} | {'Max DD':<7} | {'PF':<5} | {'Payoff':<8} | {'Recycled':<8} | {'Calmar'}")
print("-" * 145)
for r_idx, r in enumerate(results):
    prefix = "👑" if r["xirr"] >= 70.0 else ("⭐" if r["xirr"] >= 65.0 else ("⚡" if r["xirr"] >= 62.25 else "  "))
    print(f"{r_idx+1:2d}   | {prefix} {r['name']:<78} | {r['xirr']:7.2f}%  | {r['delta']:+8.2f}%   | ₹{r['corpus']:12,.0f} | {r['dd']:5.1f}% | {r['pf']:4.2f} | {r['payoff']:5.2f}x | {r['smart_cnt']:8d} | {r['calmar']:5.2f}")
print("=" * 145)
