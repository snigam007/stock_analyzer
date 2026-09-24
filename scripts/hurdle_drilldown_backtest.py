"""
Drill-Down Backtest: Fine-tune the Momentum Hurdle around the 30% winner.
Tests: 22%, 25%, 27%, 30%, 33%, 35%, 40% + combos with 52W proximity.
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

BEST_KWARGS = dict(
    monthly_wallet=20000.0, strategy="PURE_STOCKS", months_lookback=60,
    exit_protocol="ADAPTIVE_STRUCTURAL", risk_profile="RISKY", annual_step_up_pct=10.0,
    pyramid_winners=True, enable_dip_buying=True, enable_parabolic_skim=True,
    max_position_cap_pct=45.0, enable_loss_cooldown=True, cooldown_days=60,
    enable_sector_momentum_gate=True, enable_macro_regime_gate=True,
    macro_hedge_pct=5.0, enable_macro_rotation=True, enable_stepladder_trailing=True,
    sizing_mode="EQUAL", enable_correlation_clustering=True, max_pairwise_correlation=0.65,
    enable_friction_and_tax=True, enable_tax_harvesting=True,
    enable_volatility_targeting=False, enable_3tier_harvest=False,
    enable_clenow_momentum=False, enable_breadth_gate=True, target_stock_count=5,
    enable_52w_high_proximity=False, proximity_52w_threshold_pct=15.0,
    enable_quality_composite_filter=False, min_quality_score=45.0, min_sharpe_ratio=-2.0,
)

VARIANTS = [
    ("Hurdle 20% (Original Baseline)",    {"min_momentum_hurdle_pct": 20.0}),
    ("Hurdle 22%",                         {"min_momentum_hurdle_pct": 22.0}),
    ("Hurdle 25%",                         {"min_momentum_hurdle_pct": 25.0}),
    ("Hurdle 27%",                         {"min_momentum_hurdle_pct": 27.0}),
    ("Hurdle 30% ⭐ WINNER",               {"min_momentum_hurdle_pct": 30.0}),
    ("Hurdle 33%",                         {"min_momentum_hurdle_pct": 33.0}),
    ("Hurdle 35%",                         {"min_momentum_hurdle_pct": 35.0}),
    ("Hurdle 40%",                         {"min_momentum_hurdle_pct": 40.0}),
    ("Hurdle 30% + 52W 15%",              {"min_momentum_hurdle_pct": 30.0,
                                            "enable_52w_high_proximity": True,
                                            "proximity_52w_threshold_pct": 15.0}),
    ("Hurdle 30% + 52W 10%",              {"min_momentum_hurdle_pct": 30.0,
                                            "enable_52w_high_proximity": True,
                                            "proximity_52w_threshold_pct": 10.0}),
    ("Hurdle 30% + hedge 3%",             {"min_momentum_hurdle_pct": 30.0,
                                            "macro_hedge_pct": 3.0}),
    ("Hurdle 30% + hedge 8%",             {"min_momentum_hurdle_pct": 30.0,
                                            "macro_hedge_pct": 8.0}),
    ("Hurdle 30% + No Breadth Gate",      {"min_momentum_hurdle_pct": 30.0,
                                            "enable_breadth_gate": False}),
    ("Hurdle 30% + cap 40%",              {"min_momentum_hurdle_pct": 30.0,
                                            "max_position_cap_pct": 40.0}),
    ("Hurdle 30% + cap 50%",              {"min_momentum_hurdle_pct": 30.0,
                                            "max_position_cap_pct": 50.0}),
]

def run_variant(label, overrides):
    session = Session()
    t0 = time.time()
    try:
        result = run_monthly_sip_backtest(session=session, **{**BEST_KWARGS, **overrides})
        elapsed = time.time() - t0
        if "error" in result:
            return {"label": label, "error": result["error"]}
        return {
            "label": label,
            "xirr": result.get("strategy_xirr", 0.0),
            "pf": result.get("profit_factor", 0.0),
            "win_rate": result.get("win_rate", 0.0),
            "max_dd": result.get("max_drawdown_pct", 0.0),
            "payoff": result.get("payoff_ratio", 0.0),
            "final_val": result.get("final_strategy_value", 0.0),
            "total_trades": result.get("total_trades", 0),
            "elapsed": elapsed,
        }
    except Exception as e:
        import traceback
        return {"label": label, "error": str(e), "tb": traceback.format_exc()}
    finally:
        session.close()

def main():
    results = []
    total = len(VARIANTS)
    for i, (label, overrides) in enumerate(VARIANTS, 1):
        print(f"[{i}/{total}] {label} ...", flush=True)
        r = run_variant(label, overrides)
        results.append(r)
        if "error" in r:
            print(f"  ERROR: {r.get('error')}")
            if "tb" in r: print(r["tb"])
        else:
            print(f"  XIRR={r['xirr']:+.1f}%  PF={r['pf']:.2f}  WR={r['win_rate']:.1f}%  DD={r['max_dd']:.1f}%  Payoff={r['payoff']:.2f}x  Trades={r['total_trades']}  [{r['elapsed']:.0f}s]")

    print()
    print("=" * 105)
    print("DRILL-DOWN: Momentum Hurdle Optimization — 60M Horizon")
    print("=" * 105)
    print(f"{'Variant':<40} {'XIRR':>7} {'Δ Base':>7} {'PF':>6} {'WinR':>6} {'DD':>6} {'Payoff':>7} {'Trades':>7} {'Final Val':>14}")
    print("-" * 105)
    baseline_xirr = next((r["xirr"] for r in results if "Baseline" in r["label"] and not r.get("error")), 0.0)
    for r in results:
        if r.get("error"):
            print(f"{r['label']:<40}  ERROR")
        else:
            delta = r["xirr"] - baseline_xirr
            d_str = f"{delta:+.1f}%" if abs(delta) > 0.05 else "  ---  "
            star = " ⭐" if r["xirr"] == max(rr["xirr"] for rr in results if not rr.get("error")) else ""
            print(f"{r['label']:<40} {r['xirr']:>6.1f}% {d_str:>7} {r['pf']:>6.2f} {r['win_rate']:>5.1f}% {r['max_dd']:>5.1f}% {r['payoff']:>6.2f}x {r.get('total_trades',0):>7}  Rs{r['final_val']:>10,.0f}{star}")

    valid = [r for r in results if not r.get("error")]
    if valid:
        best = max(valid, key=lambda x: x["xirr"])
        print(f"\nOPTIMAL HURDLE: {best['label']}")
        print(f"  XIRR: {best['xirr']:.1f}%  PF: {best['pf']:.2f}  Payoff: {best['payoff']:.2f}x  Final: Rs {best['final_val']:,.0f}")

if __name__ == "__main__":
    main()
