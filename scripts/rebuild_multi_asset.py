import sys
import io
from pathlib import Path

# Ensure UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from sqlalchemy import text
from core.accuracy_tracker import backfill_multi_asset_audit_history, evaluate_signal_audit_track_record

engine = get_global_engine()
session = get_session(engine)

# Clear corrupted index and commodity logs
session.execute(text("DELETE FROM signal_audit_log WHERE asset_type IN ('INDEX', 'COMMODITY')"))
session.commit()

# Run clean backfill
bf = backfill_multi_asset_audit_history(session)
print('Clean Backfill Result:', bf)

# Evaluate each
for at in ['STOCK', 'INDEX', 'COMMODITY', 'ALL']:
    res = evaluate_signal_audit_track_record(session, at)
    pf = res['profit_factor']
    wr = res['overall_win_rate_pct']
    comp = res['completed_signals']
    act = res['active_signals']
    t1 = res['t1_hits_count']
    tsl = res['trailing_sl_hits_count']
    sl = res['sl_loss_hits_count']
    print(f"{at:10}: Profit Factor = {pf:5.2f}x | Win Rate = {wr:5.1f}% | Completed = {comp:3} (Wins: {t1+tsl}, Losses: {sl}) | Active = {act:3}")
