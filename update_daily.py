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
    cleanup_active_market_data(session)

    # 1. Load active stock list
    stocks = session.query(Stock).filter(Stock.is_active == True).all()
    stock_list = [{"symbol": s.symbol, "yf_symbol": s.yf_symbol, "name": s.name} for s in stocks]
    logger.info(f"Checking database for {len(stock_list)} stocks...")

    # 2. Download index & commodity deltas
    logger.info("\n📊 Step 1/6: Updating Indexes & Commodities...")
    download_indexes_and_commodities(session)

    # 3. Download stock deltas (skips up-to-date stocks instantly)
    logger.info("\n📥 Step 2/6: Checking & Downloading Stock Price Deltas...")
    download_historical_data(stock_list, session)

    # 4. Compute indicators
    logger.info("\n📐 Step 3/6: Computing Technical Indicators...")
    compute_all_indicators(session)

    # 5. Compute scores first (needed before signals for ML forecasts)
    logger.info("\n🎯 Step 4/7: Computing Composite Scores...")
    compute_and_save_scores(session)

    # 6. ML & Time-series forecasts (BEFORE signals so Forecast table is fresh for Fix 4)
    logger.info(f"\n🤖 Step 5/7: Running ML Forecasts for Top {top_forecasts} Stocks...")
    try:
        run_forecasts_for_top_stocks(session, top_n=top_forecasts)
    except Exception as e:
        logger.warning(f"ML forecasting notice: {e}")

    # 7. Generate signals (uses updated Forecast table and regime context)
    logger.info("\n🔔 Step 6/7: Generating Signals with Regime-Aware Stop Losses...")
    generate_all_signals(session)

    # 8. Sector analysis & strategies
    logger.info("\n🏭 Step 7/8: Computing Sector Analysis & Strategies...")
    compute_and_save_sector_analysis(session)
    save_all_strategies(session)

    from core.accuracy_tracker import (
        log_current_signals_to_audit,
        evaluate_signal_audit_track_record,
        update_trailing_stops,
    )
    from sqlalchemy import text

    logger.info("\n📋 Step 8/8: Signal Audit — Log, Trail & Evaluate...")
    try:
        # Log today's new signals
        logged = log_current_signals_to_audit(session)
        logger.info(f"   Snapshotted {logged} new BUY/SELL signals to audit log.")
        # Update trailing stops on all open positions
        trailed = update_trailing_stops(session)
        if trailed:
            logger.info(f"   Updated {trailed} trailing stops.")
        # Evaluate and PERSIST outcomes for historical signals
        stats = evaluate_signal_audit_track_record(session)
        logger.info(
            f"   Audit: {stats['total_signals_tracked']} total | "
            f"{stats['completed_signals']} resolved | "
            f"T1 rate: {stats['target_1_hit_rate_pct']}% | "
            f"SL rate: {stats['stop_loss_hit_rate_pct']}% | "
            f"Win rate: {stats['overall_win_rate_pct']}%"
        )
    except Exception as e:
        logger.warning(f"Signal audit evaluation notice: {e}")

    # 9. Advanced Analysis Suites (Candlestick Patterns, Alerts, Bulk Deals, Calendar)
    logger.info("\n🕯️ Step 9/12: Scanning Candlestick Formations (15 Patterns)...")
    try:
        from core.candlestick_patterns import batch_scan_candlestick_patterns
        p_cnt = batch_scan_candlestick_patterns(session)
        logger.info(f"   Detected and indexed {p_cnt} candlestick pattern formations.")
    except Exception as e:
        logger.warning(f"Candlestick scan notice: {e}")

    logger.info("\n⭐ Step 10/11: Evaluating 52-Week High/Low Radar & Watchlist Alerts...")
    try:
        from core.watchlist_manager import evaluate_and_generate_alerts
        alerts = evaluate_and_generate_alerts(session)
        logger.info(f"   Generated {len(alerts)} real-time breakout / target alerts.")
    except Exception as e:
        logger.warning(f"Alerts evaluation notice: {e}")

    logger.info("\n🏦 Step 11/12: Syncing Institutional Bulk/Block Deals & Economic Calendar...")
    try:
        from core.bulk_deals import fetch_latest_bulk_deals
        from core.economic_calendar import seed_macro_calendar
        deals_count = fetch_latest_bulk_deals(session)
        cal_count = seed_macro_calendar(session)
        logger.info(f"   Synced {deals_count} bulk deals and verified economic calendar schedule.")
    except Exception as e:
        logger.warning(f"Institutional/Calendar sync notice: {e}")

    logger.info("\n🔍 Step 12/12: Running Missed Alpha & False Negative Surveillance...")
    try:
        from core.missed_signals import scan_missed_opportunities
        m_rep = scan_missed_opportunities(session, lookback_days=5, min_gain_pct=4.0)
        m_s = m_rep["summary"]
        logger.info(f"   Surveillance: {m_s.get('total_movers_detected', 0)} fast movers | {m_s.get('missed_movers_count', 0)} uncaught on WATCH | Top bottleneck: {m_s.get('top_bottleneck_factor', 'None')}")
    except Exception as e:
        logger.warning(f"Missed mover surveillance notice: {e}")

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
