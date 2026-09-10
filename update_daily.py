"""
Incremental Daily Market Refresh & Delta Downloader
- Checks stored data in database first
- Downloads ONLY new/missing trading days (delta)
- Recalculates indicators, composite scores, signals, targets, sector analysis, and strategies
- Fast execution (5-15 seconds when mostly up-to-date)
"""
import sys
import time
import logging
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("update_daily")

from db.database import get_global_engine, get_session, Stock
from core.data_fetcher import (
    download_historical_data,
    download_indexes_and_commodities,
    get_all_prices_dataframe,
    cleanup_active_market_data,
    is_indian_market_closed,
)
from core.indicators import compute_all_indicators
from core.scoring import compute_and_save_scores
from core.signals import generate_all_signals
from core.sector_analysis import compute_and_save_sector_analysis
from core.strategies import save_all_strategies
from core.ml_models import run_forecasts_for_top_stocks


def run_daily_delta_update(top_forecasts: int = 50):
    start_time = time.time()
    logger.info("=" * 65)
    logger.info("  INDIAN STOCK ANALYZER — DAILY DELTA UPDATE")
    logger.info("=" * 65)

    engine = get_global_engine()
    session = get_session(engine)

    # 0. Clean unfinalized data if market is active today
    # 0. Clean unfinalized data if market is active today
    cleanup_active_market_data(session)

    # 1. Load active stock list
    stocks = session.query(Stock).filter(Stock.is_active == True).all()
    stock_list = [{"symbol": s.symbol, "yf_symbol": s.yf_symbol, "name": s.name} for s in stocks]
    logger.info(f"Checking database for {len(stock_list)} active stocks...")

    # 2. Download index & commodity deltas
    logger.info("\n📊 Step 1/14: Updating Indexes & Commodities Deltas (Multi-Day)...")
    download_indexes_and_commodities(session)

    # 3. Download stock deltas (skips up-to-date stocks instantly)
    logger.info("\n📥 Step 2/14: Checking & Downloading Stock Price Deltas (Multi-Day)...")
    download_historical_data(stock_list, session)

    # 4. Compute indicators
    logger.info("\n📐 Step 3/14: Computing Technical Indicators (15 Indicators)...")
    compute_all_indicators(session)

    # 5. Compute scores first (needed before signals for ML forecasts)
    logger.info("\n🎯 Step 4/14: Computing 5-Pillar Apex Composite Scores...")
    compute_and_save_scores(session)

    # 6. ML & Time-series forecasts (BEFORE signals so Forecast table is fresh for Fix 4)
    logger.info(f"\n🤖 Step 5/14: Running ML Forecasts for Top {top_forecasts} Stocks...")
    try:
        run_forecasts_for_top_stocks(session, top_n=top_forecasts)
    except Exception as e:
        logger.warning(f"ML forecasting notice: {e}")

    # 7. Generate signals (uses updated Forecast table and regime context)
    logger.info("\n🔔 Step 6/14: Generating Signals with Regime-Aware Stop Losses...")
    generate_all_signals(session)

    # 8. Sector analysis & strategies
    logger.info("\n🏭 Step 7/14: Computing Sector Analysis & Strategies...")
    compute_and_save_sector_analysis(session)
    save_all_strategies(session)

    from core.accuracy_tracker import (
        log_all_multi_asset_signals_to_audit,
        evaluate_signal_audit_track_record,
        update_trailing_stops,
    )
    from sqlalchemy import text

    logger.info("\n📋 Step 8/14: Multi-Asset Signal Audit — Log, Trail & Evaluate...")
    try:
        logged_res = log_all_multi_asset_signals_to_audit(session)
        logger.info(f"   Snapshotted {logged_res['total_logged']} multi-asset signals to audit log (Stocks: {logged_res['stocks_logged']}, Indices: {logged_res['indexes_logged']}, Commodities: {logged_res['commodities_logged']}, Breakouts: {logged_res['breakouts_logged']}).")
        trailed = update_trailing_stops(session)
        if trailed:
            logger.info(f"   Updated {trailed} trailing stops.")
        stats = evaluate_signal_audit_track_record(session, asset_type="ALL")
        logger.info(
            f"   Audit: {stats['total_signals_tracked']} total | "
            f"{stats['completed_signals']} resolved | "
            f"T1 rate: {stats['target_1_hit_rate_pct']}% | "
            f"SL rate: {stats['stop_loss_hit_rate_pct']}% | "
            f"Win rate: {stats['overall_win_rate_pct']}%"
        )
    except Exception as e:
        logger.warning(f"Signal audit evaluation notice: {e}")

    # 9. Update SIP Suggestion Forward Performance Track Record & Snapshot Today's Baskets
    logger.info("\n💰 Step 9/14: Tracking SIP Recommendations & Auto-Snapshotting Baskets...")
    try:
        from core.sip_tracker import init_sip_log_table, update_sip_forward_performance, log_sip_basket
        from core.monthly_sip_advisor import generate_monthly_sip_basket
        init_sip_log_table(session)
        sip_res = update_sip_forward_performance(session)
        if sip_res:
            logger.info(f"   SIP Track Record: Evaluated and updated {sip_res} open recommendations.")

        b_stocks = generate_monthly_sip_basket(session, monthly_wallet=20000, strategy="PURE_STOCKS", include_mutual_funds=False)
        n_stocks = log_sip_basket(session, b_stocks, strategy="PURE_STOCKS", exit_protocol="STRUCTURAL_TRAILING")
        b_multi = generate_monthly_sip_basket(session, monthly_wallet=20000, strategy="MULTI_ASSET", include_mutual_funds=True, mf_allocation_pct=40)
        n_multi = log_sip_basket(session, b_multi, strategy="MULTI_ASSET", exit_protocol="STRUCTURAL_TRAILING")
        logger.info(f"   SIP Recommendations: Auto-snapshotted daily baseline baskets (Stocks: {n_stocks}, Multi-Asset/MF: {n_multi}).")
    except Exception as e:
        logger.warning(f"SIP forward tracker notice: {e}")

    # 10. Candlestick Formations
    logger.info("\n🕯️ Step 10/14: Scanning Candlestick Formations (15 Patterns)...")
    try:
        from core.candlestick_patterns import batch_scan_candlestick_patterns
        p_cnt = batch_scan_candlestick_patterns(session)
        logger.info(f"   Detected and indexed {p_cnt} candlestick pattern formations.")
    except Exception as e:
        logger.warning(f"Candlestick scan notice: {e}")

    # 11. 52-Week High/Low Radar & Watchlist Alerts
    logger.info("\n⭐ Step 11/14: Evaluating 52-Week High/Low Radar & Watchlist Alerts...")
    try:
        from core.watchlist_manager import evaluate_and_generate_alerts
        alerts = evaluate_and_generate_alerts(session)
        logger.info(f"   Generated {len(alerts)} real-time breakout / target alerts.")
    except Exception as e:
        logger.warning(f"Alerts evaluation notice: {e}")

    # 12. Mutual Fund NAV Delta Sync
    logger.info("\n🏦 Step 12/14: Syncing Mutual Fund NAV Deltas (Multi-Day Catchup & AMFI Live Feed)...")
    try:
        from core.mf_fetcher import sync_all_mf_nav_deltas
        mf_res = sync_all_mf_nav_deltas(session)
        logger.info(f"   MF NAV Delta: {mf_res.get('new_navs_added', 0)} daily NAV records synced across {mf_res.get('schemes_updated', 0)} schemes (Latest: {mf_res.get('latest_nav_date')}).")
    except Exception as e:
        logger.warning(f"Mutual Fund delta sync notice: {e}")

    # 13. Institutional Bulk & Block Deals Delta Sync & Macro Calendar
    logger.info("\n🐋 Step 13/14: Syncing Institutional Bulk & Block Deals & Macro Calendar...")
    try:
        from core.bulk_deals import sync_bulk_and_block_deals_delta
        from core.economic_calendar import seed_macro_calendar

        deals_res = sync_bulk_and_block_deals_delta(session, force_full=False)
        deals_count = deals_res.get("new_deals_added", 0) + deals_res.get("existing_deals_updated", 0)
        net_flow = deals_res.get("net_delta_flow_cr", 0.0)
        logger.info(f"   Institutional Deals Delta: Synced {deals_count} bulk/block deals (Net Institutional Flow: ₹{net_flow:+,.2f} Cr, Latest Session: {deals_res.get('latest_deal_date')}).")

        cal_count = seed_macro_calendar(session)
        logger.info(f"   Economic Calendar: verified {cal_count} scheduled macro releases.")
    except Exception as e:
        logger.warning(f"Institutional deals / calendar sync notice: {e}")

    # 14. Surveillance Audit
    logger.info("\n🔍 Step 14/14: Running Missed Alpha & False Negative Surveillance Audit...")
    try:
        from core.missed_signals import log_daily_missed_alpha_audit
        audit_res = log_daily_missed_alpha_audit(session, lookback_days=5, min_gain_pct=4.0)
        logger.info(
            f"   Surveillance Audit: {audit_res.get('total_movers', 0)} total movers | "
            f"{audit_res.get('caught_count', 0)} caught by BUY ({audit_res.get('capture_rate_pct', 0.0)}%) | "
            f"{audit_res.get('missed_count', 0)} uncaught (Logged {audit_res.get('new_records_logged', 0)} records) | "
            f"Top Bottleneck: {audit_res.get('top_bottleneck', 'None')}"
        )
    except Exception as e:
        logger.warning(f"Missed mover surveillance audit notice: {e}")

    session.close()

    # Flush SQLite WAL to database file
    try:
        with engine.connect() as conn:
            conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
            conn.commit()
    except Exception as e:
        logger.warning(f"WAL checkpoint notice: {e}")

    elapsed = time.time() - start_time
    logger.info("=" * 65)
    logger.info(f"✅ DAILY UPDATE COMPLETE in {elapsed:.1f} seconds ({elapsed/60:.1f} mins)")
    logger.info("   Refresh your browser at http://localhost:8501")
    logger.info("=" * 65)


if __name__ == "__main__":
    run_daily_delta_update()
