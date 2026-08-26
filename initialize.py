"""
initialize.py — One-time setup and initial data download
Run this ONCE before launching the Streamlit app.

Steps:
1. Create all database tables
2. Load stock universe from YAML
3. Download full historical data (2000-present) for all stocks
4. Compute indicators, scores, signals, forecasts
5. Compute sector analysis and strategies
"""
import logging
import sys
import time
from pathlib import Path
from datetime import date

import yaml
from sqlalchemy.orm import Session

# Setup path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from config.settings import LOG_DIR, LOG_LEVEL, DOWNLOAD_START_DATE
from db.database import create_all_tables, get_global_engine, get_session, Stock

# ─── Logging Setup ────────────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "initialize.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)


def load_stock_universe(session: Session) -> list:
    """Load stock universe from YAML and populate stocks table."""
    yaml_path = BASE_DIR / "config" / "stocks.yaml"
    with open(yaml_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    stocks_created = 0
    stock_list = []

    for sector_name, sector_data in config.get("sectors", {}).items():
        for stock_cfg in sector_data.get("stocks", []):
            symbol = stock_cfg["symbol"].strip()
            # Build yfinance symbol
            yf_symbol = symbol + ".NS"

            existing = session.query(Stock).filter(Stock.symbol == symbol).first()
            if existing is None:
                stock = Stock(
                    symbol=symbol,
                    yf_symbol=yf_symbol,
                    name=stock_cfg.get("name", symbol),
                    sector=sector_name,
                    exchange="NSE",
                    market_cap_tier=stock_cfg.get("market_cap_tier", "mid"),
                    instrument_type="stock",
                    is_active=True,
                )
                session.add(stock)
                stocks_created += 1

            stock_list.append({
                "symbol": symbol,
                "yf_symbol": yf_symbol,
                "name": stock_cfg.get("name", symbol),
                "sector": sector_name,
            })

    session.commit()
    logger.info(f"✅ Stock universe loaded: {stocks_created} new stocks added ({len(stock_list)} total)")
    return stock_list


def run_full_initialization():
    """Complete initialization pipeline."""
    start_time = time.time()
    logger.info("=" * 70)
    logger.info("  INDIAN STOCK ANALYZER — INITIALIZATION")
    logger.info("=" * 70)

    # Step 1: Create database
    logger.info("\n📦 Step 1/8: Creating database tables...")
    engine = create_all_tables()
    session = get_session(engine)
    logger.info("✅ Database ready")

    # Step 2: Load stock universe
    logger.info("\n📋 Step 2/8: Loading stock universe...")
    stock_list = load_stock_universe(session)
    logger.info(f"✅ Loaded {len(stock_list)} stocks across sectors")

    # Step 3: Download indexes & commodities
    logger.info("\n🌐 Step 3/8: Downloading index & commodity data...")
    from core.data_fetcher import download_indexes_and_commodities
    download_indexes_and_commodities(session)

    # Step 4: Download historical stock data
    logger.info(f"\n📥 Step 4/8: Downloading historical stock data from {DOWNLOAD_START_DATE}...")
    logger.info("   ⚠️  This may take 30-90 minutes for 500 stocks.")
    logger.info("   ℹ️  Random delays used to avoid bot detection.")

    from core.data_fetcher import download_historical_data

    processed_count = [0]
    def progress(current, total, name):
        processed_count[0] = current
        pct = current / total * 100
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        print(f"\r  [{bar}] {pct:.0f}% ({current}/{total}) — {name[:30]:<30}", end="", flush=True)

    download_historical_data(stock_list, session, progress_callback=progress)
    print()  # New line after progress bar

    # Step 5: Compute indicators
    logger.info("\n📊 Step 5/8: Computing technical indicators...")
    from core.indicators import compute_all_indicators
    compute_all_indicators(session, progress_callback=progress)
    print()

    # Step 6: Compute scores
    logger.info("\n🎯 Step 6/8: Computing composite scores...")
    from core.scoring import compute_and_save_scores
    compute_and_save_scores(session, progress_callback=progress)
    print()

    # Step 7: Generate signals
    logger.info("\n🚦 Step 7/8: Generating BUY/SELL/WATCH signals...")
    from core.signals import generate_all_signals
    generate_all_signals(session, progress_callback=progress)
    print()

    # Step 8: Sector analysis + strategies
    logger.info("\n🏭 Step 8/8: Computing sector analysis & strategies...")
    from core.sector_analysis import compute_and_save_sector_analysis
    from core.strategies import save_all_strategies
    compute_and_save_sector_analysis(session)
    save_all_strategies(session, progress_callback=progress)
    print()

    # Optional: ML Forecasts (for top 50 stocks)
    logger.info("\n🤖 Bonus: Running ML forecasts for top 50 stocks...")
    try:
        from core.ml_models import run_forecasts_for_top_stocks
        run_forecasts_for_top_stocks(session, top_n=50, progress_callback=progress)
        print()
    except Exception as e:
        logger.warning(f"ML forecasting skipped: {e}")

    session.close()
    elapsed = (time.time() - start_time) / 60
    logger.info("=" * 70)
    logger.info(f"✅ INITIALIZATION COMPLETE in {elapsed:.1f} minutes")
    logger.info("   Run: streamlit run app/main.py")
    logger.info("=" * 70)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Initialize Stock Analyzer DB")
    parser.add_argument("--skip-download", action="store_true", help="Skip data download")
    args = parser.parse_args()

    if args.skip_download:
        logger.info("Skipping download — only creating DB and loading stock universe")
        engine = create_all_tables()
        session = get_session(engine)
        load_stock_universe(session)
        session.close()
    else:
        run_full_initialization()
