import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from sqlalchemy import text

s = get_session(get_global_engine())

# Delete mock test records from sip_suggestion_log
del1 = s.execute(text("DELETE FROM sip_suggestion_log WHERE strategy = 'Compounder Multi-Asset Core'")).rowcount
del2 = s.execute(text("DELETE FROM sip_suggestion_log WHERE strategy = 'MULTI_ASSET' AND name IN ('Bharat Heavy', 'Samvardhana')")).rowcount
del3 = s.execute(text("DELETE FROM tracked_recommendation_mandates WHERE name LIKE 'Test%'")).rowcount
del4 = s.execute(text("DELETE FROM tracked_mandate_items WHERE mandate_id NOT IN (SELECT id FROM tracked_recommendation_mandates)")).rowcount

s.commit()
print(f"Deleted {del1} rows from sip_suggestion_log (Compounder Multi-Asset Core)")
print(f"Deleted {del2} rows from sip_suggestion_log (MULTI_ASSET mock)")
print(f"Deleted {del3} mock mandates")
print(f"Deleted {del4} orphaned mandate items")

# Check remaining rows in sip_suggestion_log
rows = s.execute(text("SELECT id, symbol, name, strategy, entry_price, status, days_held FROM sip_suggestion_log")).fetchall()
print(f"\nRemaining {len(rows)} legitimate tracking rows:")
for r in rows:
    print(r)
