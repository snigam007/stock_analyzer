import sys
import os
sys.path.insert(0, os.path.abspath('.'))

import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import sqlite3
from db.database import get_session
from core.accuracy_tracker import evaluate_signal_audit_track_record

with get_session() as session:
    res = evaluate_signal_audit_track_record(session, asset_type='ALL')
    records = res.get('records', [])

    print("=== SAMPLE PENDING RECORDS ===")
    pending_recs = [r for r in records if r.get('raw_status') == 'PENDING']
    print(f"Total pending: {len(pending_recs)}")
    for r in pending_recs[:15]:
        print(f"  {r['date']} {r['symbol']}: Entry={r['entry_price']}, Current={r['close_price']}, SL={r['stop_loss']}, TrailingSL={r['trailing_stop']}, Unrlzd={r['unrealized_gain_pct']}%")

    print("\n=== SAMPLE TRAILING_SL_HIT RECORDS ===")
    tsl_recs = [r for r in records if r.get('raw_status') == 'TRAILING_SL_HIT']
    print(f"Total TRAILING_SL_HIT: {len(tsl_recs)}")
    for r in tsl_recs[:15]:
        print(f"  {r['date']} {r['symbol']}: Entry={r['entry_price']}, Exit/Close={r['close_price']}, SL={r['stop_loss']}, TrailingSL={r['trailing_stop']}, PnL={r['realized_gain_pct']}%")
