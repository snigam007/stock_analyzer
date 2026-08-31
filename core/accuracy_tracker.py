"""
Empirical Signal Accuracy & Audit Track Record Tracker
- Persistently evaluates historical BUY/SELL signals against forward price evolution
- Writes back actual hit/miss status, exit dates, and realized gains to signal_audit_log
- Implements trailing stop logic: T1 hit -> trail to breakeven, T2 hit -> trail to T1 level
- Quantifies empirical hit rates: Target 1 (~3.5%), Target 2 (~7.5%), Target 3 (~14%), Stop-Loss
"""
import logging
from datetime import date, timedelta
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# --- Audit Table Schema -------------------------------------------------------
_CREATE_AUDIT_TABLE = """
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
        days_to_outcome INTEGER,
        realized_gain_pct REAL,
        trailing_stop REAL,
        verified_date TEXT,
        UNIQUE(signal_date, symbol)
    )
"""


def init_audit_table(session: Session):
    """Create audit table and add any missing columns (migration-safe)."""
    session.execute(text(_CREATE_AUDIT_TABLE))
    for col_def in ["trailing_stop REAL", "days_to_outcome INTEGER"]:
        try:
            session.execute(text(f"ALTER TABLE signal_audit_log ADD COLUMN {col_def}"))
        except Exception:
            pass  # Column already exists
    session.commit()


# --- Log Today Signals --------------------------------------------------------
def log_current_signals_to_audit(session: Session) -> int:
    """Snapshot today BUY/SELL signals into the audit log (INSERT OR IGNORE)."""
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
                    composite_score, status, trailing_stop
                ) VALUES (:dt, :sym, :sig, :price, :t1, :t2, :t3, :sl, :score, 'PENDING', :sl)
            """), {
                'dt': str(r[0]), 'sym': str(r[1]), 'sig': str(r[2]), 'price': float(r[3]),
                't1': float(r[4]) if r[4] else None,
                't2': float(r[5]) if r[5] else None,
                't3': float(r[6]) if r[6] else None,
                'sl': float(r[7]) if r[7] else None,
                'score': float(r[8]) if r[8] else None,
            })
            logged += 1
        except Exception:
            pass
    session.commit()
    return logged


# --- Update Trailing Stops ----------------------------------------------------
def update_trailing_stops(session: Session) -> int:
    """
    Move stops as price hits targets (written back to DB):
      BUY:  price >= T1 -> trail to breakeven+0.2%; >= T2 -> trail to T1; >= T3 -> trail to T2
      SELL: inverse logic
    """
    init_audit_table(session)
    pending = session.execute(text("""
        SELECT id, symbol, signal, entry_price, target_1, target_2, target_3, stop_loss, trailing_stop
        FROM signal_audit_log WHERE status = 'PENDING'
    """)).fetchall()

    updated = 0
    for row in pending:
        row_id, sym, sig, entry, t1, t2, t3, orig_sl, trailing_sl = row
        if trailing_sl is None:
            trailing_sl = orig_sl

        latest = session.execute(text(
            "SELECT high, low, close FROM daily_prices WHERE symbol=:s ORDER BY date DESC LIMIT 1"
        ), {'s': sym}).first()
        if not latest:
            continue

        h, l, c = float(latest[0] or 0), float(latest[1] or 0), float(latest[2] or 0)
        new_trailing = trailing_sl

        if sig == 'BUY' and t1 and t2:
            if t3 and h >= float(t3) and t2:
                new_trailing = max(trailing_sl or orig_sl, float(t2) * 0.995)
            elif h >= float(t2) and t1:
                new_trailing = max(trailing_sl or orig_sl, float(t1) * 0.995)
            elif h >= float(t1):
                new_trailing = max(trailing_sl or orig_sl, entry * 1.002)
        elif sig == 'SELL' and t1 and t2:
            if t3 and l <= float(t3) and t2:
                new_trailing = min(trailing_sl or orig_sl, float(t2) * 1.005)
            elif l <= float(t2) and t1:
                new_trailing = min(trailing_sl or orig_sl, float(t1) * 1.005)
            elif l <= float(t1):
                new_trailing = min(trailing_sl or orig_sl, entry * 0.998)

        if new_trailing != trailing_sl:
            session.execute(text(
                "UPDATE signal_audit_log SET trailing_stop = :ts WHERE id = :id"
            ), {'ts': round(new_trailing, 2), 'id': row_id})
            updated += 1

    session.commit()
    return updated


# --- Evaluate and Persist Outcomes --------------------------------------------
def evaluate_signal_audit_track_record(session: Session) -> dict:
    """
    Evaluate all PENDING signals against actual forward prices and
    WRITE BACK outcomes to signal_audit_log. Returns summary stats dict.
    """
    init_audit_table(session)
    update_trailing_stops(session)

    pending_rows = session.execute(text("""
        SELECT id, signal_date, symbol, signal, entry_price,
               target_1, target_2, target_3, stop_loss, trailing_stop, composite_score
        FROM signal_audit_log
        WHERE status = 'PENDING'
        ORDER BY signal_date ASC
    """)).fetchall()

    today_str = str(date.today())

    for row in pending_rows:
        row_id, s_date, sym, sig_type, entry, t1, t2, t3, sl, trailing_sl, score = row
        effective_sl = trailing_sl if trailing_sl is not None else sl

        fwd_prices = session.execute(text("""
            SELECT date, high, low, close FROM daily_prices
            WHERE symbol = :s AND date > :d ORDER BY date ASC LIMIT 90
        """), {'s': sym, 'd': s_date}).fetchall()

        if not fwd_prices:
            continue

        hit_t1 = hit_t2 = hit_t3 = hit_sl = False
        exit_date = None
        days_to_outcome = len(fwd_prices)
        max_high = float(entry)
        min_low = float(entry)
        realized_gain_pct = None

        for day_idx, p in enumerate(fwd_prices):
            p_date, h, l, c = str(p[0]), float(p[1]), float(p[2]), float(p[3])
            max_high = max(max_high, h)
            min_low = min(min_low, l)

            if sig_type == 'BUY':
                if effective_sl and l <= float(effective_sl) and not hit_t1:
                    hit_sl = True
                    exit_date = p_date
                    days_to_outcome = day_idx + 1
                    realized_gain_pct = round((float(effective_sl) - entry) / entry * 100.0, 2)
                    break
                if t1 and h >= float(t1):
                    hit_t1 = True
                    be = entry * 1.002
                    if not effective_sl or effective_sl < be:
                        effective_sl = be
                if t2 and h >= float(t2):
                    hit_t2 = True
                    if t1 and (not effective_sl or float(effective_sl) < float(t1) * 0.995):
                        effective_sl = float(t1) * 0.995
                if t3 and h >= float(t3):
                    hit_t3 = True
                    if t2 and (not effective_sl or float(effective_sl) < float(t2) * 0.995):
                        effective_sl = float(t2) * 0.995
            elif sig_type == 'SELL':
                if effective_sl and h >= float(effective_sl) and not hit_t1:
                    hit_sl = True
                    exit_date = p_date
                    days_to_outcome = day_idx + 1
                    realized_gain_pct = round((entry - float(effective_sl)) / entry * 100.0, 2)
                    break
                if t1 and l <= float(t1):
                    hit_t1 = True
                    be = entry * 0.998
                    if not effective_sl or effective_sl > be:
                        effective_sl = be
                if t2 and l <= float(t2):
                    hit_t2 = True
                if t3 and l <= float(t3):
                    hit_t3 = True

        latest_close = float(fwd_prices[-1][3]) if fwd_prices else entry
        if sig_type == 'BUY':
            max_gain_pct = (max_high - entry) / entry * 100.0
            curr_pct = (latest_close - entry) / entry * 100.0
        else:
            max_gain_pct = (entry - min_low) / entry * 100.0
            curr_pct = (entry - latest_close) / entry * 100.0

        if hit_sl:
            final_status = 'SL_HIT'
            if realized_gain_pct is None:
                realized_gain_pct = round(curr_pct, 2)
        elif hit_t3:
            final_status = 'T3_HIT'
            exit_date = exit_date or str(fwd_prices[-1][0])
            realized_gain_pct = realized_gain_pct or round(max_gain_pct, 2)
        elif hit_t2:
            final_status = 'T2_HIT'
            exit_date = exit_date or str(fwd_prices[-1][0])
            realized_gain_pct = realized_gain_pct or round(max_gain_pct, 2)
        elif hit_t1:
            final_status = 'T1_HIT'
            exit_date = exit_date or str(fwd_prices[-1][0])
            realized_gain_pct = realized_gain_pct or round(max_gain_pct, 2)
        elif len(fwd_prices) >= 60:
            final_status = 'EXPIRED'
            exit_date = str(fwd_prices[-1][0])
            realized_gain_pct = round(curr_pct, 2)
        else:
            # Still active -- update progress only, keep PENDING
            session.execute(text("""
                UPDATE signal_audit_log
                SET max_price_reached=:mx, min_price_reached=:mn,
                    trailing_stop=:ts, verified_date=:vd
                WHERE id=:id
            """), {
                'mx': round(max_high, 2), 'mn': round(min_low, 2),
                'ts': round(effective_sl, 2) if effective_sl else None,
                'vd': today_str, 'id': row_id,
            })
            continue

        # Write final outcome to DB
        session.execute(text("""
            UPDATE signal_audit_log
            SET status=:st, max_price_reached=:mx, min_price_reached=:mn,
                exit_date=:ed, days_to_outcome=:days, realized_gain_pct=:gain,
                trailing_stop=:ts, verified_date=:vd
            WHERE id=:id
        """), {
            'st': final_status, 'mx': round(max_high, 2), 'mn': round(min_low, 2),
            'ed': exit_date, 'days': days_to_outcome, 'gain': realized_gain_pct,
            'ts': round(effective_sl, 2) if effective_sl else None,
            'vd': today_str, 'id': row_id,
        })

    session.commit()
    return _compute_summary_stats(session)


# --- Summary Statistics -------------------------------------------------------
def _compute_summary_stats(session: Session) -> dict:
    """Compute hit rate and profitability stats from the persisted audit log."""
    all_rows = session.execute(text("""
        SELECT signal_date, symbol, signal, entry_price, target_1, target_2, target_3,
               stop_loss, composite_score, status, max_price_reached, min_price_reached,
               exit_date, days_to_outcome, realized_gain_pct, trailing_stop
        FROM signal_audit_log ORDER BY signal_date DESC
    """)).fetchall()

    if not all_rows:
        return {
            'total_signals_tracked': 0, 'completed_signals': 0, 'pending_signals': 0,
            'target_1_hit_rate_pct': 0.0, 'target_2_hit_rate_pct': 0.0,
            'target_3_hit_rate_pct': 0.0, 'stop_loss_hit_rate_pct': 0.0,
            'overall_win_rate_pct': 0.0, 'profit_factor': 1.0,
            'avg_peak_gain_mfe': 0.0, 'avg_max_drawdown_mae': 0.0,
            'avg_days_to_outcome': 0.0, 'records': []
        }

    resolved = [r for r in all_rows if r[9] != 'PENDING']
    pending = [r for r in all_rows if r[9] == 'PENDING']
    n = len(resolved)

    t1_hits = sum(1 for r in resolved if r[9] in ('T1_HIT', 'T2_HIT', 'T3_HIT'))
    t2_hits = sum(1 for r in resolved if r[9] in ('T2_HIT', 'T3_HIT'))
    t3_hits = sum(1 for r in resolved if r[9] == 'T3_HIT')
    sl_hits = sum(1 for r in resolved if r[9] == 'SL_HIT')
    expired_profit = sum(1 for r in resolved if r[9] == 'EXPIRED' and (r[14] or 0) > 0)
    profitable = t1_hits + expired_profit

    gains = [r[14] for r in resolved if r[14] is not None and r[14] > 0]
    losses = [abs(r[14]) for r in resolved if r[14] is not None and r[14] < 0]
    days_list = [r[13] for r in resolved if r[13] is not None and r[13] > 0]

    mfe_list, mae_list = [], []
    for r in resolved:
        entry, sig, mx, mn = r[3], r[2], r[10], r[11]
        if entry and entry > 0:
            if sig == 'BUY':
                if mx: mfe_list.append((mx - entry) / entry * 100)
                if mn: mae_list.append((entry - mn) / entry * 100)
            else:
                if mn: mfe_list.append((entry - mn) / entry * 100)
                if mx: mae_list.append((mx - entry) / entry * 100)

    score_breakdown = {}
    for r in resolved:
        cs = r[8]
        if cs is None:       bucket = "N/A"
        elif cs >= 70:       bucket = "STRONG (70+)"
        elif cs >= 60:       bucket = "MODERATE (60-70)"
        elif cs >= 50:       bucket = "WEAK (50-60)"
        else:                bucket = "BELOW 50"
        if bucket not in score_breakdown:
            score_breakdown[bucket] = {'total': 0, 't1': 0, 'sl': 0}
        score_breakdown[bucket]['total'] += 1
        if r[9] in ('T1_HIT', 'T2_HIT', 'T3_HIT'):
            score_breakdown[bucket]['t1'] += 1
        if r[9] == 'SL_HIT':
            score_breakdown[bucket]['sl'] += 1

    denom = max(1, n)
    display_map = {
        'T3_HIT': '🎯🎯🎯 T3 HIT', 'T2_HIT': '🎯🎯 T2 HIT', 'T1_HIT': '🎯 T1 HIT',
        'SL_HIT': '🛑 STOP LOSS HIT', 'EXPIRED': '📋 EXPIRED', 'PENDING': '⏳ PENDING',
    }
    records = []
    for r in all_rows:
        s_date, sym, sig, entry, t1, t2, t3, sl, score, status, mx, mn, ex_date, days, gain, trailing = r
        max_gain = None
        if mx and entry and entry > 0:
            max_gain = round((mx - entry) / entry * 100, 2) if sig == 'BUY' else (
                round((entry - mn) / entry * 100, 2) if mn else None)
        records.append({
            'date': s_date, 'symbol': sym, 'signal': sig,
            'entry_price': round(entry, 2) if entry else None,
            'target_1': round(t1, 2) if t1 else None,
            'target_2': round(t2, 2) if t2 else None,
            'target_3': round(t3, 2) if t3 else None,
            'stop_loss': round(sl, 2) if sl else None,
            'trailing_stop': round(trailing, 2) if trailing else None,
            'composite_score': round(score, 1) if score else None,
            'status': display_map.get(status, status),
            'exit_date': ex_date, 'days_to_outcome': days,
            'realized_gain_pct': round(gain, 2) if gain is not None else None,
            'max_gain_pct': max_gain,
        })

    return {
        'total_signals_tracked': len(all_rows),
        'completed_signals': n,
        'pending_signals': len(pending),
        'active_signals': len(pending),
        't1_hits_count': t1_hits, 't2_hits_count': t2_hits,
        't3_hits_count': t3_hits, 'sl_hits_count': sl_hits,
        'profitable_count': profitable,
        'target_1_hit_rate_pct': round(t1_hits / denom * 100, 1),
        'target_2_hit_rate_pct': round(t2_hits / denom * 100, 1),
        'target_3_hit_rate_pct': round(t3_hits / denom * 100, 1),
        'stop_loss_hit_rate_pct': round(sl_hits / denom * 100, 1),
        'overall_win_rate_pct': round(profitable / denom * 100, 1),
        'in_play_profitable_pct': round(profitable / denom * 100, 1),
        'active_intact_rate_pct': round(max(0.0, 1.0 - sl_hits / denom) * 100, 1),
        'profit_factor': round(sum(gains) / max(0.01, sum(losses)), 2) if gains else 1.0,
        'avg_peak_gain_mfe': round(float(np.mean(mfe_list)), 2) if mfe_list else 0.0,
        'avg_max_drawdown_mae': round(float(np.mean(mae_list)), 2) if mae_list else 0.0,
        'avg_days_to_outcome': round(float(np.mean(days_list)), 1) if days_list else 0.0,
        'score_breakdown': score_breakdown,
        'records': records,
    }
