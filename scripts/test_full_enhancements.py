import sys, os
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from db.database import get_session, get_global_engine
from core.monthly_sip_advisor import generate_monthly_sip_basket, evaluate_sell_reminders
from core.sip_audit_backtester import run_monthly_sip_backtest

engine = get_global_engine()
session = get_session(engine)

print("--- 1. TESTING GENERATE MONTHLY SIP BASKET (ERC + CLENOW) ---")
basket = generate_monthly_sip_basket(
    session=session,
    monthly_wallet=20000.0,
    strategy="PURE_STOCKS",
    sizing_mode="ERC",
    enable_clenow_momentum=True,
    enable_3tier_harvest=True
)

print(f"Total Spent: ₹{basket.get('total_spent'):,.2f}")
print(f"Expected CAGR: {basket.get('expected_cagr_pct')}%")
print(f"Clenow Ranking Applied: {basket.get('clenow_ranking_applied')}")
print(f"Van Tharp Harvest Info: {basket.get('van_tharp_harvest_info')}")
print(f"Macro Status: {basket.get('macro_regime_status', {}).get('breadth_thrust_badge')} | Breadth 50: {basket.get('macro_regime_status', {}).get('pct_above_50_ema')}%")
for a in basket.get("assets", []):
    print(f"  • {a['symbol']} ({a.get('allocation_pct')}%): Price ₹{a['current_price']}, Qty {a['shares_to_buy']}, Clenow: {a.get('clenow_score')}")

print("\n--- 2. TESTING SELL REMINDERS (VAN THARP ALERTS) ---")
reminders = evaluate_sell_reminders(session)
print(f"Reminders generated: {len(reminders)}")
for r in reminders[:3]:
    print(f"  • {r['symbol']}: Severity={r['severity']} | Primary={r['primary_trigger']} | Action={r['recommended_action']}")

print("\n--- 3. TESTING RUN_MONTHLY_SIP_BACKTEST (36M) ---")
bt = run_monthly_sip_backtest(
    session=session,
    monthly_wallet=20000.0,
    strategy="PURE_STOCKS",
    months_lookback=36,
    sizing_mode="ERC",
    enable_3tier_harvest=True,
    enable_clenow_momentum=True,
    enable_breadth_gate=True
)
print(f"XIRR: {bt.get('strategy_xirr')}%")
print(f"Max Drawdown: {bt.get('max_drawdown_pct')}%")
print(f"Alpha: {bt.get('alpha')}%")
print(f"Profit Factor: {bt.get('profit_factor')}")
print(f"Payoff Ratio: {bt.get('payoff_ratio')}x")
final_val = bt.get('final_strategy_value')
print(f"Ending Corpus: ₹{final_val:,.2f}" if final_val is not None else "Ending Corpus: N/A")
print(f"3-Tier Harvest Exits: {bt.get('three_tier_harvests_count')}")

session.close()
print("\n✅ ALL TESTS COMPLETED SUCCESSFULLY!")
