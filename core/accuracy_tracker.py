"""
Empirical Signal Accuracy & Audit Track Record Tracker
- Persistently evaluates historical BUY/SELL signals against forward price evolution
- Quantifies actual empirical hit rates for Target 1 (+4%), Target 2 (+8%), Target 3 (+15%), and Stop-Loss triggers
"""
import logging
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


def init_audit_table(session: Session):
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS signal_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            signal TEXT NOT NULL,
            entry_price REAL NOT NULL,
            target_1 REAL,
            target_2 REAL,
            target_3 REAL,
            stop_loss REAL,
            composite_score REAL,
            status TEXT DEFAULT 'PENDING',
            max_price_reached REAL,
            min_price_reached REAL,
            exit_date TEXT,
            days_to_target INTEGER,
            realized_gain_pct REAL,
            verified_date TEXT,
            UNIQUE(signal_date, symbol)
        )
    """))
    session.commit()


def log_current_signals_to_audit(session: Session) -> int:
    init_audit_table(session)
    query = """
        SELECT sig.date, sig.symbol, sig.signal, sig.current_price,
               sig.target_price_1, sig.target_price_2, sig.target_price_3,
               sig.stop_loss, cs.composite_score
        FROM signals sig
        LEFT JOIN composite_scores cs ON sig.symbol = cs.symbol AND sig.date = cs.date
        WHERE sig.date = (SELECT MAX(date) FROM signals)
        AND sig.signal IN ('BUY', 'SELL')
    """
    rows = session.execute(text(query)).fetchall()
    logged = 0
    for r in rows:
        try:
            session.execute(text("""
                INSERT OR IGNORE INTO signal_audit_log (
                    signal_date, symbol, signal, entry_price,
                    target_1, target_2, target_3, stop_loss,
                    composite_score, status
                ) VALUES (
                    :dt, :sym, :sig, :price,
                    :t1, :t2, :t3, :sl,
                    :score, 'PENDING'
                )
            """), {
                'dt': str(r[0]), 'sym': str(r[1]), 'sig': str(r[2]), 'price': float(r[3]),
                't1': float(r[4]) if r[4] else None, 't2': float(r[5]) if r[5] else None,
                't3': float(r[6]) if r[6] else None, 'sl': float(r[7]) if r[7] else None,
                'score': float(r[8]) if r[8] else None,
            })
            logged += 1
        except Exception:
            pass
    session.commit()
    return logged


def evaluate_signal_audit_track_record(session: Session) -> dict:
    init_audit_table(session)
    log_current_signals_to_audit(session)
    signals_rows = session.execute(text("""
        SELECT id, signal_date, symbol, signal, entry_price,
               target_1, target_2, target_3, stop_loss
        FROM signal_audit_log
        ORDER BY signal_date DESC
    """)).fetchall()

    if not signals_rows:
        return {
            'total_signals_tracked': 0, 'completed_signals': 0, 'active_signals': 0,
            'target_1_hit_rate_pct': 0.0, 'target_2_hit_rate_pct': 0.0,
            'target_3_hit_rate_pct': 0.0, 'stop_loss_hit_rate_pct': 0.0,
            'overall_win_rate_pct': 0.0, 'profit_factor': 1.0,
            'avg_peak_gain_mfe': 0.0, 'avg_max_drawdown_mae': 0.0,
            'records': []
        }

    evaluated_records = []
    t1_hits, t2_hits, t3_hits, sl_hits, active_in_play = 0, 0, 0, 0, 0
    profitable_count = 0
    all_gains = []
    all_losses = []
    fwd_evaluated_count = 0

    for row in signals_rows:
        sig_id, s_date, sym, sig_type, entry, t1, t2, t3, sl = row
        fwd_prices = session.execute(text("""
            SELECT date, high, low, close
            FROM daily_prices
            WHERE symbol = :s AND date >= :d
            ORDER BY date ASC
            LIMIT 90
        """), {'s': sym, 'd': s_date}).fetchall()

        if len(fwd_prices) <= 1:
            active_in_play += 1
            evaluated_records.append({
                'date': s_date, 'symbol': sym, 'signal': sig_type,
                'entry_price': round(entry, 2), 'target_1': round(t1, 2) if t1 else None,
                'target_2': round(t2, 2) if t2 else None, 'target_3': round(t3, 2) if t3 else None,
                'stop_loss': round(sl, 2) if sl else None, 'status': '⏳ IN PLAY (Latest Session)',
                'days_elapsed': 0, 'max_gain_pct': 0.0, 'max_loss_pct': 0.0, 'current_gain_pct': 0.0,
            })
            continue

        fwd_evaluated_count += 1
        hit_t1, hit_t2, hit_t3, hit_sl = False, False, False, False
        max_high = entry
        min_low = entry

        for day_idx, p in enumerate(fwd_prices[1:], start=1):
            h, l, c = float(p[1]), float(p[2]), float(p[3])
            max_high = max(max_high, h)
            min_low = min(min_low, l)
            if sig_type == 'BUY':
                if sl and l <= sl and not hit_t1:
                    hit_sl = True
                    break
                if t1 and h >= t1: hit_t1 = True
                if t2 and h >= t2: hit_t2 = True
                if t3 and h >= t3: hit_t3 = True
            elif sig_type == 'SELL':
                if sl and h >= sl and not hit_t1:
                    hit_sl = True
                    break
                if t1 and l <= t1: hit_t1 = True
                if t2 and l <= t2: hit_t2 = True
                if t3 and l <= t3: hit_t3 = True

        latest_close = float(fwd_prices[-1][3])
        if sig_type == 'BUY':
            max_gain_pct = (max_high - entry) / entry * 100.0
            max_loss_pct = (min_low - entry) / entry * 100.0
            curr_return_pct = (latest_close - entry) / entry * 100.0
        else:
            max_gain_pct = (entry - min_low) / entry * 100.0
            max_loss_pct = (entry - max_high) / entry * 100.0
            curr_return_pct = (entry - latest_close) / entry * 100.0

        all_gains.append(max(0.0, max_gain_pct))
        all_losses.append(min(0.0, max_loss_pct))

        if hit_t3:
            status_str = '🎯🎯🎯 T3 HIT (+15%+)'
            t3_hits += 1; t2_hits += 1; t1_hits += 1; profitable_count += 1
        elif hit_t2:
            status_str = '🎯🎯 T2 HIT (+8%+)'
            t2_hits += 1; t1_hits += 1; profitable_count += 1
        elif hit_t1:
            status_str = '🎯 T1 HIT (+4%+)'
            t1_hits += 1; profitable_count += 1
        elif hit_sl:
            status_str = '🛑 STOP LOSS HIT'
            sl_hits += 1
        elif curr_return_pct > 0:
            status_str = '🟢 IN PLAY (PROFITABLE)'
            profitable_count += 1
            active_in_play += 1
        else:
            status_str = '🟡 IN PLAY (DRAWDOWNS)'
            active_in_play += 1

        evaluated_records.append({
            'date': s_date, 'symbol': sym, 'signal': sig_type,
            'entry_price': round(entry, 2),
            'target_1': round(t1, 2) if t1 else None,
            'target_2': round(t2, 2) if t2 else None,
            'target_3': round(t3, 2) if t3 else None,
            'stop_loss': round(sl, 2) if sl else None,
            'status': status_str,
            'days_elapsed': len(fwd_prices) - 1,
            'max_gain_pct': round(max_gain_pct, 2),
            'max_loss_pct': round(max_loss_pct, 2),
            'current_gain_pct': round(curr_return_pct, 2),
        })

    denom = max(1, fwd_evaluated_count)
    t1_rate = round((t1_hits / denom) * 100, 1)
    t2_rate = round((t2_hits / denom) * 100, 1)
    t3_rate = round((t3_hits / denom) * 100, 1)
    sl_rate = round((sl_hits / denom) * 100, 1)
    overall_win_rate = round((profitable_count / denom) * 100, 1)
    intact_rate = round(max(0.0, (1.0 - (sl_hits / denom))) * 100, 1)

    avg_mfe = round(float(np.mean(all_gains)), 2) if all_gains else 0.0
    avg_mae = round(float(np.mean(all_losses)), 2) if all_losses else 0.0
    sum_gains = sum(all_gains) if all_gains else 1.0
    sum_losses = abs(sum(all_losses)) if all_losses and abs(sum(all_losses)) > 0.001 else 1.0
    profit_factor = round(sum_gains / sum_losses, 2)

    return {
        'total_signals_tracked': len(signals_rows),
        'completed_signals': fwd_evaluated_count,
        'active_signals': active_in_play,
        't1_hits_count': t1_hits,
        't2_hits_count': t2_hits,
        't3_hits_count': t3_hits,
        'sl_hits_count': sl_hits,
        'profitable_count': profitable_count,
        'target_1_hit_rate_pct': t1_rate,
        'target_2_hit_rate_pct': t2_rate,
        'target_3_hit_rate_pct': t3_rate,
        'stop_loss_hit_rate_pct': sl_rate,
        'active_intact_rate_pct': intact_rate,
        'in_play_profitable_pct': overall_win_rate,
        'overall_win_rate_pct': overall_win_rate,
        'profit_factor': profit_factor,
        'avg_peak_gain_mfe': avg_mfe,
        'avg_max_drawdown_mae': avg_mae,
        'records': evaluated_records,
    }