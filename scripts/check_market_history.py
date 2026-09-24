import sys
from pathlib import Path
import pandas as pd
from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from db.database import get_session, get_global_engine

session = get_session(get_global_engine())
try:
    # 1. Check index symbols
    q_bench = """
        SELECT s.symbol, s.name, COUNT(p.date) as cnt, MIN(p.date) as min_d, MAX(p.date) as max_d
        FROM stocks s
        LEFT JOIN daily_prices p ON s.symbol = p.symbol
        WHERE s.symbol LIKE '%NIFTY%' OR s.symbol LIKE '%BEES%' OR s.symbol LIKE '%^%' OR s.symbol = 'NIFTY'
        GROUP BY s.symbol
    """
    rows_b = session.execute(text(q_bench)).fetchall()
    print("Benchmark / Index Symbols in stocks table:")
    for r in rows_b:
        print(f"  {r[0]} ({r[1]}): {r[2]} rows from {r[3]} to {r[4]}")

    # Check how NIFTY or market benchmark is represented
    q_all_syms = "SELECT DISTINCT symbol FROM daily_prices WHERE symbol LIKE '%INDEX%' OR symbol LIKE '%NIFTY%' OR symbol LIKE '%^%' OR symbol LIKE '%BEES%'"
    syms = [r[0] for r in session.execute(text(q_all_syms)).fetchall()]
    print("Found symbols:", syms)

    # Let's inspect average market prices over time if no index
    q_mkt = """
        SELECT date, AVG(close) as avg_close, COUNT(*) as n_stocks
        FROM daily_prices
        WHERE date >= '2015-01-01'
        GROUP BY date
        ORDER BY date ASC
    """
    rows = session.execute(text(q_mkt)).fetchall()
    if rows:
        df = pd.DataFrame([dict(r._mapping) for r in rows])
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        print(f"Market data points: {len(df)}, from {df['date'].min().date()} to {df['date'].max().date()}")
        print(f"Starting avg price: {df['avg_close'].iloc[0]:.2f}, Ending avg price: {df['avg_close'].iloc[-1]:.2f}")

        df['year'] = df['date'].dt.year
        for yr, grp in df.groupby('year'):
            ret = (grp['avg_close'].iloc[-1] / grp['avg_close'].iloc[0] - 1) * 100
            print(f"Year {yr}: {ret:+.2f}% (start: {grp['avg_close'].iloc[0]:.1f}, end: {grp['avg_close'].iloc[-1]:.1f}, stocks: {grp['n_stocks'].mean():.0f})")

    else:
        print("No dedicated NIFTY symbol found, checking fallback...")

    # 3. Check active universe count over time
    q_stocks = """
        SELECT strftime('%Y', date) as yr, COUNT(DISTINCT symbol) as sym_count, COUNT(*) as row_count
        FROM daily_prices
        WHERE date >= '2015-01-01'
        GROUP BY yr
        ORDER BY yr ASC
    """
    rows_s = session.execute(text(q_stocks)).fetchall()
    print("\nUniverse coverage by year:")
    for r in rows_s:
        print(f"  Year {r[0]}: {r[1]} symbols ({r[2]:,} records)")
finally:
    session.close()
