import sys
import os
sys.path.insert(0, os.path.abspath('.'))

import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from db.database import get_session
from core.accuracy_tracker import evaluate_signal_audit_track_record

with get_session() as session:
    res = evaluate_signal_audit_track_record(session, asset_type='ALL')
    records = res.get('records', [])
    print(f'Total records: {len(records)}')
    
    same_cp_ts = []
    same_ep_ts = []
    status_counts = {}
    for r in records:
        cp = r.get('close_price')
        ts = r.get('trailing_stop')
        ep = r.get('entry_price')
        sl = r.get('stop_loss')
        stat = r.get('status')
        raw_stat = r.get('raw_status')
        if cp is not None and ts is not None and abs(cp - ts) < 0.05:
            same_cp_ts.append(r)
            status_counts[raw_stat] = status_counts.get(raw_stat, 0) + 1
        if ep is not None and ts is not None and abs(ep - ts) < 0.05:
            same_ep_ts.append(r)
            
    print(f'Records where close_price (Current/Exit) == trailing_stop (Trailing SL): {len(same_cp_ts)}')
    print('Breakdown by raw_status:', status_counts)
    print('\nSamples:')
    for r in same_cp_ts[:20]:
        print(f"  {r['date']} {r['symbol']} ({r['signal']}): Entry={r['entry_price']}, Current/Exit={r['close_price']}, InitialSL={r['stop_loss']}, TrailingSL={r['trailing_stop']}, Status={r['raw_status']}")
