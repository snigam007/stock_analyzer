"""
Unit and integration test suite verifying all 6 newly added requirements:
1. MF & Bulk/Block Daily Deltas
2. Multi-Asset Monthly SIP Daily Audit & Accuracy Tracker
3. Missed Alpha & False Negative Surveillance Engine
4. Watchlists Complete CRUD (Create, Read, Update, Delete)
5. Custom Portfolio Punch-In & Optimization Engine
6. Momentum vs ML Projection Cross-Validation Engine
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import pandas as pd
from datetime import date, timedelta
from sqlalchemy import text

from db.database import get_session, get_global_engine
from core.mf_fetcher import get_mf_daily_delta_summary, sync_all_mf_nav_deltas
from core.bulk_deals import get_latest_synced_deal_metadata, sync_bulk_and_block_deals_delta
from core.sip_tracker import log_sip_basket, update_sip_forward_performance, evaluate_multi_asset_sip_accuracy
from core.missed_signals import log_daily_missed_alpha_audit, evaluate_missed_alpha_audit_accuracy
from core.watchlist_manager import (
    create_watchlist, get_all_watchlists, get_watchlist_items,
    update_watchlist, update_watchlist_item, add_item_to_watchlist,
    delete_watchlist
)
from core.portfolio_analyzer import parse_portfolio_text, parse_portfolio_csv, analyze_custom_portfolio
from core.signals import verify_momentum_vs_ml_projection


def test_1_mf_and_bulk_block_daily_deltas():
    engine = get_global_engine()
    session = get_session(engine)
    try:
        # Verify MF delta sync runs safely without error
        res = sync_all_mf_nav_deltas(session)
        assert isinstance(res, dict)
        assert "new_navs_added" in res
        assert "schemes_updated" in res

        # Verify MF summary works
        mf_sum = get_mf_daily_delta_summary(session)
        assert isinstance(mf_sum, list)

        # Verify bulk/block deal sync & summary
        deals_res = sync_bulk_and_block_deals_delta(session, force_full=False, days_lookback=3)
        assert isinstance(deals_res, dict)

        deal_meta = get_latest_synced_deal_metadata(session)
        assert isinstance(deal_meta, dict)
        assert "total_deals_count" in deal_meta
    finally:
        session.close()


def test_2_multi_asset_sip_daily_audit():
    engine = get_global_engine()
    session = get_session(engine)
    try:
        test_basket = [
            {"symbol": "RELIANCE", "asset_class": "Stock", "weight": 25.0, "current_price": 2500.0, "strategy": "Compounder Core"},
            {"symbol": "^NSEI", "asset_class": "Index / ETF", "weight": 25.0, "current_price": 22000.0, "strategy": "Market Core"},
            {"symbol": "GC=F", "asset_class": "Commodity", "weight": 25.0, "current_price": 65000.0, "strategy": "Hedge"},
            {"symbol": "120503", "asset_class": "Mutual Fund", "weight": 25.0, "nav": 85.0, "strategy": "Active Alpha"},
        ]
        # Log basket across all 4 asset classes
        b_inserted = log_sip_basket(
            session=session,
            basket={"assets": test_basket},
            strategy="TEST_Compounder_Multi_Asset_Core",
            exit_protocol="Target T2 / Trailing Stop",
            force_relog=True
        )
        assert b_inserted >= 0

        # Run forward performance updater
        update_sip_forward_performance(session)

        # Run multi-asset accuracy evaluation
        acc = evaluate_multi_asset_sip_accuracy(session, months=12)
        assert isinstance(acc, dict)
        assert "total_suggestions" in acc
        assert "win_rate_pct" in acc
        assert "asset_class_stats" in acc
        assert "strategy_stats" in acc
    finally:
        session.execute(text("DELETE FROM sip_suggestion_log WHERE strategy = 'TEST_Compounder_Multi_Asset_Core'"))
        session.commit()
        session.close()


def test_3_missed_alpha_surveillance_audit():
    engine = get_global_engine()
    session = get_session(engine)
    try:
        # Run daily missed alpha audit
        audit_res = log_daily_missed_alpha_audit(session, lookback_days=10)
        assert isinstance(audit_res, dict)
        assert "new_records_logged" in audit_res
        assert "capture_rate_pct" in audit_res

        # Run accuracy evaluation
        eval_res = evaluate_missed_alpha_audit_accuracy(session, days=60)
        assert isinstance(eval_res, dict)
        assert "total_movers" in eval_res
        assert "capture_rate_pct" in eval_res
        assert "false_negative_rate_pct" in eval_res
        assert "bottleneck_distribution" in eval_res
        assert "quant_insights" in eval_res
    finally:
        session.close()


def test_4_watchlist_crud_operations():
    engine = get_global_engine()
    session = get_session(engine)
    try:
        # 1. CREATE
        wl_id = create_watchlist("Test WL Automated", "Created for automated testing", session)
        assert wl_id is not None

        # 2. READ
        all_wl = get_all_watchlists(session)
        assert any(w["id"] == wl_id for w in all_wl)

        # 3. ADD ITEM
        added = add_item_to_watchlist(wl_id, "TCS", 3800.0, 4200.0, 3600.0, "Core IT", session)
        assert added is True

        items = get_watchlist_items(wl_id, session)
        assert len(items) >= 1
        item_id = items[0]["item_id"]

        # 4. UPDATE ITEM
        up_item = update_watchlist_item(item_id, target_buy_price=3850.0, target_sell_price=4300.0, stop_loss=3650.0, notes="Updated note", session=session)
        assert up_item is True

        # 5. UPDATE WATCHLIST NAME & DESC
        up_wl = update_watchlist(wl_id, name="Test WL Renamed", description="Updated description", session=session)
        assert up_wl is True

        # 6. DELETE (populated)
        del_success = delete_watchlist(wl_id, session)
        assert del_success is True

        # Verify deletion
        all_wl_after = get_all_watchlists(session)
        assert not any(w["id"] == wl_id for w in all_wl_after)

        # 7. DELETE (empty watchlist)
        wl_empty_id = create_watchlist("Test WL Empty", "Empty testing", session)
        assert wl_empty_id is not None
        del_empty = delete_watchlist(wl_empty_id, session)
        assert del_empty is True
    finally:
        session.close()


def test_5_custom_portfolio_analyzer():
    engine = get_global_engine()
    session = get_session(engine)
    try:
        sample_text = """
        TCS.NS, 25, 3850
        INFY.NS, 50, 1550
        RELIANCE.NS, 20, 2450
        HDFCBANK.NS, 30, 1600
        """
        parsed_items = parse_portfolio_text(sample_text)
        assert len(parsed_items) == 4
        assert parsed_items[0]["symbol"] == "TCS"
        assert parsed_items[0]["shares"] == 25

        report = analyze_custom_portfolio(parsed_items, session)
        assert isinstance(report, dict)
        assert "holdings" in report
        assert len(report["holdings"]) == 4
        assert report["summary"]["total_current"] > 0
        assert "hhi_score" in report["summary"]
        assert "advice_counts" in report["summary"]
        assert "sector_breakdown" in report["summary"]
        # Check that each holding has advice and health
        for h in report["holdings"]:
            assert h["advice"] in ["ACCUMULATE", "HOLD", "TRIM", "REBALANCE", "EXIT"]
            assert "composite_score" in h
            assert "unrealized_pnl_pct" in h

        # Test Multi-Asset Catalog & Search
        from core.portfolio_analyzer import get_searchable_assets_catalog
        cat_all = get_searchable_assets_catalog(session, category="ALL")
        assert len(cat_all) >= 400
        cat_mfs = get_searchable_assets_catalog(session, category="MF")
        assert len(cat_mfs) >= 20
        cat_stocks = get_searchable_assets_catalog(session, category="STOCK")
        assert len(cat_stocks) >= 300

        # Test Multi-Asset Portfolio Audit (Stocks, MFs, ETFs, Commodities)
        multi_port = [
            {"symbol": "TCS", "shares": 10, "buy_price": 3800.0, "asset_class": "Stock"},
            {"symbol": "118955", "shares": 100, "buy_price": 280.0, "asset_class": "Mutual Fund"},
            {"symbol": "GOLDBEES.NS", "shares": 50, "buy_price": 120.0, "asset_class": "Index / ETF"},
            {"symbol": "GC=F", "shares": 1, "buy_price": 74000.0, "asset_class": "Commodity"}
        ]
        multi_res = analyze_custom_portfolio(multi_port, session)
        assert multi_res["status"] == "SUCCESS"
        assert len(multi_res["holdings"]) == 4
        assert "asset_class_breakdown" in multi_res["summary"]
        assert len(multi_res["summary"]["asset_class_breakdown"]) >= 3
    finally:
        session.close()


def test_6_momentum_vs_ml_projection_validation():
    engine = get_global_engine()
    session = get_session(engine)
    try:
        # Case 1: Bullish Confluence
        r1 = verify_momentum_vs_ml_projection("TEST", momentum_pct=15.0, ml_forecast_pct=4.5)
        assert r1["status"] == "BULLISH_CONFLUENCE"
        assert "🚀" in r1["badge"]

        # Case 2: Bull Trap / Exhaustion Divergence
        r2 = verify_momentum_vs_ml_projection("TEST", momentum_pct=22.0, ml_forecast_pct=-3.5)
        assert r2["status"] == "BULL_TRAP_DIVERGENCE"
        assert "⚠️" in r2["badge"]
        assert r2["score_adj"] < 0

        # Case 3: Value Reversal
        r3 = verify_momentum_vs_ml_projection("TEST", momentum_pct=-10.0, ml_forecast_pct=5.0)
        assert r3["status"] == "ACCUMULATION_REVERSAL"
        assert "🌱" in r3["badge"]

        # Case 4: Bearish Confluence
        r4 = verify_momentum_vs_ml_projection("TEST", momentum_pct=-12.0, ml_forecast_pct=-4.0)
        assert r4["status"] == "BEARISH_CONFLUENCE"
        assert "🔴" in r4["badge"]

        # Case 5: Neutral
        r5 = verify_momentum_vs_ml_projection("TEST", momentum_pct=2.0, ml_forecast_pct=0.5)
        assert r5["status"] == "NEUTRAL"
    finally:
        session.close()


def test_7_recommendation_mandate_and_shift_tracker():
    from core.recommendation_tracker import (
        init_recommendation_tracker_tables,
        save_active_recommendation_mandate,
        get_tracked_mandates,
        evaluate_mandate_live_status,
        compute_daily_recommendation_shifts,
        get_recommendation_shift_timeline,
        delete_or_retire_mandate
    )
    engine = get_global_engine()
    session = get_session(engine)
    try:
        init_recommendation_tracker_tables(session)
        sample_assets = [
            {"symbol": "BHEL", "name": "Bharat Heavy", "current_price": 421.45, "shares_to_buy": 8, "composite_score": 88.0, "signal": "BUY", "sector": "Engineering"},
            {"symbol": "MOTHERSON", "name": "Samvardhana", "current_price": 162.0, "shares_to_buy": 22, "composite_score": 84.0, "signal": "BUY", "sector": "Auto"}
        ]
        mid = save_active_recommendation_mandate(
            session,
            name="Test Mandate Lifecycle",
            strategy="TEST_MULTI_ASSET",
            assets=sample_assets,
            source="Monthly SIP Planner",
            monthly_outlay=20000.0,
            notes="Testing mandate tracking"
        )
        assert mid > 0

        # Verify get_tracked_mandates
        all_m = get_tracked_mandates(session, status="ACTIVE")
        assert any(m["id"] == mid for m in all_m)

        # Verify live surveillance
        status_eval = evaluate_mandate_live_status(session, mid)
        assert status_eval["mandate_id"] == mid
        assert len(status_eval["items"]) == 2
        assert "action_items" in status_eval

        # Verify daily shifts computation
        curr_b = [
            {"symbol": "BHEL", "composite_score": 90.0, "signal": "BUY", "current_price": 425.0},
            {"symbol": "TRENT", "composite_score": 85.0, "signal": "BUY", "current_price": 7200.0}
        ]
        shifts = compute_daily_recommendation_shifts(session, curr_b, strategy="TEST_MULTI_ASSET")
        assert "new_additions" in shifts
        assert "dropped_assets" in shifts
        assert "action_summary" in shifts

        # Verify timeline events
        events = get_recommendation_shift_timeline(session, mandate_id=mid)
        assert len(events) >= 2

        # Clean up test mandate
        delete_or_retire_mandate(session, mid, action="DELETE")
    finally:
        session.execute(text("DELETE FROM sip_suggestion_log WHERE strategy = 'TEST_MULTI_ASSET'"))
        session.commit()
        session.close()


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    tests = [
        ("1. MF & Bulk/Block Daily Deltas", test_1_mf_and_bulk_block_daily_deltas),
        ("2. Multi-Asset SIP Daily Audit & Accuracy Tracker", test_2_multi_asset_sip_daily_audit),
        ("3. Missed Alpha & False Negative Surveillance Engine", test_3_missed_alpha_surveillance_audit),
        ("4. Watchlists Complete CRUD Operations", test_4_watchlist_crud_operations),
        ("5. Custom Portfolio Punch-In & Optimization Engine", test_5_custom_portfolio_analyzer),
        ("6. Momentum vs ML Projection Cross-Validation Engine", test_6_momentum_vs_ml_projection_validation),
        ("7. Active Recommendation Mandate & Daily Shift Tracker", test_7_recommendation_mandate_and_shift_tracker),
    ]

    print("===============================================================================")
    print("      RUNNING INTEGRATION VERIFICATION FOR ALL 7 NEW CAPABILITIES")
    print("===============================================================================\n")

    passed = 0
    for name, fn in tests:
        try:
            print(f"▶️ Testing: {name}...", end=" ")
            fn()
            print("✅ PASSED")
            passed += 1
        except Exception as e:
            print(f"❌ FAILED: {e}")
            import traceback
            traceback.print_exc()

    print(f"\nSummary: {passed}/{len(tests)} test suites passed successfully.")
    if passed == len(tests):
        print("🎉 ALL NEW FEATURES VALIDATED AND WORKING CORRECTLY!")
    else:
        sys.exit(1)

