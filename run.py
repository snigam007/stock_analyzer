"""
run.py — Single Point of Execution for Indian Stock Analyzer & Financial Powerhouse

Provides an interactive menu & CLI flags for:
1. 🚀 Just Run App (Instant Launch)
2. ⚡ Daily Delta Update & Launch (Delta download + update analysis + run)
3. 🔄 Complete Analysis Refresh & Launch (Recompute all 15 indicators, scores & ML without re-downloading)
4. 🌐 Full Deep Update & Launch (Complete historical data download & rebuild)
5. 🛠️ First-Time Setup & Execution (Fresh environment & scratch DB build)

Usage:
  python run.py                     (Interactive Menu)
  python run.py --mode run          (Instant Launch)
  python run.py --mode daily        (Daily Delta Update & Launch)
  python run.py --mode refresh      (Recalculate Analysis & Launch)
  python run.py --mode full         (Deep Re-download & Launch)
  python run.py --mode setup        (First-Time Fresh Setup & Launch)
"""
import os
import sys
import time
import subprocess
import argparse
import logging
from pathlib import Path

# Setup paths & environment
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Launcher")


def print_banner():
    banner = r"""
================================================================================
   🏛️  INDIAN STOCK ANALYZER & INSTITUTIONAL ADVISORY POWERHOUSE
================================================================================
   • 285+ NSE Equities | 15 Benchmark Indexes | 7 Commodities
   • 5-Model ML Ensemble Consensus | Champion Strategy Backtesting (10 Alg)
   • 3-Tranche Scaling | Macro Regime & Asset Allocation | F&O Derivatives
================================================================================
"""
    print(banner)


def check_db_exists() -> bool:
    """Check if the SQLite database exists and has data."""
    db_path = BASE_DIR / "data" / "stock_analyzer.db"
    return db_path.exists() and db_path.stat().st_size > 100000


def find_available_port(start_port: int = 8501, max_tries: int = 10) -> int:
    """Find the first available open port to avoid 'Port already in use' collisions."""
    import socket
    for p in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start_port


def launch_streamlit(port: int = 8501):
    """Launch the Streamlit web application on an open port."""
    available_port = find_available_port(port)
    if available_port != port:
        logger.warning(f"⚠️ Port {port} is occupied. Automatically routing to open port {available_port}...")
    logger.info(f"\n🚀 Launching Streamlit App on http://localhost:{available_port} ...")
    app_main = str(BASE_DIR / "app" / "main.py")
    
    # Try finding streamlit inside virtualenv or PATH
    python_exe = sys.executable
    venv_streamlit = BASE_DIR / "venv" / "Scripts" / "streamlit.exe"
    if venv_streamlit.exists():
        cmd = [str(venv_streamlit), "run", app_main, f"--server.port={available_port}", "--server.headless=false"]
    else:
        cmd = [python_exe, "-m", "streamlit", "run", app_main, f"--server.port={available_port}", "--server.headless=false"]
    
    try:
        subprocess.run(cmd, cwd=str(BASE_DIR))
    except KeyboardInterrupt:
        logger.info("\n🛑 Application stopped by user.")


def run_daily_delta(launch: bool = True):
    """Option 2: Daily Delta Update & Launch."""
    start_time = time.time()
    logger.info("\n" + "=" * 65)
    logger.info("  ⚡ EXECUTING: DAILY DELTA UPDATE")
    logger.info("=" * 65)
    
    from db.database import get_global_engine, get_session, Stock
    from core.data_fetcher import (
        download_historical_data, download_indexes_and_commodities,
        cleanup_active_market_data, is_indian_market_closed
    )
    from core.indicators import compute_all_indicators
    from core.scoring import compute_and_save_scores
    from core.signals import generate_all_signals
    from core.sector_analysis import compute_and_save_sector_analysis
    from core.strategies import save_all_strategies
    from core.ml_models import run_forecasts_for_top_stocks
    from core.accuracy_tracker import log_current_signals_to_audit, evaluate_signal_audit_track_record
    from core.sip_tracker import init_sip_log_table, update_sip_forward_performance

    engine = get_global_engine()
    session = get_session(engine)

    # Clean any unfinalized data if market is active today
    cleanup_active_market_data(session)

    stocks = session.query(Stock).filter(Stock.is_active == True).all()
    stock_list = [{"symbol": s.symbol, "yf_symbol": s.yf_symbol, "name": s.name} for s in stocks]
    logger.info(f"Checking database for {len(stock_list)} stocks...")

    logger.info("📊 Step 1/7: Updating Indexes & Commodities deltas...")
    download_indexes_and_commodities(session)

    logger.info("📥 Step 2/7: Checking & downloading stock price deltas...")
    download_historical_data(stock_list, session)

    logger.info("📐 Step 3/7: Updating Technical Indicators...")
    compute_all_indicators(session)

    logger.info("🎯 Step 4/7: Recomputing Composite Scores & Signals...")
    compute_and_save_scores(session)
    generate_all_signals(session)

    logger.info("🏭 Step 5/7: Updating Sector Analysis & Strategies...")
    compute_and_save_sector_analysis(session)
    save_all_strategies(session)

    logger.info("🤖 Step 6/7: Running ML Ensemble Forecasts for Top 50 Stocks...")
    try:
        run_forecasts_for_top_stocks(session, top_n=50)
    except Exception as e:
        logger.warning(f"ML forecasting notice: {e}")

    logger.info("🎯 Step 7/7: Logging Daily Prediction Audit Snapshot...")
    try:
        logged = log_current_signals_to_audit(session)
        evaluate_signal_audit_track_record(session)
        logger.info(f"✅ Audit logged: {logged} daily signals snapshotted for future performance verification.")
    except Exception as e:
        logger.warning(f"Audit log notice: {e}")

    logger.info("📋 Step 8/8: Updating SIP Suggestion Forward Performance...")
    try:
        init_sip_log_table(session)
        sip_updated = update_sip_forward_performance(session)
        logger.info(f"✅ SIP tracker: {sip_updated} open positions evaluated.")
    except Exception as e:
        logger.warning(f"SIP tracker notice: {e}")

    session.close()
    elapsed = time.time() - start_time
    logger.info("=" * 65)
    logger.info(f"✅ DAILY UPDATE COMPLETE in {elapsed:.1f}s ({elapsed/60:.1f} mins)")
    logger.info("=" * 65)

    if launch:
        launch_streamlit()


def run_complete_analysis_refresh(launch: bool = True):
    """Option 3: Complete Analysis Refresh without re-downloading prices."""
    start_time = time.time()
    logger.info("\n" + "=" * 65)
    logger.info("  🔄 EXECUTING: COMPLETE ANALYSIS REFRESH (NO RE-DOWNLOAD)")
    logger.info("=" * 65)

    from db.database import get_global_engine, get_session
    from core.indicators import compute_all_indicators
    from core.scoring import compute_and_save_scores
    from core.signals import generate_all_signals
    from core.sector_analysis import compute_and_save_sector_analysis
    from core.strategies import save_all_strategies
    from core.ml_models import run_forecasts_for_top_stocks
    from core.accuracy_tracker import log_all_multi_asset_signals_to_audit, evaluate_signal_audit_track_record

    engine = get_global_engine()
    session = get_session(engine)

    logger.info("📐 Step 1/5: Recomputing All 15 Technical Indicators...")
    compute_all_indicators(session)

    logger.info("🎯 Step 2/5: Recalculating Multi-Factor Composite Scores & Signals...")
    compute_and_save_scores(session)
    generate_all_signals(session)

    logger.info("🏭 Step 3/5: Recalculating Sector Performance & Strategies...")
    compute_and_save_sector_analysis(session)
    save_all_strategies(session)

    logger.info("🤖 Step 4/5: Rebuilding ML Forecasts for Top 50 Stocks...")
    try:
        run_forecasts_for_top_stocks(session, top_n=50)
    except Exception as e:
        logger.warning(f"ML forecast notice: {e}")

    logger.info("🎯 Step 5/5: Updating Multi-Asset Prediction Audit Log...")
    try:
        logged_res = log_all_multi_asset_signals_to_audit(session)
        evaluate_signal_audit_track_record(session, asset_type="ALL")
        logger.info(f"✅ Audit updated: {logged_res['total_logged']} multi-asset signals recorded.")
    except Exception as e:
        logger.warning(f"Audit log notice: {e}")

    session.close()
    elapsed = time.time() - start_time
    logger.info("=" * 65)
    logger.info(f"✅ COMPLETE ANALYSIS REFRESHED in {elapsed:.1f}s ({elapsed/60:.1f} mins)")
    logger.info("=" * 65)

    if launch:
        launch_streamlit()


def run_full_deep_update(launch: bool = True):
    """Option 4: Full Deep Update (Historical Data Backfill & Rebuild)."""
    start_time = time.time()
    logger.info("\n" + "=" * 65)
    logger.info("  🌐 EXECUTING: FULL DEEP DATA UPDATE & REBUILD")
    logger.info("=" * 65)

    from initialize import run_full_initialization
    run_full_initialization()

    elapsed = time.time() - start_time
    logger.info("=" * 65)
    logger.info(f"✅ FULL DEEP UPDATE COMPLETED in {elapsed/60:.1f} minutes")
    logger.info("=" * 65)

    if launch:
        launch_streamlit()


def run_first_time_setup(launch: bool = True):
    """Option 5: First-Time Setup & Execution (Scratch Install)."""
    start_time = time.time()
    logger.info("\n" + "=" * 65)
    logger.info("  🛠️ EXECUTING: FIRST-TIME SETUP & INITIALIZATION")
    logger.info("=" * 65)

    # 1. Initialize DB tables and load universe
    from db.database import create_all_tables
    from initialize import run_full_initialization

    logger.info("📦 Creating SQLite tables and initial indexes...")
    create_all_tables()

    logger.info("🌐 Running complete initial data pull & analytics pipeline...")
    run_full_initialization()

    elapsed = time.time() - start_time
    logger.info("=" * 65)
    logger.info(f"🎉 SETUP COMPLETED SUCCESSFULLY in {elapsed/60:.1f} minutes!")
    logger.info("=" * 65)

    if launch:
        launch_streamlit()


def interactive_menu():
    """Interactive CLI menu for single-point execution."""
    print_banner()
    db_ok = check_db_exists()

    status_str = "🟢 Ready" if db_ok else "🟡 Not Initialized (Run Option 5 first)"
    print(f"   Database Status: {status_str}\n")
    print("   Please select an execution mode:")
    print("   -------------------------------------------------------------------------")
    print("   [1] 🚀 Just Run App                    (Instant Launch at http://localhost:8501)")
    print("   [2] ⚡ Daily Delta Update & Run        (Download only delta trading days & update)")
    print("   [3] 🔄 Complete Analysis Refresh & Run (Recalculate indicators & ML without download)")
    print("   [4] 🌐 Full Deep Update & Run          (Re-download full history & complete rebuild)")
    print("   [5] 🛠️ First-Time Setup & Run          (Fresh scratch install & database creation)")
    print("   -------------------------------------------------------------------------")
    print("   [Q] ❌ Exit\n")

    choice = input("   👉 Enter your choice [1-5 or Q] (Default: 1): ").strip().upper()

    if not choice or choice == "1":
        if not db_ok:
            print("\n⚠️ Database is empty or not created yet.")
            sub_choice = input("Would you like to run First-Time Setup now? (y/n): ").strip().lower()
            if sub_choice == "y":
                run_first_time_setup(launch=True)
                return
        launch_streamlit()
    elif choice == "2":
        run_daily_delta(launch=True)
    elif choice == "3":
        run_complete_analysis_refresh(launch=True)
    elif choice == "4":
        run_full_deep_update(launch=True)
    elif choice == "5":
        run_first_time_setup(launch=True)
    elif choice in ["Q", "QUIT", "EXIT"]:
        print("\n👋 Exiting. Have a great trading day!")
        sys.exit(0)
    else:
        print(f"\n❌ Invalid option '{choice}'. Defaulting to Fast Launch...")
        launch_streamlit()


def main():
    parser = argparse.ArgumentParser(description="Single Point of Execution for Stock Analyzer")
    parser.add_argument(
        "--mode",
        choices=["run", "daily", "refresh", "full", "setup"],
        help="Execution mode (skips interactive menu)"
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Execute pipeline without launching Streamlit web UI"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8501,
        help="Streamlit port (default: 8501)"
    )
    args = parser.parse_args()

    launch = not args.no_launch

    if args.mode == "run":
        launch_streamlit(port=args.port)
    elif args.mode == "daily":
        run_daily_delta(launch=launch)
    elif args.mode == "refresh":
        run_complete_analysis_refresh(launch=launch)
    elif args.mode == "full":
        run_full_deep_update(launch=launch)
    elif args.mode == "setup":
        run_first_time_setup(launch=launch)
    else:
        interactive_menu()


if __name__ == "__main__":
    main()