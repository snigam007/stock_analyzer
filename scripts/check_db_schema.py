import sys
sys.stdout.reconfigure(encoding='utf-8')
from sqlalchemy import create_engine, text
engine = create_engine('sqlite:///data/stocks.db')
with engine.connect() as conn:
    tables = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")).fetchall()
    print('All tables:')
    for t in tables:
        print(' ', t[0])
    print()
    # Check stocks table columns
    cols = conn.execute(text("PRAGMA table_info(stocks)")).fetchall()
    print('stocks columns:')
    for c in cols:
        print(f"  {c[1]:30} {c[2]}")
    print()
    # Check if any fundamental data table exists
    for tname in ['fundamentals', 'stock_fundamentals', 'financial_ratios', 'screener_data', 'scoring']:
        try:
            row = conn.execute(text(f"SELECT COUNT(*) FROM {tname}")).scalar()
            cols2 = conn.execute(text(f"PRAGMA table_info({tname})")).fetchall()
            print(f"{tname}: {row} rows, columns: {[c[1] for c in cols2]}")
        except Exception:
            pass
