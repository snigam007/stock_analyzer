"""
scripts/download_all_1h_data.py
Orchestration Script: Download 1-Hour Intraday Candles for All Active Stocks
Stores up to 2 years of 1H data in SQLite (data/stock_analyzer.db).
"""

import sys
import time
from pathlib import Path

# Add root directory to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.hourly_fetcher import (
    init_hourly_db,
    get_active_symbols,
    download_all_hourly_data,
    get_hourly_data_status
)


def main():
    print("=" * 90)
    print("   QUANTUM INGESTION ENGINE: DOWNLOADING 1-HOUR INTRADAY CANDLES FOR ALL STOCKS")
    print("=" * 90)
    print("Database Target: data/stock_analyzer.db -> table: hourly_prices")
    print("Horizon: 2 Years (Max supported by yfinance at 1h granularity)")
    print("=" * 90 + "\n")

    init_hourly_db()
    symbols = get_active_symbols()
    print(f"Discovered {len(symbols)} active equity symbols in database.\n")

    t0 = time.time()
    # Batch size 20 with 1.5s delay to remain well within Yahoo Finance limits
    stats = download_all_hourly_data(batch_size=20, delay_between_batches=1.2)

    db_status = get_hourly_data_status()
    total_time = round(time.time() - t0, 1)

    print("\n" + "=" * 90)
    print("   INGESTION COMPLETE — SUMMARY & COVERAGE AUDIT")
    print("=" * 90)
    print(f"Total Tickers Processed:    {stats['total_symbols']}")
    print(f"Successfully Stored:        {stats['successful_symbols']} stocks")
    print(f"Total Hourly Rows Ingested: {stats['total_rows_inserted']:,}")
    print(f"Total Elapsed Time:         {total_time}s ({total_time / 60:.1f} mins)")
    print("-" * 90)
    print(f"Database Distinct Symbols:  {db_status['distinct_symbols']}")
    print(f"Database Total Hourly Rows: {db_status['total_rows']:,}")
    print(f"Earliest Timestamp:         {db_status['earliest']}")
    print(f"Latest Timestamp:           {db_status['latest']}")
    print("=" * 90 + "\n")


if __name__ == "__main__":
    main()
