"""
Quantitative Exploration Suite: 20 Advanced Levers & Synergies Targeting 70.0%+ Net XIRR.
Evaluates:
- Momentum Convexity / Acceleration (Mom 3M >= 0.50 * Mom 6M)
- Sector Duopoly Engine (allows up to 2 stocks in #1 trending sector)
- Stage-Calibrated Tiered Trailing Ratchet (14% base -> 10% mid -> 7% parabolic)
- Intra-Month Capital Recycler (next-day redeployment of stopped/skimmed capital)
- Dynamic Runner Cap Expansion (55% cap on 3-baggers)
- 4-Stock and 3-Stock Concentration Baskets
- Step-Up Acceleration (15% and 20%)
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
    # New Levers defaulted to False in base:
    enable_momentum_convexity=False,
    min_convexity_ratio=0.50,
    enable_sector_duopoly=False,
    sector_duopoly_max=2,
    enable_tiered_trailing_ratchet=False,
    enable_intra_month_recycling=False,
    enable_dynamic_cap_expansion=False,
    expanded_cap_pct=55.0
)

CANDIDATES = [
    # ── Benchmark Baselines ──
    ("👑 Benchmark: 62.25% Holy Grail (5 Stocks, Base)", {}),
    ("🎯 4-Stock Concentration Basket (Holy Grail Base)", {"target_stock_count": 4}),

    # ── Individual Levers on 5-Stock Base ──
    ("⚡ Lever 10: Momentum Convexity Filter (3M >= 0.50 * 6M)", {"enable_momentum_convexity": True, "min_convexity_ratio": 0.50}),
    ("⚡ Lever 10B: Momentum Convexity Aggressive (3M >= 0.55 * 6M)", {"enable_momentum_convexity": True, "min_convexity_ratio": 0.55}),
    ("⚡ Lever 11: Sector Duopoly Engine (Max 2 in #1 Sector)", {"enable_sector_duopoly": True, "sector_duopoly_max": 2}),
    ("⚡ Lever 12: Stage Tiered Trailing Ratchet (14%/10%/7%)", {"enable_tiered_trailing_ratchet": True}),
    ("⚡ Lever 13: Intra-Month Capital Recycler", {"enable_intra_month_recycling": True}),
    ("⚡ Lever 14: Dynamic Runner Cap Expansion (55% on 3x)", {"enable_dynamic_cap_expansion": True, "expanded_cap_pct": 55.0}),

    # ── Individual Levers on 4-Stock Basket ──
    ("💎 4 Stocks + Intra-Month Capital Recycler", {
        "target_stock_count": 4, "enable_intra_month_recycling": True
    }),
    ("💎 4 Stocks + Sector Duopoly Engine", {
        "target_stock_count": 4, "enable_sector_duopoly": True
    }),
    ("💎 4 Stocks + Momentum Convexity Filter", {
        "target_stock_count": 4, "enable_momentum_convexity": True, "min_convexity_ratio": 0.50
    }),
    ("💎 4 Stocks + Tiered Trailing Ratchet", {
        "target_stock_count": 4, "enable_tiered_trailing_ratchet": True
    }),

    # ── High-Synergy Combinations (4 Stocks) ──
    ("🚀 Synergy 1: 4 Stocks + Recycler + Duopoly", {
        "target_stock_count": 4, "enable_intra_month_recycling": True, "enable_sector_duopoly": True
    }),
    ("🚀 Synergy 2: 4 Stocks + Recycler + Convexity", {
        "target_stock_count": 4, "enable_intra_month_recycling": True, "enable_momentum_convexity": True
    }),
    ("🚀 Synergy 3: 4 Stocks + Recycler + Tiered Ratchet", {
        "target_stock_count": 4, "enable_intra_month_recycling": True, "enable_tiered_trailing_ratchet": True
    }),
    ("🚀 Synergy 4: 4 Stocks + Recycler + Duopoly + Convexity", {
        "target_stock_count": 4, "enable_intra_month_recycling": True, "enable_sector_duopoly": True, "enable_momentum_convexity": True
    }),
    ("🏆 Synergy 5: The Grand Apex Quintet (4 Stocks + Recycler + Duopoly + Convexity + Ratchet + Cap 55%)", {
        "target_stock_count": 4,
        "enable_intra_month_recycling": True,
        "enable_sector_duopoly": True,
        "enable_momentum_convexity": True,
        "enable_tiered_trailing_ratchet": True,
        "enable_dynamic_cap_expansion": True,
        "expanded_cap_pct": 55.0
    }),
    ("🏆 Synergy 6: Grand Apex Quintet + 15% Annual Step-Up", {
        "target_stock_count": 4,
        "annual_step_up_pct": 15.0,
        "enable_intra_month_recycling": True,
        "enable_sector_duopoly": True,
        "enable_momentum_convexity": True,
        "enable_tiered_trailing_ratchet": True,
        "enable_dynamic_cap_expansion": True,
        "expanded_cap_pct": 55.0
    }),
    ("🏆 Synergy 7: Grand Apex Quintet + 20% Annual Step-Up", {
        "target_stock_count": 4,
        "annual_step_up_pct": 20.0,
        "enable_intra_month_recycling": True,
        "enable_sector_duopoly": True,
        "enable_momentum_convexity": True,
        "enable_tiered_trailing_ratchet": True,
        "enable_dynamic_cap_expansion": True,
        "expanded_cap_pct": 55.0
    }),

    # ── Ultra Concentration Synergies (3 Stocks) ──
    ("🔥 Synergy 8: 3-Stock Ultra Basket + Recycler + Duopoly + Convexity + Ratchet", {
        "target_stock_count": 3,
        "enable_intra_month_recycling": True,
        "enable_sector_duopoly": True,
        "enable_momentum_convexity": True,
        "enable_tiered_trailing_ratchet": True,
        "enable_dynamic_cap_expansion": True,
        "expanded_cap_pct": 55.0
    }),
    ("🔥 Synergy 9: 3-Stock Ultra Basket + Step-Up 15% + Recycler + Duopoly + Convexity", {
        "target_stock_count": 3,
        "annual_step_up_pct": 15.0,
        "enable_intra_month_recycling": True,
        "enable_sector_duopoly": True,
        "enable_momentum_convexity": True,
        "enable_tiered_trailing_ratchet": True,
        "enable_dynamic_cap_expansion": True,
        "expanded_cap_pct": 55.0
    })
]

print("=" * 135)
print("🚀 QUANTITATIVE EXPLORATION SUITE: 20 STRATEGIES TARGETING 70%+ NET XIRR (60-MONTH POINT-IN-TIME)")
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
        recycled_cnt = res.get("recycled_trades_count", 0)
        calmar = round(xirr / max(1.0, dd), 2)
        delta_bench = xirr - 62.25
        
        results.append({
            "name": name, "xirr": xirr, "delta": delta_bench,
            "corpus": corpus, "trades": trades, "win_rate": win_rate,
            "pf": pf, "payoff": payoff, "dd": dd, "calmar": calmar,
            "recycled_cnt": recycled_cnt
        })
        
        print(f"[{idx+1:02d}/{len(CANDIDATES):02d}] {name:<80} | XIRR: {xirr:5.2f}% ({delta_bench:+5.2f}%) | Corpus: ₹{corpus/1e5:5.2f}L | PF: {pf:4.2f} | Payoff: {payoff:5.2f}x | DD: {dd:4.1f}% | Recycled: {recycled_cnt:2d} | ({elapsed:.1f}s)")
finally:
    session.close()

results.sort(key=lambda x: x["xirr"], reverse=True)

print("\n" + "=" * 145)
print("🏆 FINAL LEADERBOARD: TARGETING 70%+ NET XIRR (RANKED BY NET XIRR)")
print("=" * 145)
print(f"{'Rank':<4} | {'Strategy Variant':<80} | {'Net XIRR':<10} | {'Δ vs 62.3%':<11} | {'Final Corpus':<14} | {'Max DD':<7} | {'PF':<5} | {'Payoff':<8} | {'Recycled':<8} | {'Calmar'}")
print("-" * 145)
for r_idx, r in enumerate(results):
    prefix = "👑" if r["xirr"] >= 70.0 else ("⭐" if r["xirr"] >= 65.0 else ("⚡" if r["xirr"] >= 62.25 else "  "))
    print(f"{r_idx+1:2d}   | {prefix} {r['name']:<78} | {r['xirr']:7.2f}%  | {r['delta']:+8.2f}%   | ₹{r['corpus']:12,.0f} | {r['dd']:5.1f}% | {r['pf']:4.2f} | {r['payoff']:5.2f}x | {r['recycled_cnt']:8d} | {r['calmar']:5.2f}")
print("=" * 145)
