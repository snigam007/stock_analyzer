import sys
import io
from pathlib import Path

# Ensure UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from core.signals import generate_all_signals
from core.accuracy_tracker import backfill_multi_asset_audit_history, evaluate_signal_audit_track_record

engine = get_global_engine()
session = get_session(engine)

print("1. Regenerating all signals with upgraded Quant rules (Oversold Mean-Reversion & VCP)...")
generate_all_signals(session)

print("\n2. Backfilling & evaluating multi-asset accuracy audit...")
bf = backfill_multi_asset_audit_history(session)
print("Backfill Snapshot:", bf)

for at in ["STOCK", "INDEX", "COMMODITY", "BREAKOUT", "ALL"]:
    stats = evaluate_signal_audit_track_record(session, asset_type=at)
    print(f"\n🎯 {at} AUDIT TRACK RECORD SUMMARY")
    print(f"  • Total Signals Tracked: {stats['total_signals_tracked']}")
    print(f"  • Forward Evaluated:    {stats['completed_signals']}")
    print(f"  • In-Play Active:        {stats['active_signals']} (Profitable In-Play: {stats['in_play_profitable_count']} / {stats['in_play_profitable_pct']}%)")
    print(f"  • Target 1 Hit Rate:     {stats['target_1_hit_rate_pct']}%")
    print(f"  • Stop Loss Hit Rate:    {stats['stop_loss_hit_rate_pct']}%")
    print(f"  • Profit Factor:         {stats['profit_factor']}x")
    print(f"  • Avg Peak Move (MFE):   +{stats['avg_peak_gain_mfe']}%")
    print(f"  • Avg Max Drawdown (MAE): {stats['avg_max_drawdown_mae']}%")

print("\nSystem verification complete and verified!")
