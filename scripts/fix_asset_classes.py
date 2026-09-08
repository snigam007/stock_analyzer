import sys
sys.path.insert(0, ".")
from db.database import get_session
from sqlalchemy import text

s = get_session()
s.execute(text("UPDATE sip_suggestion_log SET asset_class = 'Mutual Fund' WHERE symbol LIKE 'MF_%'"))
s.execute(text("UPDATE sip_suggestion_log SET asset_class = 'Index / ETF' WHERE symbol LIKE '%BEES%' OR symbol LIKE '^%'"))
s.commit()
rows = s.execute(text("SELECT id, symbol, asset_class, strategy, entry_price, days_held FROM sip_suggestion_log")).fetchall()
print(f"Total rows: {len(rows)}")
for r in rows:
    print(r)
