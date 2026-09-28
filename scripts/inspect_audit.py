import sqlite3

conn = sqlite3.connect('data/stock_analyzer.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cursor.fetchall()]
print("Tables:", tables)

for t in tables:
    if any(k in t for k in ['audit', 'track', 'signal', 'trade', 'performance', 'learning']):
        cnt = cursor.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"Table {t}: {cnt} rows")

print("\n--- SCHEMA OF signal_audit / signals ---")
for t in ['signal_audit', 'signals', 'signal_track_record']:
    if t in tables:
        cursor.execute(f"PRAGMA table_info({t})")
        cols = cursor.fetchall()
        print(f"{t} columns: {[c[1] for c in cols]}")
        cursor.execute(f"SELECT MIN(date), MAX(date) FROM {t}")
        print(f"{t} date range: {cursor.fetchone()}")
