import sqlite3

conn = sqlite3.connect('data/stock_analyzer.db')
c = conn.cursor()

c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%archive%'")
print('Archive tables:', c.fetchall())

try:
    c.execute('SELECT COUNT(*) FROM signal_audit_log_legacy_archive')
    print('Legacy archive rows:', c.fetchone()[0])
except Exception as e:
    print('Archive check error:', e)

c.execute('SELECT COUNT(*) FROM signal_audit_log')
print('Current signal_audit_log rows:', c.fetchone()[0])

conn.close()
