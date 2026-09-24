"""
Comprehensive Audit Tables Deep-Dive & XIRR Analysis Engine
Analyzes:
1. signal_audit_log across Stocks, Indices, Commodities, Breakouts
   - Hit rates (T1, T2, T3, Trailing SL, True SL)
   - Win Rate & Intact Rate
   - Profit Factor & Payoff Ratio
   - Average Win % vs Average Loss %
   - Days to Outcome (Velocity)
   - Annualized Cash-Flow XIRR (Resolved + Mark-to-Market Pending)
2. missed_alpha_audit_log (False negative surveillance & alpha capture rate)
3. sip_suggestion_log (Forward performance of recommended baskets)
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import pandas as pd
import numpy as np
from datetime import datetime, date
from sqlalchemy import text
from db.database import get_global_engine, get_session
from core.accuracy_tracker import evaluate_signal_audit_track_record
from core.sip_audit_backtester import calculate_xirr

def compute_signal_audit_xirr(session, asset_type: str = "ALL", trade_size: float = 10000.0) -> dict:
    """
    Computes annualized cash-flow XIRR for signals in signal_audit_log.
    Simulates equal allocation per trade (trade_size), recording:
    - Cash outflow on signal_date
    - Cash inflow on exit_date (for completed trades)
    - Terminal valuation on latest date (for pending trades)
    """
    where_clause = ""
    params = {}
    if asset_type != "ALL":
        where_clause = "WHERE asset_type = :at"
        params = {"at": asset_type}

    query = f"""
        SELECT signal_date, exit_date, status, realized_gain_pct, unrealized_gain_pct, entry_price
        FROM signal_audit_log
        {where_clause}
        ORDER BY signal_date ASC
    """
    rows = session.execute(text(query), params).fetchall()
    if not rows:
        return {"xirr": 0.0, "total_trades": 0, "net_profit": 0.0}

    # Latest date for mark-to-market
    latest_date_str = session.execute(text("SELECT MAX(date) FROM daily_prices")).scalar() or str(date.today())
    latest_dt = datetime.strptime(str(latest_date_str)[:10], "%Y-%m-%d").date()

    daily_flows = {}
    total_invested_gross = 0.0
    total_returned_gross = 0.0

    completed_cnt = 0
    pending_cnt = 0

    for r in rows:
        s_date_str = str(r[0])[:10]
        ex_date_str = str(r[1])[:10] if r[1] else None
        status = r[2]
        realized_pct = float(r[3]) if r[3] is not None else None
        unrealized_pct = float(r[4]) if r[4] is not None else 0.0

        try:
            s_dt = datetime.strptime(s_date_str, "%Y-%m-%d").date()
        except Exception:
            continue

        # Cash outflow on signal_date
        daily_flows[s_dt] = daily_flows.get(s_dt, 0.0) - trade_size
        total_invested_gross += trade_size

        if status != "PENDING" and ex_date_str and realized_pct is not None:
            completed_cnt += 1
            try:
                ex_dt = datetime.strptime(ex_date_str, "%Y-%m-%d").date()
            except Exception:
                ex_dt = s_dt
            if ex_dt <= s_dt:
                ex_dt = s_dt + pd.Timedelta(days=1)
            
            payout = trade_size * (1.0 + realized_pct / 100.0)
            daily_flows[ex_dt] = daily_flows.get(ex_dt, 0.0) + payout
            total_returned_gross += payout
        else:
            # Pending position marked to market on latest_dt
            pending_cnt += 1
            mtm_value = trade_size * (1.0 + unrealized_pct / 100.0)
            daily_flows[latest_dt] = daily_flows.get(latest_dt, 0.0) + mtm_value
            total_returned_gross += mtm_value

    cash_flows = sorted([(d, round(amt, 2)) for d, amt in daily_flows.items()], key=lambda x: x[0])
    
    # Calculate XIRR
    xirr_val = calculate_xirr(cash_flows)
    net_profit = total_returned_gross - total_invested_gross
    roi_pct = round(net_profit / max(1.0, total_invested_gross) * 100.0, 2)

    return {
        "xirr": xirr_val,
        "roi_pct": roi_pct,
        "total_invested": total_invested_gross,
        "total_returned": total_returned_gross,
        "net_profit": net_profit,
        "completed_count": completed_cnt,
        "pending_count": pending_cnt,
        "total_count": len(rows),
    }


def analyze_all_audit_tables():
    engine = get_global_engine()
    session = get_session(engine)

    print("=" * 95)
    print("🎯 MULTI-ASSET SIGNAL AUDIT TRACK RECORD & PERFORMANCE DIAGNOSTICS")
    print("=" * 95)

    asset_classes = ["ALL", "STOCK", "INDEX", "COMMODITY", "BREAKOUT"]
    summary_table = []

    for ac in asset_classes:
        stats = evaluate_signal_audit_track_record(session, asset_type=ac)
        xirr_data = compute_signal_audit_xirr(session, asset_type=ac)

        summary_table.append({
            "Asset": ac,
            "Total": stats.get("total_signals_tracked", 0),
            "Closed": stats.get("completed_signals", 0),
            "Pending": stats.get("pending_signals", 0),
            "Win Rate": f"{stats.get('overall_win_rate_pct', 0.0):.1f}%",
            "T1 Hit": f"{stats.get('target_1_hit_rate_pct', 0.0):.1f}%",
            "Trailing SL": f"{stats.get('trailing_sl_hit_rate_pct', 0.0):.1f}%",
            "SL Loss": f"{stats.get('stop_loss_hit_rate_pct', 0.0):.1f}%",
            "Profit Factor": f"{stats.get('profit_factor', 0.0):.2f}",
            "Avg Days": f"{stats.get('avg_days_to_outcome', 0.0):.1f}",
            "XIRR": f"{xirr_data.get('xirr', 0.0):.1f}%",
            "ROI": f"{xirr_data.get('roi_pct', 0.0):.1f}%"
        })

    df_sum = pd.DataFrame(summary_table)
    print(df_sum.to_string(index=False))

    print("\n" + "=" * 95)
    print("🔍 MISSED ALPHA & SURVEILLANCE AUDIT TRACK RECORD")
    print("=" * 95)
    missed_count = session.execute(text("SELECT COUNT(*) FROM missed_alpha_audit_log")).scalar()
    print(f"Total Missed Alpha Events Audited: {missed_count}")
    if missed_count > 0:
        top_bottlenecks = session.execute(text("""
            SELECT bottleneck, COUNT(*) as cnt, AVG(gain_pct) as avg_gain
            FROM missed_alpha_audit_log
            GROUP BY bottleneck
            ORDER BY cnt DESC LIMIT 5
        """)).fetchall()
        print("\nTop Filtering Bottlenecks on Missed Explosive Movers:")
        for b in top_bottlenecks:
            print(f"  • {str(b[0]):<40} : {b[1]:>3} occurrences | Avg Missed Gain: +{b[2]:.1f}%")

    print("\n" + "=" * 95)
    print("💼 SIP SUGGESTION AUDIT TRACK RECORD")
    print("=" * 95)
    sip_count = session.execute(text("SELECT COUNT(*) FROM sip_suggestion_log")).scalar()
    print(f"Total SIP Baskets Audited: {sip_count}")
    if sip_count > 0:
        sip_stats = session.execute(text("""
            SELECT strategy, COUNT(*) as recommendations, AVG(alpha_pct) as avg_alpha,
                   SUM(CASE WHEN alpha_pct > 0 THEN 1 ELSE 0 END) as beating_nifty
            FROM sip_suggestion_log
            GROUP BY strategy
        """)).fetchall()
        for s in sip_stats:
            win_pct = round((s[3] or 0) / max(1, s[1]) * 100.0, 1)
            alpha_val = s[2] if s[2] is not None else 0.0
            print(f"  • Strategy: {str(s[0]):<20} | Items: {s[1]:>2} | Avg Alpha: {alpha_val:+5.2f}% | Beating Nifty: {win_pct}%")

    session.close()

if __name__ == "__main__":
    analyze_all_audit_tables()
