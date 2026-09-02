import sys
import io
from pathlib import Path

# Ensure UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from core.accuracy_tracker import evaluate_signal_audit_track_record

engine = get_global_engine()
session = get_session(engine)

for at in ['ALL', 'STOCK']:
    data = evaluate_signal_audit_track_record(session, asset_type=at)
    print(f"=== {at} TRACK RECORD METRICS ===")
    print(f"  Total Tracked:         {data['total_signals_tracked']}")
    print(f"  Resolved Outcomes:     {data['completed_signals']}")
    print(f"  Trade Intact Rate:     {data['active_intact_rate_pct']}%")
    print(f"  In-Play Profitable:    {data['in_play_profitable_pct']}% ({data['in_play_profitable_count']}/{data['active_signals']})")
    print(f"  🎯 Target 1+ Hit Rate: {data['target_1_hit_rate_pct']}% ({data['t1_hits_count']} wins)")
    print(f"  🛡️ Trailing SL Profit: {data['trailing_sl_hit_rate_pct']}% ({data['trailing_sl_hits_count']} protected wins)")
    print(f"  🛑 Stop Loss (Loss):   {data['stop_loss_hit_rate_pct']}% ({data['sl_loss_hits_count']} true losses)")
    print(f"  ⭐ Overall Win Rate:   {data['overall_win_rate_pct']}% ({data['profitable_count']} total profitable exits)")
    print(f"  Profit Factor:         {data['profit_factor']}x")
    print()

print("=== SL DEEP DIVE SUMMARY (TRUE LOSS STOPS ONLY) ===")
print(data['sl_deep_dive'])
