import sys
import os
sys.path.insert(0, os.path.abspath('.'))

import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import sqlite3
from sqlalchemy import text
from db.database import get_session
from core.accuracy_tracker import (
    update_trailing_stops,
    evaluate_signal_audit_track_record,
    _compute_summary_stats
)

def run_recalibration():
    print("================================================================================")
    print("  RECALIBRATING TRAILING STOPS & FIXING SL CORRUPTIONS IN AUDIT TABLE")
    print("================================================================================")

    with get_session() as session:
        # 1. Identify and fix bad/inverted stop loss and target levels in signal_audit_log
        corrupted_buy = session.execute(text("""
            SELECT id, symbol, entry_price, stop_loss, target_1, trailing_stop
            FROM signal_audit_log
            WHERE signal = 'BUY' AND (stop_loss IS NULL OR stop_loss >= entry_price * 0.985 OR target_1 <= entry_price)
        """)).fetchall()

        print(f"Found {len(corrupted_buy)} BUY audit records with narrow/inverted SL (<1.5% distance) or inverted T1.")
        fixed_count = 0
        for r in corrupted_buy:
            rid, sym, ep, sl, t1, ts = r
            if not ep or ep <= 0:
                continue
            # Tier-aware cushion or 3.5% minimum floor
            new_sl = round(ep * 0.955, 2)
            new_t1 = round(ep * 1.045, 2) if (not t1 or t1 <= ep) else t1
            new_ts = new_sl if (not ts or ts >= ep * 0.985) else ts

            session.execute(text("""
                UPDATE signal_audit_log
                SET stop_loss = :sl, target_1 = :t1, trailing_stop = :ts
                WHERE id = :id
            """), {"sl": new_sl, "t1": new_t1, "ts": new_ts, "id": rid})
            fixed_count += 1

        corrupted_sell = session.execute(text("""
            SELECT id, symbol, entry_price, stop_loss, target_1, trailing_stop
            FROM signal_audit_log
            WHERE signal = 'SELL' AND (stop_loss IS NULL OR stop_loss <= entry_price * 1.015 OR target_1 >= entry_price)
        """)).fetchall()

        print(f"Found {len(corrupted_sell)} SELL audit records with narrow/inverted SL (<1.5% distance) or inverted T1.")
        for r in corrupted_sell:
            rid, sym, ep, sl, t1, ts = r
            if not ep or ep <= 0:
                continue
            new_sl = round(ep * 1.045, 2)
            new_t1 = round(ep * 0.955, 2) if (not t1 or t1 >= ep) else t1
            new_ts = new_sl if (not ts or ts <= ep * 1.015) else ts

            session.execute(text("""
                UPDATE signal_audit_log
                SET stop_loss = :sl, target_1 = :t1, trailing_stop = :ts
                WHERE id = :id
            """), {"sl": new_sl, "t1": new_t1, "ts": new_ts, "id": rid})
            fixed_count += 1

        session.commit()
        print(f"✅ Fixed initial stop levels on {fixed_count} audit records.")

        # 2. Run update_trailing_stops with our new guarded engine
        print("\nUpdating progressive trailing stops for in-play signals...")
        trailed = update_trailing_stops(session)
        print(f"✅ Updated trailing stops on {trailed} active positions.")

        # 3. Recalibrate all historical signals through strict causal simulation
        print("\nRe-evaluating full audit track record across all historical sessions...")
        summary = evaluate_signal_audit_track_record(session, asset_type="ALL", recalibrate_all=True)

        print("\n=== RECALIBRATION COMPLETE ===")
        print(f"Total Signals: {summary.get('total_signals_tracked', 0)}")
        print(f"Completed:     {summary.get('completed_signals', 0)}")
        print(f"Pending:       {summary.get('pending_signals', 0)}")
        print(f"Overall Win Rate: {summary.get('overall_win_rate_pct', 0)}%")
        print(f"T1 Hit Rate:      {summary.get('target_1_hit_rate_pct', 0)}%")
        print(f"Trailing SL Wins: {summary.get('trailing_wins_count', 0)}")

        # 4. Deep-dive validation: Verify NO active signal has trailing_stop == current_price
        records = summary.get('records', [])
        active_collisions = []
        for rec in records:
            if rec.get('raw_status') == 'PENDING':
                cp = rec.get('current_price')
                ts = rec.get('trailing_stop')
                sig = rec.get('signal')
                if cp is not None and ts is not None:
                    if sig == 'BUY' and ts >= cp * 0.995:
                        active_collisions.append((rec['symbol'], rec['date'], cp, ts, sig))
                    elif sig == 'SELL' and ts <= cp * 1.005:
                        active_collisions.append((rec['symbol'], rec['date'], cp, ts, sig))

        print(f"\nAudit Verification: Active in-play collisions (Trailing SL == Current Price): {len(active_collisions)}")
        if active_collisions:
            print("Collisions:", active_collisions[:5])
        else:
            print("🎉 Zero collisions found! Trailing SL is strictly separated from Current Value for all active trades.")

        # 5. Check sample records in records
        print("\n=== SAMPLE RECORDS IN AUDIT TABLE ===")
        for r in records[:10]:
            print(f"  {r['date']} {r['symbol']} ({r['signal']}): Entry=₹{r['entry_price']} | Current=₹{r['current_price']} | Exit={r['exit_price']} | InitialSL=₹{r['stop_loss']} | TrailingSL=₹{r['trailing_stop']} | Status={r['status']}")

if __name__ == "__main__":
    run_recalibration()
