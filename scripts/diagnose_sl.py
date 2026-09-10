import sys
import os
sys.path.insert(0, os.path.abspath('.'))

import sqlite3

conn = sqlite3.connect('data/stock_analyzer.db')
c = conn.cursor()

c.execute("""
    SELECT symbol, date, signal, current_price, stop_loss, target_price_1, stop_loss_downside_pct 
    FROM signals 
    WHERE symbol IN ('IOB', 'ICICIBANK', 'INDUSINDBK', 'SBIN', 'PCBL') AND date = '2026-09-10'
""")
print("=== SIGNALS on 2026-09-10 ===")
for r in c.fetchall():
    print(r)

c.execute("""
    SELECT id, signal_date, symbol, signal, entry_price, stop_loss, trailing_stop, status, unrealized_gain_pct
    FROM signal_audit_log
    WHERE symbol IN ('IOB', 'ICICIBANK', 'INDUSINDBK', 'SBIN', 'PCBL') AND signal_date = '2026-09-10'
""")
print("\n=== SIGNAL_AUDIT_LOG on 2026-09-10 ===")
for r in c.fetchall():
    print(r)

c.execute("""
    SELECT s.market_cap_tier, t.close, t.atr_14, t.adx
    FROM stocks s
    JOIN technical_indicators t ON s.id = t.stock_id
    WHERE s.symbol = 'IOB'
    ORDER BY t.date DESC LIMIT 1
""")
print("\n=== IOB TECH INDICATORS ===")
print(c.fetchall())
