import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from sqlalchemy import text

s = get_session(get_global_engine())
tables = [t[0] for t in s.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()]
print("Matching tables:", [t for t in tables if any(k in t.lower() for k in ['sip', 'track', 'mandate', 'log'])])

tname = 'sip_suggestion_log'
print(f"\n--- Table: {tname} ---")
cols = [c[1] for c in s.execute(text(f"PRAGMA table_info({tname})")).fetchall()]
print("Columns:", cols)
rows = s.execute(text(f"SELECT * FROM {tname}")).fetchall()
for r in rows:
    print(r)
