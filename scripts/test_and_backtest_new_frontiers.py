"""
Comprehensive Empirical Backtest & Functional Test of:
1. Alpha & Sizing Optimizations (LiquidBees Cash Yield, Regime-Adaptive Hurdle, Beta Stepladders)
2. Fundamental Moat & Quality Filters (Piotroski F-Score >= 6, Altman Z)
3. Broker Portfolio Import & Live Holdings Sync (Zerodha / Groww Reconciliation)
"""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.sip_audit_backtester import run_monthly_sip_backtest
from core.broker_sync import parse_broker_holdings, reconcile_portfolio_with_sip_radar
from core.monthly_sip_advisor import generate_monthly_sip_basket

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
    min_piotroski_score=6
)

VARIANTS = [
    # ── 1. Current Champion ──
    ("👑 Champ: Maximum Alpha v2.0 (Hurdle 30%, Hedge 3%)", {}),

    # ── 2. LiquidBees Cash Yield Auto-Sweeping ──
    ("⚡ Champ + LiquidBees Auto-Sweep (6.5% Yield)", {
        "enable_liquid_sweep": True, "liquid_yield_pct": 6.5
    }),

    # ── 3. Regime-Adaptive Hurdle ──
    ("🎯 Champ + Regime-Adaptive Hurdle (Bull 30% / Neut 20% / Bear 15%)", {
        "enable_regime_adaptive_hurdle": True
    }),

    # ── 4. Beta-Calibrated Dynamic Stepladders ──
    ("🪜 Champ + Beta-Calibrated Stepladders (Wide High-Beta / Tight Low-Beta)", {
        "enable_beta_stepladder": True
    }),

    # ── 5. Fundamental Moat (Piotroski >= 6 & Safe Altman Z) ──
    ("🏛️ Champ + Fundamental Moat (Piotroski F >= 6 & Safe Z)", {
        "enable_fundamental_moat": True, "min_piotroski_score": 6
    }),

    # ── 6. Sector Momentum Shield Baselines ──
    ("🛡️ Sector Momentum Shield Baseline (54.8% XIRR / 21.7% DD)", {
        "enable_sector_rotation_score": True, "sector_boost_pct": 50.0
    }),
    ("🛡️ Sector Shield + LiquidBees Auto-Sweep", {
        "enable_sector_rotation_score": True, "sector_boost_pct": 50.0,
        "enable_liquid_sweep": True, "liquid_yield_pct": 6.5
    }),

    # ── 7. Supreme Combined Synergies ──
    ("💎 Apex Combo A: Champ + LiquidBees + Beta Stepladder", {
        "enable_liquid_sweep": True, "liquid_yield_pct": 6.5,
        "enable_beta_stepladder": True
    }),
    ("💎 Apex Combo B: Sector Shield + LiquidBees + Beta Stepladder", {
        "enable_sector_rotation_score": True, "sector_boost_pct": 50.0,
        "enable_liquid_sweep": True, "liquid_yield_pct": 6.5,
        "enable_beta_stepladder": True
    }),
    ("💎 Apex Combo C: Sector Shield + LiquidBees + Adaptive Hurdle + Moat", {
        "enable_sector_rotation_score": True, "sector_boost_pct": 50.0,
        "enable_liquid_sweep": True, "liquid_yield_pct": 6.5,
        "enable_regime_adaptive_hurdle": True,
        "enable_fundamental_moat": True, "min_piotroski_score": 6
    }),
]


def run_all_backtests():
    print("=" * 115)
    print("🚀 QUANTITATIVE BACKTEST: ALPHA & SIZING OPTIMIZATIONS + FUNDAMENTAL MOATS (60 MONTHS)")
    print("=" * 115)

    results = []
    session = Session()

    for idx, (name, overrides) in enumerate(VARIANTS, 1):
        kw = CHAMP_KWARGS.copy()
        kw.update(overrides)

        t0 = time.time()
        res = run_monthly_sip_backtest(session, **kw)
        elapsed = time.time() - t0

        if "error" in res:
            print(f"[{idx:02d}/{len(VARIANTS):02d}] ❌ {name}: ERROR: {res['error']}")
            continue

        xirr = res.get("strategy_xirr", 0.0)
        corpus = res.get("final_strategy_value", 0.0)
        invested = res.get("total_invested", 0.0)
        net_profit = corpus - invested
        pf = res.get("profit_factor", 0.0)
        payoff = res.get("payoff_ratio", 0.0)
        max_dd = res.get("max_drawdown_pct", 0.0)
        win_rate = res.get("win_rate", 0.0)
        trades = res.get("total_trades_count", 0)

        results.append({
            "name": name,
            "xirr": xirr,
            "corpus": corpus,
            "invested": invested,
            "net_profit": net_profit,
            "pf": pf,
            "payoff": payoff,
            "max_dd": max_dd,
            "win_rate": win_rate,
            "trades": trades,
            "time_sec": elapsed
        })

        print(f"[{idx:02d}/{len(VARIANTS):02d}] ✅ {name:<70} | XIRR: {xirr:5.1f}% | Corpus: ₹{corpus/1e5:5.2f}L | PF: {pf:4.2f} | Payoff: {payoff:5.2f}x | DD: {max_dd:4.1f}% | ({elapsed:.1f}s)")

    session.close()

    print("\n" + "=" * 115)
    print(f"{'Configuration':<65} | {'XIRR':<6} | {'Corpus':<9} | {'Profit Factor':<13} | {'Payoff':<7} | {'Max DD':<6} | {'Win %':<5}")
    print("-" * 115)
    for r in sorted(results, key=lambda x: x["xirr"], reverse=True):
        print(f"{r['name']:<65} | {r['xirr']:5.1f}% | ₹{r['corpus']/1e5:5.2f}L | {r['pf']:13.2f} | {r['payoff']:6.2f}x | {r['max_dd']:5.1f}% | {r['win_rate']:4.1f}%")
    print("=" * 115)
    return results


def test_broker_portfolio_reconciliation():
    print("\n" + "=" * 115)
    print("💼 TESTING BROKER PORTFOLIO IMPORT & LIVE RECONCILIATION (ZERODHA & GROWW)")
    print("=" * 115)

    # 1. Mock Zerodha Holdings CSV
    zerodha_csv = """Instrument,Qty.,Avg. cost,LTP,Cur. val,P&L,Net chg.
RELIANCE,10,2400.0,3050.0,30500.0,6500.0,+27.08%
TATAELXSI,15,6200.0,8100.0,121500.0,28500.0,+30.65%
PERSISTENT,8,2200.0,6100.0,48800.0,31200.0,+177.27%
SUZLON,200,82.0,54.0,10800.0,-5600.0,-34.15%
INFY,25,1450.0,1920.0,48000.0,11750.0,+32.41%
"""

    parsed = parse_broker_holdings(zerodha_csv, broker_hint="ZERODHA")
    print(f"Detected Broker: {parsed.get('broker')}")
    print(f"Total Holdings: {parsed.get('total_holdings_count')} | Invested: ₹{parsed.get('total_invested'):,.2f} | Current Value: ₹{parsed.get('current_value'):,.2f} | PnL: ₹{parsed.get('total_pnl'):,.2f} ({parsed.get('total_pnl_pct')}%)")

    # Generate current live basket for comparison
    session = Session()
    basket = generate_monthly_sip_basket(
        session=session,
        monthly_wallet=20000.0,
        strategy="PURE_STOCKS",
        risk_profile="RISKY",
        exit_protocol="ADAPTIVE_STRUCTURAL"
    )
    session.close()

    rec = reconcile_portfolio_with_sip_radar(parsed, basket, monthly_wallet=20000.0)

    print(f"\nReconciliation Results:")
    print(f"  • Pyramid Tranches Found: {len(rec['pyramid_tranches'])}")
    for pyr in rec["pyramid_tranches"]:
        print(f"    🚀 {pyr['symbol']}: Current Gain +{pyr['pnl_pct']:.1f}% -> Recommended +{pyr['recommended_new_shares']} shares (₹{pyr['fresh_investment']:,.2f})")

    print(f"  • New Initiations: {len(rec['new_initiations'])}")
    for init in rec["new_initiations"][:3]:
        print(f"    ⭐ {init['symbol']}: Recommended {init['recommended_shares']} shares (₹{init['allocation']:,.2f})")

    print(f"  • Profit Skim Alerts: {len(rec['profit_skims'])}")
    for sk in rec["profit_skims"]:
        print(f"    💰 {sk['symbol']}: Gain +{sk['pnl_pct']:.1f}% -> Action: {sk['action']} (Banks ₹{sk['freed_cash']:,.2f})")

    print(f"  • Sell Alerts (Stop Breaches): {len(rec['sell_alerts'])}")
    for sl in rec["sell_alerts"]:
        print(f"    🚨 {sl['symbol']}: Action: {sl['action']} | Reason: {sl['reason']}")

    print(f"  • Execution Order Sheet Items: {len(rec['execution_order_sheet'])}")
    for ord_item in rec["execution_order_sheet"]:
        print(f"    📋 [{ord_item['status']}] {ord_item['type']:<18} | {ord_item['symbol']:<15} | Qty: {ord_item['shares']:<4} | Net: ₹{ord_item['approx_cost']:,.2f}")

    print("=" * 115)


if __name__ == "__main__":
    test_broker_portfolio_reconciliation()
    run_all_backtests()
