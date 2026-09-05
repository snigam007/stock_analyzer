"""
Test suite for Monthly SIP Investment Advisor and Sell Reminder Engine.
"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import text
from db.database import get_global_engine, get_session, Watchlist, WatchlistItem
from core.monthly_sip_advisor import (
    generate_monthly_sip_basket,
    deploy_sip_basket_to_watchlist,
    evaluate_sell_reminders
)
from core.watchlist_manager import evaluate_and_generate_alerts


def test_sip_advisor():
    engine = get_global_engine()
    session = get_session(engine)

    print("=" * 60)
    print("TEST 1: Pure Stocks Monthly Basket (₹20,000 Budget)")
    print("=" * 60)
    basket_stocks = generate_monthly_sip_basket(
        session=session,
        monthly_wallet=20000.0,
        strategy="PURE_STOCKS",
        risk_profile="BALANCED",
        target_stock_count=5
    )

    print(f"Strategy: {basket_stocks['strategy']}")
    print(f"Total Spent: ₹{basket_stocks['total_spent']:,.2f} / ₹{basket_stocks['monthly_wallet']:,.2f}")
    print(f"Cash Buffer: ₹{basket_stocks['cash_buffer']:,.2f}")
    print(f"Expected CAGR: {basket_stocks['expected_cagr_pct']}%")
    print(f"Assets Count: {len(basket_stocks['assets'])}")
    print("\nAllocated Shares:")
    for a in basket_stocks["assets"]:
        print(f"  • {a['symbol']:<10} | {a['name'][:20]:<20} | {a['sector'][:18]:<18} | "
              f"Qty: {a['shares_to_buy']:<2} | Price: ₹{a['current_price']:<7.2f} | "
              f"Cost: ₹{a['total_cost']:<8.2f} | SL: ₹{a['stop_loss']:<7.2f} | T1: ₹{a['target_price']:<7.2f}")

    assert basket_stocks["total_spent"] <= 20000.0, "Total spent exceeds monthly wallet!"
    assert basket_stocks["total_spent"] >= 18000.0, "Total spent is too low, under-allocating wallet!"
    assert len(basket_stocks["assets"]) >= 3, "Too few assets generated!"
    for a in basket_stocks["assets"]:
        assert isinstance(a["shares_to_buy"], int) and a["shares_to_buy"] > 0, "Share quantity must be positive integer!"

    print("\n" + "=" * 60)
    print("TEST 2: Multi-Asset Monthly Basket (Equities + Index + Gold)")
    print("=" * 60)
    basket_multi = generate_monthly_sip_basket(
        session=session,
        monthly_wallet=20000.0,
        strategy="MULTI_ASSET",
        risk_profile="BALANCED",
        target_stock_count=5
    )

    print(f"Strategy: {basket_multi['strategy']}")
    print(f"Total Spent: ₹{basket_multi['total_spent']:,.2f} / ₹{basket_multi['monthly_wallet']:,.2f}")
    print(f"Cash Buffer: ₹{basket_multi['cash_buffer']:,.2f}")
    for a in basket_multi["assets"]:
        print(f"  • {a['symbol']:<10} | {a['name'][:22]:<22} | {a['asset_class']:<12} | "
              f"Qty: {a['shares_to_buy']:<3} | Cost: ₹{a['total_cost']:<8.2f}")

    assert basket_multi["total_spent"] <= 20000.0, "Total spent exceeds monthly wallet!"
    assert any(a["asset_class"] == "Index / ETF" for a in basket_multi["assets"]), "Index ETF missing in Multi-Asset!"
    assert any(a["asset_class"] == "Commodity" for a in basket_multi["assets"]), "Gold/Commodity missing in Multi-Asset!"

    print("\n" + "=" * 60)
    print("TEST 3: 1-Click Deploy to Watchlist")
    print("=" * 60)
    test_wl_name = "TEST_MONTHLY_SIP_BASKET"
    deploy_res = deploy_sip_basket_to_watchlist(
        session=session,
        basket=basket_stocks,
        watchlist_name=test_wl_name,
        replace_existing=True
    )
    print(f"Deploy Result: {deploy_res}")
    assert deploy_res["status"] == "SUCCESS", f"Failed to deploy: {deploy_res}"
    assert deploy_res["added_count"] > 0, "No items added to watchlist!"

    wl = session.query(Watchlist).filter(Watchlist.name == test_wl_name).first()
    assert wl is not None, "Watchlist was not persisted!"
    print(f"Persisted Watchlist ID: {wl.id} with {len(wl.items)} items.")

    print("\n" + "=" * 60)
    print("TEST 4: Sell Reminder Radar Evaluation")
    print("=" * 60)
    # Add a mock deteriorated stock into the test watchlist to verify sell reminder detection
    # E.g. add a stock with an artificially high stop-loss that is already breached
    mock_item = WatchlistItem(
        watchlist_id=wl.id,
        symbol="RELIANCE",
        target_buy_price=1300.0,
        target_sell_price=1500.0,
        stop_loss=2000.0, # Deliberately higher than current price (~1322) to test Stop-Loss breach trigger
        notes="Test stop loss trigger"
    )
    session.add(mock_item)
    session.commit()

    reminders = evaluate_sell_reminders(session, watchlist_id=wl.id)
    print(f"Detected {len(reminders)} Sell Reminders in Test Watchlist:")
    for r in reminders:
        print(f"  • [{r['severity']}] {r['symbol']}: {r['primary_trigger']} -> {r['recommended_action']}")

    # Verify that RELIANCE triggered CRITICAL stop-loss breach
    rel_reminder = next((r for r in reminders if r["symbol"] == "RELIANCE"), None)
    assert rel_reminder is not None, "RELIANCE did not trigger sell reminder!"
    assert rel_reminder["severity"] == "CRITICAL", "Stop-loss breach should be CRITICAL severity!"
    assert "Stop-Loss Breached" in rel_reminder["primary_trigger"], "Trigger message incorrect!"

    # Test evaluate_and_generate_alerts integration (delete any prior today's test alert for clean idempotency)
    session.execute(text("DELETE FROM price_alerts WHERE symbol = 'RELIANCE'"))
    session.commit()
    alerts = evaluate_and_generate_alerts(session)
    print(f"\nGenerated {len(alerts)} alerts via core watchlist manager.")
    stop_alerts = [a for a in alerts if a["type"] == "Stop-Loss Hit"]
    print(f"Stop-Loss Alerts generated: {len(stop_alerts)}")
    assert len(stop_alerts) > 0, "Stop loss alert was not generated in price_alerts!"

    # Clean up test watchlist
    session.query(WatchlistItem).filter(WatchlistItem.watchlist_id == wl.id).delete()
    session.delete(wl)
    session.commit()
    print("\nCleanup completed: Test watchlist deleted successfully.")

    session.close()
    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    test_sip_advisor()
