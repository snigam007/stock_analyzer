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

    # 5. Compute scores & signals
    logger.info("\n🎯 Step 4/6: Computing Composite Scores & Signals...")
    compute_and_save_scores(session)
    generate_all_signals(session)

    # 6. Sector analysis & strategies
    logger.info("\n🏭 Step 5/6: Computing Sector Analysis & Strategies...")
    compute_and_save_sector_analysis(session)
    save_all_strategies(session)

    # 7. ML & Time-series forecasts
    logger.info(f"\n🤖 Step 6/6: Running ML Forecasts for Top {top_forecasts} Stocks...")
    run_forecasts_for_top_stocks(session, top_n=top_forecasts)

    session.close()
    elapsed = time.time() - start_time
    logger.info("=" * 65)
    logger.info(f"✅ DAILY UPDATE COMPLETE in {elapsed:.1f} seconds ({elapsed/60:.1f} mins)")
    logger.info("   Refresh your browser at http://localhost:8501")
    logger.info("=" * 65)


if __name__ == "__main__":
    run_daily_delta_update()
