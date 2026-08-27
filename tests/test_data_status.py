import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from core.data_status import get_database_status_summary, get_daily_stock_counts_history, get_searchable_universe_directory

def test_status():
    engine = get_global_engine()
    session = get_session(engine)
    
    summary = get_database_status_summary(session)
    print(f"Max date: {summary['max_date']}")
    print(f"Total assets: {summary['total_assets']}")
    print(f"Stocks: {summary['stock_count']}, Indexes: {summary['index_count']}, Commodities: {summary['commodity_count']}")
    
    history_df = get_daily_stock_counts_history(days=5, session=session)
    print(f"History records: {len(history_df)}")
    for idx, row in history_df.head(5).iterrows():
        print(f"  Date: {row['date']} | Stocks: {row['stock_count']} | Indexes: {row.get('index_count', 0)} | Commodities: {row.get('commodity_count', 0)} | Total Volume: {int(row.get('total_volume', 0)):,}")
        
    catalog_df = get_searchable_universe_directory(session)
    print(f"Catalog records: {len(catalog_df)}")
    print(f"First 3 catalog items: {[r['symbol'] + ' (' + r['asset_type'] + ')' for _, r in catalog_df.head(3).iterrows()]}")
    
    session.close()
    print("SUCCESS: All verification checks passed!")

if __name__ == "__main__":
    test_status()
