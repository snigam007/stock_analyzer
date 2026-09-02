import sys
import io
import json
from pathlib import Path
import pandas as pd
import numpy as np
from sqlalchemy import text

# Ensure UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from core.accuracy_tracker import evaluate_signal_audit_track_record, log_current_signals_to_audit
from core.missed_signals import scan_missed_opportunities

engine = get_global_engine()
session = get_session(engine)

# 1. Update audit evaluation
logged = log_current_signals_to_audit(session)
audit_stats = evaluate_signal_audit_track_record(session)

print("=" * 80)
print("🎯 EMPIRICAL SIGNAL ACCURACY & AUDIT TRACK RECORD")
print("=" * 80)

q_audit = """
    SELECT sal.id, sal.signal_date, sal.symbol, stk.name, stk.sector, stk.market_cap_tier as tier,
           sal.signal, sal.entry_price, sal.target_1, sal.target_2, sal.target_3,
           sal.stop_loss, sal.composite_score, sal.status, sal.max_price_reached,
           sal.min_price_reached, sal.exit_date, sal.days_to_outcome, sal.realized_gain_pct,
           sal.trailing_stop, COALESCE(sal.risk_level, sig.risk_level, 'MODERATE') as risk_level
    FROM signal_audit_log sal
    JOIN stocks stk ON sal.symbol = stk.symbol
    LEFT JOIN signals sig ON sal.symbol = sig.symbol AND sal.signal_date = sig.date
    ORDER BY sal.signal_date ASC, sal.symbol ASC
"""
df_audit = pd.read_sql(q_audit, session.connection())

resolved = df_audit[df_audit['status'] != 'PENDING'].copy()
pending = df_audit[df_audit['status'] == 'PENDING'].copy()

print(f"Total Audit Entries Tracked: {len(df_audit)}")
print(f"Resolved (Completed Forward Evaluations): {len(resolved)}")
print(f"Active / In Play (Pending Forward Outcomes): {len(pending)}")
print("\nStatus Distribution:")
print(df_audit['status'].value_counts().to_string())

# Performance metrics for resolved trades
resolved['is_t1_hit'] = resolved['status'].isin(['T1_HIT', 'T2_HIT', 'T3_HIT'])
resolved['is_sl_hit'] = resolved['status'] == 'SL_HIT'
resolved['is_expired'] = resolved['status'] == 'EXPIRED'

t1_count = resolved['is_t1_hit'].sum()
sl_count = resolved['is_sl_hit'].sum()
t2_count = resolved['status'].isin(['T2_HIT', 'T3_HIT']).sum()
t3_count = (resolved['status'] == 'T3_HIT').sum()

win_rate = (t1_count / len(resolved) * 100) if len(resolved) > 0 else 0.0
sl_rate = (sl_count / len(resolved) * 100) if len(resolved) > 0 else 0.0

gains = resolved[resolved['realized_gain_pct'] > 0]['realized_gain_pct']
losses = resolved[resolved['realized_gain_pct'] < 0]['realized_gain_pct'].abs()
profit_factor = (gains.sum() / max(losses.sum(), 0.001)) if len(losses) > 0 else 0.0
avg_win = gains.mean() if len(gains) > 0 else 0.0
avg_loss = losses.mean() if len(losses) > 0 else 0.0

# Calculate MFE and MAE
mfe_list, mae_list = [], []
for _, r in resolved.iterrows():
    entry = float(r['entry_price'])
    sig = r['signal']
    mx = float(r['max_price_reached']) if r['max_price_reached'] else entry
    mn = float(r['min_price_reached']) if r['min_price_reached'] else entry
    if entry > 0:
        if sig == 'BUY':
            mfe_list.append((mx - entry) / entry * 100.0)
            mae_list.append((entry - mn) / entry * 100.0)
        else:
            mfe_list.append((entry - mn) / entry * 100.0)
            mae_list.append((mx - entry) / entry * 100.0)

avg_mfe = np.mean(mfe_list) if mfe_list else 0.0
avg_mae = np.mean(mae_list) if mae_list else 0.0
avg_days = resolved['days_to_outcome'].mean() if len(resolved) > 0 else 0.0

print("\n--- KEY PERFORMANCE INDICATORS ---")
print(f"Overall Target 1 Hit Rate: {win_rate:.2f}% ({t1_count}/{len(resolved)})")
print(f"Target 2 Hit Rate:         {t2_count / max(1, len(resolved)) * 100:.2f}% ({t2_count}/{len(resolved)})")
print(f"Target 3 Hit Rate:         {t3_count / max(1, len(resolved)) * 100:.2f}% ({t3_count}/{len(resolved)})")
print(f"Stop-Loss Hit Rate:        {sl_rate:.2f}% ({sl_count}/{len(resolved)})")
print(f"Profit Factor:             {profit_factor:.2f}x (Total Gains: +{gains.sum():.1f}% vs Total Losses: -{losses.sum():.1f}%)")
print(f"Average Winner Gain:       +{avg_win:.2f}%")
print(f"Average Loser Loss:        -{avg_loss:.2f}%")
print(f"Reward-to-Risk Ratio:      {(avg_win / max(avg_loss, 0.001)):.2f}:1")
print(f"Average Peak Gain (MFE):   +{avg_mfe:.2f}%")
print(f"Average Max Drawdown (MAE): -{avg_mae:.2f}%")
print(f"Avg Days to Outcome:       {avg_days:.1f} sessions")

# By Signal Type (BUY vs SELL)
print("\n--- BREAKDOWN BY SIGNAL TYPE ---")
sig_group = resolved.groupby('signal').agg(
    total=('id', 'count'),
    t1_hits=('is_t1_hit', 'sum'),
    sl_hits=('is_sl_hit', 'sum'),
    win_rate=('is_t1_hit', lambda x: f"{x.mean()*100:.1f}%"),
    avg_return=('realized_gain_pct', 'mean')
)
print(sig_group.to_string())

# By Score Buckets
resolved['score_bucket'] = pd.cut(
    resolved['composite_score'],
    bins=[0, 50, 60, 70, 100],
    labels=['<50 (Weak)', '50-60 (Watch/Border)', '60-70 (Moderate)', '70+ (Strong)']
)
print("\n--- BREAKDOWN BY COMPOSITE SCORE TIER ---")
score_group = resolved.groupby('score_bucket', observed=False).agg(
    total=('id', 'count'),
    t1_hits=('is_t1_hit', 'sum'),
    sl_hits=('is_sl_hit', 'sum'),
    win_rate=('is_t1_hit', lambda x: f"{x.mean()*100:.1f}%"),
    avg_return=('realized_gain_pct', 'mean')
)
print(score_group.to_string())

# By Risk Level
print("\n--- BREAKDOWN BY RISK LEVEL ---")
risk_group = resolved.groupby('risk_level').agg(
    total=('id', 'count'),
    t1_hits=('is_t1_hit', 'sum'),
    sl_hits=('is_sl_hit', 'sum'),
    win_rate=('is_t1_hit', lambda x: f"{x.mean()*100:.1f}%"),
    avg_return=('realized_gain_pct', 'mean')
)
print(risk_group.to_string())

# By Market Cap Tier
print("\n--- BREAKDOWN BY MARKET CAP TIER ---")
tier_group = resolved.groupby('tier').agg(
    total=('id', 'count'),
    t1_hits=('is_t1_hit', 'sum'),
    sl_hits=('is_sl_hit', 'sum'),
    win_rate=('is_t1_hit', lambda x: f"{x.mean()*100:.1f}%"),
    avg_return=('realized_gain_pct', 'mean')
)
print(tier_group.to_string())

# By Sector (Top Sectors)
print("\n--- TOP SECTORS BY TRADE VOLUME & WIN RATE ---")
sec_group = resolved.groupby('sector').agg(
    total=('id', 'count'),
    t1_hits=('is_t1_hit', 'sum'),
    sl_hits=('is_sl_hit', 'sum'),
    win_rate=('is_t1_hit', lambda x: f"{x.mean()*100:.1f}%"),
    avg_return=('realized_gain_pct', 'mean')
)
print(sec_group[sec_group['total'] >= 5].sort_values('total', ascending=False).to_string())

# Top 10 Best Realized Trades
print("\n--- TOP 10 BEST REALIZED SIGNALS ---")
top_winners = resolved.sort_values('realized_gain_pct', ascending=False).head(10)
for idx, r in top_winners.iterrows():
    print(f"• {r['symbol']} ({r['name']}) [{r['signal_date']}] {r['signal']} @ {r['entry_price']:.1f} -> Return: +{r['realized_gain_pct']:.2f}% | Status: {r['status']} | Score: {r['composite_score']:.1f} | Days: {r['days_to_outcome']}")

# Top 5 Stop Loss Hits
print("\n--- NOTABLE STOP LOSS EXITS ---")
worst_losers = resolved.sort_values('realized_gain_pct', ascending=True).head(5)
for idx, r in worst_losers.iterrows():
    print(f"• {r['symbol']} ({r['name']}) [{r['signal_date']}] {r['signal']} @ {r['entry_price']:.1f} -> Return: {r['realized_gain_pct']:.2f}% | Status: {r['status']} | Score: {r['composite_score']:.1f} | Days: {r['days_to_outcome']}")

# Pending signals by date
print("\n--- ACTIVE / IN-PLAY (PENDING) SIGNALS BREAKDOWN ---")
print(pending.groupby('signal_date').agg(
    pending_signals=('id', 'count'),
    buy_signals=('signal', lambda x: (x == 'BUY').sum()),
    sell_signals=('signal', lambda x: (x == 'SELL').sum()),
    avg_composite_score=('composite_score', 'mean')
).to_string())

# 2. Missed Signals & Uncaught Alpha Analysis
print("\n" + "=" * 80)
print("🔍 MISSED SIGNALS & UNCAUGHT ALPHA SURVEILLANCE")
print("=" * 80)

for lb, mg in [(1, 2.5), (3, 3.5), (5, 4.0), (7, 5.0)]:
    m_data = scan_missed_opportunities(session, lookback_days=lb, min_gain_pct=mg)
    s = m_data['summary']
    print(f"\n--- {lb}-DAY WINDOW (Min Gain >= +{mg}%) ---")
    print(f"Total High-Velocity Movers: {s.get('total_movers_detected', 0)}")
    print(f"Caught by BUY Signal:       {s.get('caught_buyers', 0)} ({s.get('capture_rate_pct', 0.0)}% capture rate)")
    print(f"Uncaught / Missed on WATCH: {s.get('missed_movers_count', 0)}")
    print(f"Avg Missed Alpha:           +{s.get('avg_missed_gain_pct', 0.0)}%")
    print(f"Primary Bottleneck Factor:  {s.get('top_bottleneck_factor', 'None')}")

# Deep dive on 5-Day Missed Movers
m_5d = scan_missed_opportunities(session, lookback_days=5, min_gain_pct=4.0)
df_m5 = pd.DataFrame(m_5d['missed_movers'])

if not df_m5.empty:
    print("\n--- 5-DAY MISSED MOVERS: BOTTLENECK FREQUENCY ---")
    print(df_m5['bottleneck'].value_counts().to_string())

    print("\n--- 5-DAY MISSED MOVERS: SECTOR CONCENTRATION ---")
    print(df_m5['sector'].value_counts().to_string())

    print("\n--- 5-DAY MISSED MOVERS: MARKET CAP CONCENTRATION ---")
    print(df_m5['tier'].value_counts().to_string())

    print("\n--- DETAILED DIAGNOSTIC LIST OF 5-DAY MISSED RUNNERS ---")
    for _, m in df_m5.iterrows():
        print(f"• {m['symbol']} ({m['name']}) | Gain: +{m['gain_pct']:.2f}% (Price: {m['start_price']:.1f} -> {m['end_price']:.1f})")
        print(f"  Score: {m['start_score']:.1f} | RSI: {m['rsi']:.1f} | ADX: {m['adx']:.1f} | VolRatio: {m['vol_ratio']:.2f}x | Pattern: {m['pattern_catalyst']}")
        print(f"  Bottleneck: {m['bottleneck']}")
        print(f"  Diagnosis:  {m['diagnosis']}")
        print(f"  Remedy:     {m['actionable_takeaway']}\n")

print("Analysis complete!")
