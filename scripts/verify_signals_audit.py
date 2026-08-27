import sys
import io
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# UTF-8 stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from db.database import get_global_engine, get_session
from core.signals import compute_and_save_signals
from core.accuracy_tracker import evaluate_signal_audit_track_record

engine = get_global_engine()
session = get_session(engine)

print("Regenerating signals with quantitative guardrails & dynamic ATR...")
compute_and_save_signals(session)
print("New signals generated and saved.")

audit = evaluate_signal_audit_track_record(session)
print("\nUpdated Empirical Audit Track Record:")
print(f"• Total Tracked: {audit['total_signals_tracked']}")
print(f"• Forward Evaluated: {audit['completed_signals']}")
print(f"• Active / In Play: {audit['active_signals']}")
print(f"• Overall Win Rate: {audit['overall_win_rate_pct']}%")
print(f"• Target 1 Hit Rate: {audit['target_1_hit_rate_pct']}%")
print(f"• Stop Loss Hit Rate: {audit['stop_loss_hit_rate_pct']}%")
print(f"• Profit Factor: {audit['profit_factor']}")
print(f"• Avg Peak Gain (MFE): +{audit['avg_peak_gain_mfe']}%")
print(f"• Avg Max Drawdown (MAE): {audit['avg_max_drawdown_mae']}%")

session.close()
print("\nSUCCESS: Verification complete!")
