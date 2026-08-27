import sys
import io
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from db.database import get_global_engine, get_session
from core.accuracy_tracker import evaluate_signal_audit_track_record

engine = get_global_engine()
session = get_session(engine)
audit = evaluate_signal_audit_track_record(session)

print("--- EMPIRICAL ACCURACY AUDIT TRACK RECORD ---")
print(f"Total Tracked: {audit['total_signals_tracked']}")
print(f"Completed Forward Evaluated: {audit['completed_signals']}")
print(f"Active / In Play: {audit['active_signals']}")
print(f"Overall Win Rate: {audit['overall_win_rate_pct']}%")
print(f"Target 1 Hit Rate: {audit['target_1_hit_rate_pct']}%")
print(f"Target 2 Hit Rate: {audit['target_2_hit_rate_pct']}%")
print(f"Target 3 Hit Rate: {audit['target_3_hit_rate_pct']}%")
print(f"Stop Loss Hit Rate: {audit['stop_loss_hit_rate_pct']}%")
print(f"Profit Factor: {audit['profit_factor']}x")
print(f"Avg Peak Gain (MFE): +{audit['avg_peak_gain_mfe']}%")
print(f"Avg Max Drawdown (MAE): {audit['avg_max_drawdown_mae']}%")

session.close()
