"""
Extensive Quantitative Grid & Synergy Backtest:
Evaluating 18+ Advanced Strategy Candidates to Elevate Net XIRR Beyond 55.70%,
Maximize Profit Factor & Payoff Ratio, and Compress Drawdowns.
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

CANDIDATES = [
    # ── Group 0: Current Champion Benchmark ──
    ("👑 Champ: Maximum Alpha v2.0 (Hurdle 30%, Equal, 5 Stocks, Cap 45%)", {}),
    
    # ── Group 1: Portfolio Concentration (Capital Density) ──
    ("🎯 1. Hyper-Concentrated Momentum (Top 3 Stocks @ 33.3% each)", {
        "target_stock_count": 3
    }),
    ("🎯 2. Concentrated 4-Stock Basket (@ 25% each)", {
        "target_stock_count": 4
    }),
    
    # ── Group 2: Momentum Hurdle Calibration (Quality of Momentum) ──
    ("🎯 3. High-Velocity Hurdle (+35% 6M Momentum Threshold)", {
        "min_momentum_hurdle_pct": 35.0
    }),
    ("🎯 4. Parabolic Momentum Hurdle (+40% 6M Momentum Threshold)", {
        "min_momentum_hurdle_pct": 40.0
    }),
    
    # ── Group 3: 52-Week High Proximity Continuation Filter ──
    ("🎯 5. 52W High Proximity Rocket (Within 5% of 52W High)", {
        "enable_52w_high_proximity": True, "proximity_52w_threshold_pct": 5.0
    }),
    ("🎯 6. 52W High Breakout Snipers (Within 2.5% of 52W High)", {
        "enable_52w_high_proximity": True, "proximity_52w_threshold_pct": 2.5
    }),
    
    # ── Group 4: Exponential Power-Conviction Sizing ──
    ("🎯 7. Exponential Conviction Sizing (35% #1, 25% #2, 20% #3, 12% #4, 8% #5)", {
        "sizing_mode": "CONVICTION",
        "enable_conviction_weighting": True,
        "conviction_weights": [0.35, 0.25, 0.20, 0.12, 0.08]
    }),
    ("🎯 8. Hyper-Conviction Sizing (40% #1, 25% #2, 18% #3, 11% #4, 6% #5)", {
        "sizing_mode": "CONVICTION",
        "enable_conviction_weighting": True,
        "conviction_weights": [0.40, 0.25, 0.18, 0.11, 0.06]
    }),
    
    # ── Group 5: Winner Position Cap Expansion (Let Multi-Baggers Compound) ──
    ("🎯 9. Winner Freedom Expansion (Max Cap 60% vs 45%)", {
        "max_position_cap_pct": 60.0
    }),
    ("🎯 10. Unshackled Compounding (Max Cap 75%)", {
        "max_position_cap_pct": 75.0
    }),
    
    # ── Group 6: Tactical Dip Buying & Parabolic Skimming Aggressiveness ──
    ("🎯 11. Hyper-Aggressive Dip Deployer (Deploy 100% Cash on 5% Pullback)", {
        "dip_threshold_pct": 5.0, "dip_deploy_pct": 100.0
    }),
    ("🎯 12. Accelerated Parabolic Skimmer (+100% Milestone @ 15% Trim)", {
        "skim_milestone_pct": 100.0, "skim_ratio_pct": 15.0
    }),
    
    # ── Group 7: Supercharged Sector Momentum Leadership ──
    ("🎯 13. Supercharged Sector Boost (+75% Top-3 Sector Tailwind)", {
        "enable_sector_rotation_score": True, "sector_boost_pct": 75.0
    }),
    
    # ── Group 8: Cash Sweeping Yield Enhancement ──
    ("⚡ 14. Champ + LiquidBees Cash Yield Auto-Sweep (6.5% Risk-Free)", {
        "enable_liquid_sweep": True, "liquid_yield_pct": 6.5
    }),
    
    # ── Group 9: Supreme High-Conviction Synergies ──
    ("💎 15. Apex Synergy A: Top 3 Stocks + Hurdle 35% + LiquidBees", {
        "target_stock_count": 3,
        "min_momentum_hurdle_pct": 35.0,
        "enable_liquid_sweep": True,
        "liquid_yield_pct": 6.5
    }),
    ("💎 16. Apex Synergy B: Top 3 Stocks + 52W High Proximity 5% + LiquidBees", {
        "target_stock_count": 3,
        "enable_52w_high_proximity": True,
        "proximity_52w_threshold_pct": 5.0,
        "enable_liquid_sweep": True,
        "liquid_yield_pct": 6.5
    }),
    ("💎 17. Apex Synergy C: Power Sizing (35/25/20/12/8) + Cap 60% + LiquidBees", {
        "sizing_mode": "CONVICTION",
        "enable_conviction_weighting": True,
        "conviction_weights": [0.35, 0.25, 0.20, 0.12, 0.08],
        "max_position_cap_pct": 60.0,
        "enable_liquid_sweep": True,
        "liquid_yield_pct": 6.5
    }),
    ("🏆 18. The Grand Slam Alpha Monster (Top 3 Stocks + Hurdle 35% + Cap 60% + LiquidBees)", {
        "target_stock_count": 3,
        "min_momentum_hurdle_pct": 35.0,
        "max_position_cap_pct": 60.0,
        "enable_liquid_sweep": True,
        "liquid_yield_pct": 6.5
    }),
]

def run_extensive_backtests():
    print("=" * 125)
    print("🚀 EXTENSIVE QUANTITATIVE GRID: 18 ADVANCED ALPHA FRONTIERS (60-MONTH SIMULATION)")
    print("=" * 125)
    
    session = Session()
    results = []
    
    for idx, (name, overrides) in enumerate(CANDIDATES, 1):
        cfg = dict(CHAMP_KWARGS)
        cfg.update(overrides)
        
        t0 = time.time()
        try:
            res = run_monthly_sip_backtest(session, **cfg)
            dur = time.time() - t0
            
            xirr = res.get("strategy_xirr", 0.0)
            corpus = res.get("final_strategy_value", 0.0)
            invested = res.get("total_invested", 0.0)
            net_profit = corpus - invested
            dd = res.get("max_drawdown_pct", 0.0)
            pf = res.get("profit_factor", 0.0)
            payoff = res.get("payoff_ratio", 0.0)
            win_rate = res.get("win_rate", 0.0)
            trades = res.get("total_trades", 0)
            
            # Calmar Ratio approximation (XIRR / Max DD)
            calmar = round(xirr / max(0.1, dd), 2)
            
            delta_xirr = xirr - 55.70
            sign = "+" if delta_xirr >= 0 else ""
            delta_str = f"({sign}{delta_xirr:.2f}%)"
            
            print(f"[{idx:02d}/{len(CANDIDATES):02d}] {name[:68]:<68} | XIRR: {xirr:5.2f}% {delta_str:<9} | Corpus: ₹{corpus/1e5:5.2f}L | PF: {pf:4.2f} | Payoff: {payoff:5.2f}x | DD: {dd:4.1f}% | ({dur:.1f}s)", flush=True)
            
            results.append({
                "name": name,
                "xirr": xirr,
                "delta_xirr": delta_xirr,
                "corpus": corpus,
                "invested": invested,
                "net_profit": net_profit,
                "dd": dd,
                "pf": pf,
                "payoff": payoff,
                "win_rate": win_rate,
                "trades": trades,
                "calmar": calmar,
                "dur": dur
            })
        except Exception as e:
            print(f"[{idx:02d}/{len(CANDIDATES):02d}] ❌ {name}: ERROR: {e}", flush=True)
            import traceback
            traceback.print_exc()
            
    session.close()
    
    # Sort by Net XIRR descending
    sorted_by_xirr = sorted(results, key=lambda r: r["xirr"], reverse=True)
    
    print("\n" + "=" * 135)
    print("🏆 FINAL LEADERBOARD: RANKED BY NET XIRR (60-MONTH POINT-IN-TIME EMPIRICAL PROOF)")
    print("=" * 135)
    print(f"{'Rank':<4} | {'Strategy Variant':<68} | {'Net XIRR':<10} | {'Δ vs Champ':<11} | {'Final Corpus':<14} | {'Max DD':<7} | {'PF':<5} | {'Payoff':<7} | {'Calmar':<6}")
    print("-" * 135)
    for rank, r in enumerate(sorted_by_xirr, 1):
        champ_badge = "👑 " if rank == 1 else ("⚡ " if r['delta_xirr'] > 0 else "   ")
        sign = "+" if r['delta_xirr'] >= 0 else ""
        d_str = f"{sign}{r['delta_xirr']:.2f}%"
        print(f"{rank:>2}   | {champ_badge}{r['name'][:64]:<64} | {r['xirr']:>7.2f}%  | {d_str:>9}   | ₹{r['corpus']:>12,.0f} | {r['dd']:>5.1f}% | {r['pf']:>4.2f} | {r['payoff']:>5.2f}x | {r['calmar']:>5.2f}")
    print("=" * 135)

if __name__ == "__main__":
    run_extensive_backtests()
