import sys
import io
from pathlib import Path

# Ensure UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from core.accuracy_tracker import backfill_multi_asset_audit_history, evaluate_signal_audit_track_record

engine = get_global_engine()
session = get_session(engine)

bf = backfill_multi_asset_audit_history(session)
print("Backfill result:", bf)

for at in ["ALL", "STOCK", "INDEX", "COMMODITY", "BREAKOUT"]:
    stats = evaluate_signal_audit_track_record(session, asset_type=at)
    print(f"\n=== Asset Type: {at} ===")
    print(f"  Total Tracked: {stats['total_signals_tracked']}")
    print(f"  Completed: {stats['completed_signals']}, Active: {stats['active_signals']}")
    print(f"  In-Play Profitable: {stats['in_play_profitable_count']} ({stats['in_play_profitable_pct']}%)")
    print(f"  T1 Hit Rate: {stats['target_1_hit_rate_pct']}%, SL Hit Rate: {stats['stop_loss_hit_rate_pct']}%")
    print(f"  Profit Factor: {stats['profit_factor']}x")
    if stats['records']:
        for s in stats['records'][:3]:
            print(f"  • {s['symbol']} ({s['asset_type']}) [{s['date']}] | Status: {s['status']} | Live/Realized P&L: {s['realized_gain_pct']}% | Days: {s['days_to_outcome']}")

print("\nMulti-asset audit test succeeded!")
