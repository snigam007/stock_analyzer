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

engine = get_global_engine()
session = get_session(engine)

def recalibrate_asset(asset_type, t1_pct, t2_pct, t3_pct, sl_pct):
    tbl = 'index_prices' if asset_type == 'INDEX' else 'commodity_prices'
    rows = session.execute(text('''
        SELECT id, signal_date, symbol, signal, entry_price
        FROM signal_audit_log
        WHERE asset_type = :at
    '''), {'at': asset_type}).fetchall()
    
    print(f'Recalibrating {len(rows)} {asset_type} signals...')
    for r in rows:
        row_id, s_date, sym, sig, entry = r
        if not entry or entry <= 0: continue
        
        if sig == 'BUY':
            t1 = entry * (1.0 + t1_pct / 100.0)
            t2 = entry * (1.0 + t2_pct / 100.0)
            t3 = entry * (1.0 + t3_pct / 100.0)
            sl = entry * (1.0 - sl_pct / 100.0)
        else:
            t1 = entry * (1.0 - t1_pct / 100.0)
            t2 = entry * (1.0 - t2_pct / 100.0)
            t3 = entry * (1.0 - t3_pct / 100.0)
            sl = entry * (1.0 + sl_pct / 100.0)
            
        fwd = session.execute(text(f'''
            SELECT date, high, low, close FROM {tbl}
            WHERE symbol=:s AND date > :d ORDER BY date ASC LIMIT 90
        '''), {'s': sym, 'd': s_date}).fetchall()
        
        if not fwd:
            session.execute(text('''
                UPDATE signal_audit_log
                SET target_1=:t1, target_2=:t2, target_3=:t3, stop_loss=:sl, trailing_stop=:sl,
                    status='PENDING', unrealized_gain_pct=0.0
                WHERE id=:id
            '''), {'t1': round(t1, 2), 't2': round(t2, 2), 't3': round(t3, 2), 'sl': round(sl, 2), 'id': row_id})
            continue
            
        hit_t1 = hit_t2 = hit_t3 = hit_sl = hit_ts_win = False
        effective_sl = sl
        max_h = float(entry)
        min_l = float(entry)
        realized_gain = None
        exit_date = None
        days = len(fwd)
        
        for d_idx, bar in enumerate(fwd):
            b_date, h, l, c = str(bar[0]), float(bar[1]), float(bar[2]), float(bar[3])
            max_h = max(max_h, h)
            min_l = min(min_l, l)
            
            if sig == 'BUY':
                if (c <= effective_sl) or (l <= effective_sl * 0.99):
                    hit_sl = True
                    exit_date = b_date
                    days = d_idx + 1
                    realized_gain = round((effective_sl - entry) / entry * 100.0, 2)
                    if effective_sl > entry: hit_ts_win = True
                    break
                if t3 and h >= t3:
                    hit_t3 = True
                    effective_sl = max(effective_sl, t2 * 0.995)
                elif t2 and h >= t2:
                    hit_t2 = True
                    effective_sl = max(effective_sl, t1 * 0.995)
                elif t1 and h >= t1:
                    hit_t1 = True
                    effective_sl = max(effective_sl, entry * 1.005)
                elif (max_h - entry) / entry >= (t1_pct * 0.007):
                    effective_sl = max(effective_sl, entry * 1.002)
            else:
                if (c >= effective_sl) or (h >= effective_sl * 1.01):
                    hit_sl = True
                    exit_date = b_date
                    days = d_idx + 1
                    realized_gain = round((entry - effective_sl) / entry * 100.0, 2)
                    if effective_sl < entry: hit_ts_win = True
                    break
                if t3 and l <= t3:
                    hit_t3 = True
                    effective_sl = min(effective_sl, t2 * 1.005)
                elif t2 and l <= t2:
                    hit_t2 = True
                    effective_sl = min(effective_sl, t1 * 1.005)
                elif t1 and l <= t1:
                    hit_t1 = True
                    effective_sl = min(effective_sl, entry * 0.995)
                elif (entry - min_l) / entry >= (t1_pct * 0.007):
                    effective_sl = min(effective_sl, entry * 0.998)
                    
        if hit_t3:
            st = 'T3_HIT'
            gain = round(t3_pct, 2)
        elif hit_t2:
            st = 'T2_HIT'
            gain = round(t2_pct, 2)
        elif hit_t1:
            st = 'T1_HIT'
            gain = round(t1_pct, 2)
        elif hit_ts_win:
            st = 'TRAILING_SL_HIT'
            gain = realized_gain
        elif hit_sl:
            st = 'SL_HIT'
            gain = realized_gain
        else:
            st = 'PENDING'
            last_c = float(fwd[-1][3])
            gain = round((last_c - entry) / entry * 100.0, 2) if sig == 'BUY' else round((entry - last_c) / entry * 100.0, 2)
            
        session.execute(text('''
            UPDATE signal_audit_log
            SET target_1=:t1, target_2=:t2, target_3=:t3, stop_loss=:sl, trailing_stop=:ts,
                status=:st, realized_gain_pct=:gain, exit_date=:ed, days_to_outcome=:days,
                max_price_reached=:mx, min_price_reached=:mn, unrealized_gain_pct=:gain
            WHERE id=:id
        '''), {
            't1': round(t1, 2), 't2': round(t2, 2), 't3': round(t3, 2), 'sl': round(sl, 2),
            'ts': round(effective_sl, 2), 'st': st, 'gain': gain, 'ed': exit_date, 'days': days,
            'mx': round(max_h, 2), 'mn': round(min_l, 2), 'id': row_id
        })
    session.commit()

# Index parameters: Target 1: 2.0%, Target 2: 3.8%, Target 3: 6.0%, SL: 1.5% (R:R 1.33)
recalibrate_asset('INDEX', t1_pct=2.0, t2_pct=3.8, t3_pct=6.0, sl_pct=1.5)

# Commodity parameters: Target 1: 3.2%, Target 2: 5.8%, Target 3: 8.5%, SL: 2.2% (R:R 1.45)
recalibrate_asset('COMMODITY', t1_pct=3.2, t2_pct=5.8, t3_pct=8.5, sl_pct=2.2)

from core.accuracy_tracker import evaluate_signal_audit_track_record
idx_res = evaluate_signal_audit_track_record(session, 'INDEX')
cmd_res = evaluate_signal_audit_track_record(session, 'COMMODITY')
all_res = evaluate_signal_audit_track_record(session, 'ALL')

print("INDEX:", idx_res["profit_factor"], "x | Win Rate:", idx_res["overall_win_rate_pct"], "% | Completed:", idx_res["completed_signals"])
print("COMMODITY:", cmd_res["profit_factor"], "x | Win Rate:", cmd_res["overall_win_rate_pct"], "% | Completed:", cmd_res["completed_signals"])
print("GLOBAL ALL:", all_res["profit_factor"], "x | Win Rate:", all_res["overall_win_rate_pct"], "% | Completed:", all_res["completed_signals"])
