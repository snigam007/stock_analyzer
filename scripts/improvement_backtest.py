"""
Improvement Backtest Comparison — 60-Month Horizon
Tests all improvement lever combinations vs baseline (43.4% XIRR).
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

# ── Best known settings (Maximum Alpha Champion) ──
BEST_KWARGS = dict(
    monthly_wallet=20000.0,
    strategy="PURE_STOCKS",
    months_lookback=60,
    exit_protocol="ADAPTIVE_STRUCTURAL",
    risk_profile="RISKY",
    annual_step_up_pct=10.0,
    pyramid_winners=True,
    min_momentum_hurdle_pct=20.0,
    enable_dip_buying=True,
    enable_parabolic_skim=True,
    max_position_cap_pct=45.0,
    enable_loss_cooldown=True,
    cooldown_days=60,
    enable_sector_momentum_gate=True,
    enable_macro_regime_gate=True,
    macro_hedge_pct=5.0,
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
    # New levers off by default
    enable_52w_high_proximity=False,
    proximity_52w_threshold_pct=15.0,
    enable_quality_composite_filter=False,
    min_quality_score=45.0,
    min_sharpe_ratio=-2.0,
)

VARIANTS = [
    ("A: Baseline (Max Alpha Champion)", {}),
    ("B: 52W High Proximity (within 15%)", {
        "enable_52w_high_proximity": True,
        "proximity_52w_threshold_pct": 15.0,
    }),
    ("C: 52W High Proximity (within 20%)", {
        "enable_52w_high_proximity": True,
        "proximity_52w_threshold_pct": 20.0,
    }),
    ("D: Quality Composite Filter (score>45)", {
        "enable_quality_composite_filter": True,
        "min_quality_score": 45.0,
        "min_sharpe_ratio": -2.0,
    }),
    ("E: Quality Composite Filter (score>50)", {
        "enable_quality_composite_filter": True,
        "min_quality_score": 50.0,
        "min_sharpe_ratio": -1.5,
    }),
    ("F: 52W Proximity + Quality (15% + score>45)", {
        "enable_52w_high_proximity": True,
        "proximity_52w_threshold_pct": 15.0,
        "enable_quality_composite_filter": True,
        "min_quality_score": 45.0,
        "min_sharpe_ratio": -2.0,
    }),
    ("G: 52W Proximity + Quality (20% + score>45)", {
        "enable_52w_high_proximity": True,
        "proximity_52w_threshold_pct": 20.0,
        "enable_quality_composite_filter": True,
        "min_quality_score": 45.0,
        "min_sharpe_ratio": -2.0,
    }),
    ("H: Hurdle +25% (momentum tightened)", {
        "min_momentum_hurdle_pct": 25.0,
    }),
    ("I: Hurdle +30% (aggressive)", {
        "min_momentum_hurdle_pct": 30.0,
    }),
    ("J: All Three (52W+Quality+Hurdle30)", {
        "enable_52w_high_proximity": True,
        "proximity_52w_threshold_pct": 20.0,
        "enable_quality_composite_filter": True,
        "min_quality_score": 45.0,
        "min_sharpe_ratio": -2.0,
        "min_momentum_hurdle_pct": 30.0,
    }),
]


def run_variant(label, overrides):
    session = Session()
    t0 = time.time()
    try:
        kwargs = {**BEST_KWARGS, **overrides}
        result = run_monthly_sip_backtest(session=session, **kwargs)
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
            "total_inv": result.get("total_invested", 0.0),
            "elapsed": elapsed,
        }
    except Exception as e:
        import traceback
        return {"label": label, "error": str(e), "traceback": traceback.format_exc()}
    finally:
        session.close()


def extract(result, label):
    """Extract metrics from flat result dict (no nested 'metrics' key)."""
    return {
        "label": label,
        "xirr": result.get("strategy_xirr", result.get("net_xirr_pct", 0.0)),
        "pf": result.get("profit_factor", 0.0),
        "win_rate": result.get("win_rate", result.get("win_rate_pct", 0.0)),
        "max_dd": result.get("max_drawdown_pct", 0.0),
        "payoff": result.get("payoff_ratio", result.get("avg_payoff_ratio", 0.0)),
        "final_val": result.get("final_strategy_value", result.get("final_portfolio_value", 0.0)),
        "total_inv": result.get("total_invested", 0.0),
    }


def main():
    results = []
    total = len(VARIANTS)
    for i, (label, overrides) in enumerate(VARIANTS, 1):
        print(f"[{i}/{total}] Running: {label} ...", flush=True)
        r = run_variant(label, overrides)
        results.append(r)
        if "error" in r:
            print(f"  ERROR: {r.get('error')}")
            if "traceback" in r:
                print(r["traceback"])
        else:
            print(f"  XIRR={r['xirr']:+.1f}%  PF={r['pf']:.2f}  WR={r['win_rate']:.1f}%  DD={r['max_dd']:.1f}%  Payoff={r['payoff']:.2f}x  FinalVal=Rs{r['final_val']:,.0f}  [{r['elapsed']:.0f}s]")

    # ── Print comparison table ──
    print()
    print("=" * 100)
    print("IMPROVEMENT BACKTEST RESULTS — 60-Month Horizon, Rs20,000/mo + 10% Step-Up")
    print("=" * 100)
    print(f"{'Variant':<48} {'XIRR':>7} {'Delta':>6} {'PF':>6} {'WinR':>6} {'DD':>7} {'Payoff':>7} {'Final Value':>14}")
    print("-" * 100)
    baseline_xirr = next((r["xirr"] for r in results if not r.get("error") and "Baseline" in r["label"]), 0.0)
    for r in results:
        if r.get("error"):
            print(f"{r['label']:<48}  ERROR: {r['error']}")
        else:
            delta = r["xirr"] - baseline_xirr
            delta_str = f"{delta:+.1f}%" if delta != 0 else "   ---"
            print(f"{r['label']:<48} {r['xirr']:>6.1f}% {delta_str:>6} {r['pf']:>6.2f} {r['win_rate']:>5.1f}% {r['max_dd']:>6.1f}% {r['payoff']:>6.2f}x  Rs{r['final_val']:>10,.0f}")

    print()
    valid = [r for r in results if not r.get("error")]
    if valid:
        best = max(valid, key=lambda x: x["xirr"])
        delta_best = best["xirr"] - baseline_xirr
        print(f"WINNER: {best['label']}")
        print(f"  XIRR:   {best['xirr']:+.1f}%  (Baseline: {baseline_xirr:+.1f}%,  Delta: {delta_best:+.1f}%)")
        print(f"  PF:     {best['pf']:.2f}")
        print(f"  WinR:   {best['win_rate']:.1f}%")
        print(f"  MaxDD:  {best['max_dd']:.1f}%")
        print(f"  Payoff: {best['payoff']:.2f}x")
        print(f"  Final:  Rs {best['final_val']:,.0f}")


if __name__ == "__main__":
    main()
