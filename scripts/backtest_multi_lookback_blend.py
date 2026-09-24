"""
Empirical Backtest: Multi-Lookback Momentum Blend (12M + 6M + 3M)
Evaluates whether blending 12M (structural trend), 6M (core momentum), and 3M (recent acceleration)
improves or diversifies the 55.7% Champion Alpha strategy.
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
    enable_parabolic_skim=True,
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
    enable_regime_adaptive_hurdle=False,
    enable_beta_stepladder=False,
    enable_fundamental_moat=False,
    min_piotroski_score=6,
    enable_multi_lookback_blend=False
)

VARIANTS = [
    ("👑 Champ: Maximum Alpha v2.0 (Pure 6M Momentum)", {}),
    
    ("📈 Multi-Lookback Blend (45% 6M + 35% 12M + 20% 3M)", {
        "enable_multi_lookback_blend": True
    }),
    
    ("🛡️ Sector Shield + Multi-Lookback Blend", {
        "enable_sector_rotation_score": True,
        "sector_boost_pct": 50.0,
        "enable_multi_lookback_blend": True
    }),
    
    ("⚡ Multi-Lookback Blend + LiquidBees Cash Yield (6.5%)", {
        "enable_multi_lookback_blend": True,
        "enable_liquid_sweep": True,
        "liquid_yield_pct": 6.5
    }),
    
    ("💎 Multi-Lookback Blend + Beta Stepladder + LiquidBees", {
        "enable_multi_lookback_blend": True,
        "enable_beta_stepladder": True,
        "enable_liquid_sweep": True,
        "liquid_yield_pct": 6.5
    }),
    
    ("🏆 Apex All-In: Sector Shield + Multi-Lookback + Beta Stepladder + LiquidBees", {
        "enable_sector_rotation_score": True,
        "sector_boost_pct": 50.0,
        "enable_multi_lookback_blend": True,
        "enable_beta_stepladder": True,
        "enable_liquid_sweep": True,
        "liquid_yield_pct": 6.5
    }),
]

def run_backtest():
    print("=" * 115)
    print("🚀 QUANTITATIVE BACKTEST: MULTI-LOOKBACK MOMENTUM BLEND (12M + 6M + 3M) (60 MONTHS)")
    print("=" * 115)
    
    results = []
    session = Session()
    
    for idx, (name, overrides) in enumerate(VARIANTS, 1):
        cfg = dict(CHAMP_KWARGS)
        cfg.update(overrides)
        
        t0 = time.time()
        print(f"\n[{idx}/{len(VARIANTS)}] Running {name}...", flush=True)
        try:
            res = run_monthly_sip_backtest(session, **cfg)
            dur = time.time() - t0
            
            xirr = res.get("strategy_xirr", 0.0)
            corpus = res.get("final_strategy_value", 0.0)
            invested = res.get("total_invested", 0.0)
            drawdown = res.get("max_drawdown_pct", 0.0)
            trades = res.get("total_trades_count", 0)
            win_rate = res.get("win_rate", 0.0)
            pf = res.get("profit_factor", 0.0)
            payoff = res.get("payoff_ratio", 0.0)
            alpha = res.get("alpha_vs_benchmark_pct", 0.0)
            
            print(f"    --> Net XIRR: {xirr:.2f}% | Final: ₹{corpus:,.0f} | Invested: ₹{invested:,.0f} | Max DD: {drawdown:.1f}%")
            print(f"    --> Trades: {trades} | Win Rate: {win_rate:.1f}% | Profit Factor: {pf:.2f}x | Payoff: {payoff:.2f}x | Dur: {dur:.1f}s")
            
            results.append({
                "name": name,
                "xirr": xirr,
                "corpus": corpus,
                "invested": invested,
                "drawdown": drawdown,
                "trades": trades,
                "win_rate": win_rate,
                "pf": pf,
                "payoff": payoff,
                "alpha": alpha,
                "dur": dur
            })
        except Exception as e:
            print(f"    --> ERROR: {e}", flush=True)
            import traceback
            traceback.print_exc()
            
    session.close()
    
    # Summary Table
    print("\n" + "=" * 125)
    print(f"{'Variant / Configuration':<65} | {'Net XIRR':<10} | {'Final Corpus':<15} | {'Max DD':<8} | {'PF':<6} | {'Payoff':<7} | {'Win %':<6}")
    print("-" * 125)
    for r in results:
        print(f"{r['name']:<65} | {r['xirr']:>8.2f}% | ₹{r['corpus']:>13,.0f} | {r['drawdown']:>6.1f}% | {r['pf']:>5.2f} | {r['payoff']:>6.2f} | {r['win_rate']:>5.1f}%")
    print("=" * 125)

if __name__ == "__main__":
    run_backtest()
