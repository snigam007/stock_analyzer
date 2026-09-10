import sqlite3

conn = sqlite3.connect('data/stock_analyzer.db')
cursor = conn.cursor()

print("=== CHECKING signals ===")
cursor.execute("""
    SELECT symbol, date, signal, current_price, buy_price, stop_loss, target_price_1
    FROM signals
    WHERE date = (SELECT MAX(date) FROM signals)
    LIMIT 10
""")
for row in cursor.fetchall():
    print(row)

print("\n=== CHECKING tracked_mandate_items ===")
cursor.execute("""
    SELECT id, symbol, entry_date, entry_price, peak_price, stop_loss, trailing_stop, current_status
    FROM tracked_mandate_items
    ORDER BY id DESC LIMIT 10
""")
for row in cursor.fetchall():
    print(row)
