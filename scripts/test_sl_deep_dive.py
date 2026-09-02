import sys
import io
from pathlib import Path
import pandas as pd
import numpy as np

# Ensure UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from sqlalchemy import text

engine = get_global_engine()
session = get_session(engine)

# Query all SL_HIT records
sl_rows = session.execute(text("""
    SELECT id, signal_date, symbol, signal, entry_price, target_1, target_2, target_3,
           stop_loss, trailing_stop, status, exit_date, days_to_outcome,
           COALESCE(asset_type, 'STOCK') as asset_type
    FROM signal_audit_log
    WHERE status = 'SL_HIT'
    ORDER BY signal_date DESC
""")).fetchall()

print(f"Total Stop Loss Exits to analyze: {len(sl_rows)}")

stats = {
    'total_sl': len(sl_rows),
    'saved_capital': 0,
    'whipsaw_t1': 0,
    'partial_rebound': 0,
    'cascade_down': 0,
    'avg_downside_avoided_pct': [],
    'avg_rebound_mfe_pct': [],
}

samples = []

for r in sl_rows:
    row_id, s_date, sym, sig, entry, t1, t2, t3, sl, trailing_sl, status, ex_date, days, asset_t = r
    effective_sl = trailing_sl if trailing_sl is not None else sl
    if not effective_sl or not entry:
        continue

    tbl = "index_prices" if asset_t == "INDEX" else ("commodity_prices" if asset_t == "COMMODITY" else "daily_prices")
    fwd_prices = session.execute(text(f"""
        SELECT date, high, low, close FROM {tbl}
        WHERE symbol = :s AND date > :d ORDER BY date ASC LIMIT 90
    """), {'s': sym, 'd': s_date}).fetchall()

    if not fwd_prices:
        continue

    # Find the index corresponding to exit_date
    sl_idx = 0
    if ex_date:
        for idx, p in enumerate(fwd_prices):
            if str(p[0]) == str(ex_date):
                sl_idx = idx
                break
    else:
        sl_idx = min(len(fwd_prices) - 1, max(0, (days or 1) - 1))

    post_bars = fwd_prices[sl_idx:]
    if not post_bars:
        post_bars = fwd_prices[-1:]

    if sig == 'BUY':
        post_max_high = max(float(p[1]) for p in post_bars)
        post_min_low = min(float(p[2]) for p in post_bars)
        post_close = float(post_bars[-1][3])
        post_sl_mfe = (post_max_high - float(effective_sl)) / float(effective_sl) * 100
        post_sl_mae = (float(effective_sl) - post_min_low) / float(effective_sl) * 100

        if t1 and post_max_high >= float(t1):
            behavior = 'WHIPSAW_T1'
            behavior_desc = f"🎣 Whipsaw: Rebounded & Hit Target 1 (High: ₹{post_max_high:,.1f})"
            stats['whipsaw_t1'] += 1
            stats['avg_rebound_mfe_pct'].append(post_sl_mfe)
        elif post_max_high >= float(entry) * 1.005:
            behavior = 'PARTIAL_REBOUND'
            behavior_desc = f"🔄 Rebounded Above Entry (High: ₹{post_max_high:,.1f}, +{post_sl_mfe:.1f}% from SL)"
            stats['partial_rebound'] += 1
            stats['avg_rebound_mfe_pct'].append(post_sl_mfe)
        elif post_min_low <= float(effective_sl) * 0.985:
            behavior = 'SAVED_CAPITAL'
            behavior_desc = f"🛡️ Saved -{post_sl_mae:.1f}% Bleed (Dropped to ₹{post_min_low:,.1f})"
            stats['saved_capital'] += 1
            stats['avg_downside_avoided_pct'].append(post_sl_mae)
        else:
            behavior = 'CASCADE_DOWN'
            behavior_desc = f"📉 Continued Below SL (Current: ₹{post_close:,.1f})"
            stats['cascade_down'] += 1
            if post_sl_mae > 0:
                stats['avg_downside_avoided_pct'].append(post_sl_mae)
    else: # SELL
        post_max_high = max(float(p[1]) for p in post_bars)
        post_min_low = min(float(p[2]) for p in post_bars)
        post_close = float(post_bars[-1][3])
        post_sl_mfe = (float(effective_sl) - post_min_low) / float(effective_sl) * 100
        post_sl_mae = (post_max_high - float(effective_sl)) / float(effective_sl) * 100

        if t1 and post_min_low <= float(t1):
            behavior = 'WHIPSAW_T1'
            behavior_desc = f"🎣 Whipsaw: Dropped & Hit Target 1 (Low: ₹{post_min_low:,.1f})"
            stats['whipsaw_t1'] += 1
            stats['avg_rebound_mfe_pct'].append(post_sl_mfe)
        elif post_min_low <= float(entry) * 0.995:
            behavior = 'PARTIAL_REBOUND'
            behavior_desc = f"🔄 Dropped Below Entry (Low: ₹{post_min_low:,.1f}, +{post_sl_mfe:.1f}% from SL)"
            stats['partial_rebound'] += 1
            stats['avg_rebound_mfe_pct'].append(post_sl_mfe)
        elif post_max_high >= float(effective_sl) * 1.015:
            behavior = 'SAVED_CAPITAL'
            behavior_desc = f"🛡️ Saved +{post_sl_mae:.1f}% Squeeze (High: ₹{post_max_high:,.1f})"
            stats['saved_capital'] += 1
            stats['avg_downside_avoided_pct'].append(post_sl_mae)
        else:
            behavior = 'CASCADE_DOWN'
            behavior_desc = f"📈 Squeezed Above SL (Current: ₹{post_close:,.1f})"
            stats['cascade_down'] += 1
            if post_sl_mae > 0:
                stats['avg_downside_avoided_pct'].append(post_sl_mae)

    samples.append({
        'symbol': sym, 'sig': sig, 'entry': entry, 'sl': effective_sl,
        'ex_date': ex_date, 'behavior': behavior, 'desc': behavior_desc
    })

tot = max(1, stats['total_sl'])
print("\n=== EMPIRICAL STOP LOSS QUALITY & POST-EXIT ANALYSIS ===")
print(f"Total Stop Loss Exits Evaluated: {stats['total_sl']}")
print(f"🛡️ Valid Capital-Saving Stops (Price kept falling): {stats['saved_capital']} ({stats['saved_capital']/tot*100:.1f}%)")
print(f"📉 Flat / Continued Below SL:                    {stats['cascade_down']} ({stats['cascade_down']/tot*100:.1f}%)")
print(f"🔄 Partial Rebounds (Bounced above entry):       {stats['partial_rebound']} ({stats['partial_rebound']/tot*100:.1f}%)")
print(f"🎣 Whipsaw Shakeouts (Hit SL then Hit Target 1): {stats['whipsaw_t1']} ({stats['whipsaw_t1']/tot*100:.1f}%)")
if stats['avg_downside_avoided_pct']:
    print(f"🛡️ Avg Downside Avoided when cutting loss:       -{np.mean(stats['avg_downside_avoided_pct']):.2f}%")
if stats['avg_rebound_mfe_pct']:
    print(f"🔄 Avg Rebound after Whipsaw/Bounce:             +{np.mean(stats['avg_rebound_mfe_pct']):.2f}%")

print("\n--- SAMPLE STOP LOSS DIAGNOSTICS (FIRST 10) ---")
for s in samples[:10]:
    print(f"• {s['symbol']} ({s['sig']}) | Entry: ₹{s['entry']:.1f} | SL: ₹{s['sl']:.1f} | Exit: {s['ex_date']} -> {s['desc']}")
