import sys
sys.stdout.reconfigure(encoding='utf-8')
from sqlalchemy import create_engine, text

engine = create_engine('sqlite:///data/stock_analyzer.db')
with engine.connect() as conn:
    # Check composite_scores columns
    cols = conn.execute(text("PRAGMA table_info(composite_scores)")).fetchall()
    print("composite_scores columns:")
    for c in cols:
        print(f"  {c[1]:30} {c[2]}")
    
    # Sample some rows
    rows = conn.execute(text("SELECT * FROM composite_scores LIMIT 3")).fetchall()
    if rows:
        print("\nSample rows:", rows[0])
    
    print()
    # Check technical_indicators columns
    cols2 = conn.execute(text("PRAGMA table_info(technical_indicators)")).fetchall()
    print("technical_indicators columns:")
    for c in cols2:
        print(f"  {c[1]:30} {c[2]}")
    
    # Check if daily_prices has 52W high
    sample = conn.execute(text("""
        SELECT dp.symbol, 
               dp.close as cur_price,
               MAX(dp2.high) as high_52w,
               MIN(dp2.low) as low_52w,
               dp.close / MAX(dp2.high) as proximity_52w
        FROM daily_prices dp
        JOIN daily_prices dp2 ON dp.symbol = dp2.symbol
        WHERE dp.date = (SELECT MAX(date) FROM daily_prices)
        AND dp2.date >= DATE(dp.date, '-365 days')
        AND dp2.date <= dp.date
        GROUP BY dp.symbol
        HAVING MAX(dp2.high) > 0
        LIMIT 10
    """)).fetchall()
    print("\n52W High proximity sample:")
    for r in sample:
        print(f"  {r[0]:15} cur={r[1]:.1f}  52wH={r[2]:.1f}  prox={r[4]*100:.1f}%")
