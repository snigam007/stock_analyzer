"""
Comprehensive Backtest of Profit Improvement Roadmap Levers
Tests Levers 1, 3, 5, 7 individually and in combination vs Baselines on 60-month horizon.
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
    min_momentum_hurdle_pct=20.0,
    enable_52w_high_proximity=False, proximity_52w_threshold_pct=15.0,
    enable_quality_composite_filter=False, min_quality_score=45.0, min_sharpe_ratio=-2.0,
    enable_multifactor_alpha=False,
    enable_split_entry=False, split_entry_initial_ratio=0.60, split_entry_pullback_pct=3.0, split_entry_max_wait_days=10,
    enable_stale_rotation=False, stale_rotation_days=120, stale_rotation_min_gain_pct=25.0, stale_rotation_lookback_days=90,
    enable_sector_rotation_score=False, sector_boost_pct=30.0,
)

VARIANTS = [
    # ── Baselines ──
    ("Baseline (Hurdle 20%, Hedge 5%)", {}),
    ("Champion (Hurdle 30%, Hedge 3%)", {
        "min_momentum_hurdle_pct": 30.0, "macro_hedge_pct": 3.0
    }),

    # ── Lever 7: Sector Rotation Score ──
    ("L7: Sector Boost (+30% on Baseline)", {
        "enable_sector_rotation_score": True, "sector_boost_pct": 30.0
    }),
    ("L7: Sector Boost (+30% on Champion)", {
        "min_momentum_hurdle_pct": 30.0, "macro_hedge_pct": 3.0,
        "enable_sector_rotation_score": True, "sector_boost_pct": 30.0
    }),
    ("L7: Sector Boost (+50% on Champion)", {
        "min_momentum_hurdle_pct": 30.0, "macro_hedge_pct": 3.0,
        "enable_sector_rotation_score": True, "sector_boost_pct": 50.0
    }),

    # ── Lever 5: Time-Decay Exit (Stale Winner Rotation) ──
    ("L5: Stale Rotation (120d, <25% on Baseline)", {
        "enable_stale_rotation": True, "stale_rotation_days": 120,
        "stale_rotation_min_gain_pct": 25.0, "stale_rotation_lookback_days": 90
    }),
    ("L5: Stale Rotation (120d, <25% on Champion)", {
        "min_momentum_hurdle_pct": 30.0, "macro_hedge_pct": 3.0,
        "enable_stale_rotation": True, "stale_rotation_days": 120,
        "stale_rotation_min_gain_pct": 25.0, "stale_rotation_lookback_days": 90
    }),
    ("L5: Stale Rotation (90d, <20% Aggressive on Champ)", {
        "min_momentum_hurdle_pct": 30.0, "macro_hedge_pct": 3.0,
        "enable_stale_rotation": True, "stale_rotation_days": 90,
        "stale_rotation_min_gain_pct": 20.0, "stale_rotation_lookback_days": 60
    }),

    # ── Lever 3: Intra-Month Split-Entry Timing ──
    ("L3: Split-Entry (60/40, -3% on Baseline)", {
        "enable_split_entry": True, "split_entry_initial_ratio": 0.60,
        "split_entry_pullback_pct": 3.0, "split_entry_max_wait_days": 10
    }),
    ("L3: Split-Entry (60/40, -3% on Champion)", {
        "min_momentum_hurdle_pct": 30.0, "macro_hedge_pct": 3.0,
        "enable_split_entry": True, "split_entry_initial_ratio": 0.60,
        "split_entry_pullback_pct": 3.0, "split_entry_max_wait_days": 10
    }),
    ("L3: Split-Entry (50/50, -2.5% on Champion)", {
        "min_momentum_hurdle_pct": 30.0, "macro_hedge_pct": 3.0,
        "enable_split_entry": True, "split_entry_initial_ratio": 0.50,
        "split_entry_pullback_pct": 2.5, "split_entry_max_wait_days": 10
    }),

    # ── Lever 1: Multi-Factor Alpha Scoring ──
    ("L1: Multi-Factor Alpha (on Baseline)", {
        "enable_multifactor_alpha": True
    }),
    ("L1: Multi-Factor Alpha (on Champion)", {
        "min_momentum_hurdle_pct": 30.0, "macro_hedge_pct": 3.0,
        "enable_multifactor_alpha": True
    }),

    # ── Synergistic Combinations ──
    ("Combo 1: Champ + L7 Sector Boost", {
        "min_momentum_hurdle_pct": 30.0, "macro_hedge_pct": 3.0,
        "enable_sector_rotation_score": True, "sector_boost_pct": 30.0
    }),
    ("Combo 2: Champ + L5 Stale Rotation", {
        "min_momentum_hurdle_pct": 30.0, "macro_hedge_pct": 3.0,
        "enable_stale_rotation": True, "stale_rotation_days": 120, "stale_rotation_min_gain_pct": 25.0
    }),
    ("Combo 3: Champ + L7 Sector + L5 Stale", {
        "min_momentum_hurdle_pct": 30.0, "macro_hedge_pct": 3.0,
        "enable_sector_rotation_score": True, "sector_boost_pct": 30.0,
        "enable_stale_rotation": True, "stale_rotation_days": 120, "stale_rotation_min_gain_pct": 25.0
    }),
    ("Combo 4: Champ + L7 Sector + L3 Split", {
        "min_momentum_hurdle_pct": 30.0, "macro_hedge_pct": 3.0,
        "enable_sector_rotation_score": True, "sector_boost_pct": 30.0,
        "enable_split_entry": True
    }),
    ("Combo 5: Champ + L7 + L5 + L3", {
        "min_momentum_hurdle_pct": 30.0, "macro_hedge_pct": 3.0,
        "enable_sector_rotation_score": True, "sector_boost_pct": 30.0,
        "enable_stale_rotation": True, "stale_rotation_days": 120, "stale_rotation_min_gain_pct": 25.0,
        "enable_split_entry": True
    }),
    ("Combo 6: Champ + All Levers (L1+L3+L5+L7)", {
        "min_momentum_hurdle_pct": 30.0, "macro_hedge_pct": 3.0,
        "enable_multifactor_alpha": True,
        "enable_sector_rotation_score": True, "sector_boost_pct": 30.0,
        "enable_stale_rotation": True, "stale_rotation_days": 120, "stale_rotation_min_gain_pct": 25.0,
        "enable_split_entry": True
    }),
]

def run_variant(label, overrides):
    session = Session()
    kw = dict(BEST_KWARGS)
    kw.update(overrides)
    t0 = time.time()
    try:
        res = run_monthly_sip_backtest(session, **kw)
        el = time.time() - t0
        xirr = res.get("strategy_xirr", 0.0)
        corpus = res.get("final_strategy_value", 0.0) / 100000.0
        invested = res.get("total_invested", 0.0) / 100000.0
        profit = corpus - invested
        pf = res.get("profit_factor", 0.0)
        payoff = res.get("payoff_ratio", 0.0)
        dd = res.get("max_drawdown_pct", 0.0)
        wr = res.get("win_rate", 0.0)
        split_fills = res.get("split_entries_filled_count", 0)
        stale_exits = res.get("stale_rotations_count", 0)
        return {
            "label": label, "xirr": xirr, "corpus": corpus, "profit": profit,
            "pf": pf, "payoff": payoff, "dd": dd, "wr": wr,
            "split_fills": split_fills, "stale_exits": stale_exits,
            "time": el, "ok": True
        }
    except Exception as ex:
        el = time.time() - t0
        print(f"  FAILED: {label} -> {ex}")
        import traceback; traceback.print_exc()
        return {"label": label, "xirr": -999, "ok": False, "err": str(ex), "time": el}
    finally:
        session.close()

if __name__ == "__main__":
    output_lines = []
    header1 = "=" * 105
    header2 = f"{'Variant':<44} | {'XIRR':>6} | {'Corpus':>8} | {'PF':>5} | {'Payoff':>6} | {'DD':>5} | {'WR':>4} | {'Triggers'}"
    header3 = "-" * 105
    print(header1); output_lines.append(header1)
    print("PROFIT IMPROVEMENT ROADMAP: COMPREHENSIVE LEVERS BACKTEST (60 MONTHS)"); output_lines.append("PROFIT IMPROVEMENT ROADMAP: COMPREHENSIVE LEVERS BACKTEST (60 MONTHS)")
    print(header1); output_lines.append(header1)
    print(header2); output_lines.append(header2)
    print(header3); output_lines.append(header3)

    results = []
    for label, overrides in VARIANTS:
        r = run_variant(label, overrides)
        results.append(r)
        if r["ok"]:
            trig_info = ""
            if r["split_fills"] > 0: trig_info += f"Splits:{r['split_fills']} "
            if r["stale_exits"] > 0: trig_info += f"Stale:{r['stale_exits']} "
            line = f"{r['label']:<44} | {r['xirr']:>5.1f}% | Rs.{r['corpus']:>6.2f}L | {r['pf']:>5.2f} | {r['payoff']:>5.2f}x | {r['dd']:>4.1f}% | {r['wr']:>3.0f}% | {trig_info}"
            print(line); output_lines.append(line)
        else:
            line = f"{r['label']:<44} |  ERROR: {r.get('err', '')[:30]}"
            print(line); output_lines.append(line)

    print(header1); output_lines.append(header1)
    sorted_res = sorted([r for r in results if r["ok"]], key=lambda x: x["xirr"], reverse=True)
    top_header = "\nTOP 5 VARIANTS BY NET XIRR:"
    print(top_header); output_lines.append(top_header)
    for i, r in enumerate(sorted_res[:5], 1):
        delta = r["xirr"] - 43.4
        t_line = f"  #{i}: {r['label']:<44} -> XIRR: {r['xirr']:.1f}% ({delta:+.1f}%) | Corpus: Rs.{r['corpus']:.2f}L | PF: {r['pf']:.2f} | DD: {r['dd']:.1f}%"
        print(t_line); output_lines.append(t_line)

    with open("scripts/roadmap_levers_results.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines) + "\n")
    print("\nSaved output to scripts/roadmap_levers_results.txt")
