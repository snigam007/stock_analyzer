"""
Deep Loss Diagnostic Script
Analyse WHY the 220 true stop-loss exits happen and what could have prevented them.
"""
import sqlite3
import pandas as pd
import numpy as np

conn = sqlite3.connect('data/stock_analyzer.db')

q = """
SELECT sal.status, sal.composite_score, sal.realized_gain_pct, sal.risk_level,
       sal.signal, sal.entry_price, sal.stop_loss, sal.target_1, sal.target_2,
       sal.signal_date, sal.exit_date, sal.days_to_outcome, sal.symbol,
       sal.max_price_reached, sal.min_price_reached, sal.trailing_stop,
       stk.market_cap_tier, stk.sector
FROM signal_audit_log sal
LEFT JOIN stocks stk ON sal.symbol = stk.symbol
WHERE sal.asset_type = 'STOCK' AND sal.status != 'PENDING'
"""
df = pd.read_sql(q, conn)

df['is_loss'] = (df['status'] == 'SL_HIT') & (df['realized_gain_pct'].fillna(0) <= 0)
df['is_win'] = df['status'].isin(['T1_HIT', 'T2_HIT', 'T3_HIT', 'TRAILING_SL_HIT'])

wins = df[df['is_win']].copy()
losses = df[df['is_loss']].copy()

print("=" * 60)
print("1. SCORE DISTRIBUTION: LOSSES vs WINS")
print("=" * 60)
print(f"Loss count: {len(losses)}")
print(f"Win count: {len(wins)}")
print(f"Loss avg composite_score: {losses['composite_score'].mean():.1f}")
print(f"Win avg composite_score: {wins['composite_score'].mean():.1f}")

print("\n=== SCORE BUCKETS FOR ALL RESOLVED TRADES ===")
all_res = df[df['status'] != 'PENDING'].copy()
all_res['score_bucket'] = pd.cut(
    all_res['composite_score'].fillna(60),
    bins=[0, 55, 60, 63, 65, 68, 70, 100],
    labels=['<55', '55-60', '60-63', '63-65', '65-68', '68-70', '70+']
)
for bucket in ['<55', '55-60', '60-63', '63-65', '65-68', '68-70', '70+']:
    sub = all_res[all_res['score_bucket'] == bucket]
    if len(sub) > 0:
        loss_r = len(sub[sub['is_loss']]) / len(sub) * 100
        win_r = len(sub[sub['is_win']]) / len(sub) * 100
        print(f"  {bucket}: {len(sub)} trades, loss={loss_r:.1f}%, win={win_r:.1f}%")

print("\n=== LOSS RATE BY RISK LEVEL ===")
for rl in ['SAFE', 'MODERATE', 'RISKY']:
    sub = all_res[all_res['risk_level'] == rl]
    if len(sub) > 0:
        loss_r = len(sub[sub['is_loss']]) / len(sub) * 100
        avg_score = sub['composite_score'].mean()
        print(f"  {rl}: {len(sub)} trades, loss={loss_r:.1f}%, avg_score={avg_score:.1f}")

print("\n=== SL DISTANCE ANALYSIS ===")
df['sl_distance_pct'] = ((df['entry_price'] - df['stop_loss']) / df['entry_price'] * 100).abs()
df['t1_upside_pct'] = ((df['target_1'] - df['entry_price']) / df['entry_price'] * 100).abs()
# Re-derive wins/losses after new columns
losses = df[df['is_loss']].copy()
wins = df[df['is_win']].copy()
df['rr_ratio'] = df['t1_upside_pct'] / df['sl_distance_pct'].replace(0, np.nan)

print("Loss avg SL distance:", round(losses['sl_distance_pct'].mean(), 2))
print("Win avg SL distance:", round(wins['sl_distance_pct'].mean(), 2))
print("Loss avg T1 upside:", round(losses['t1_upside_pct'].mean(), 2))
print("Win avg T1 upside:", round(wins['t1_upside_pct'].mean(), 2))
print("Loss avg R:R:", round(df.loc[df['is_loss'], 'rr_ratio'].mean(), 2))
print("Win avg R:R:", round(df.loc[df['is_win'], 'rr_ratio'].mean(), 2))

print("\n=== DAYS TO LOSS (SPEED OF SL HITS) ===")
print(losses['days_to_outcome'].describe())

print("\n=== LOSS TRADES: HIGH R:R (>1.5) that still lost ===")
# These are structural errors - high R:R setups that shouldn't have lost
high_rr_loss = df[(df['is_loss']) & (df['rr_ratio'] > 1.5)]
print(f"Count: {len(high_rr_loss)}")
print(f"Avg score: {high_rr_loss['composite_score'].mean():.1f}")
print(f"Avg SL distance: {high_rr_loss['sl_distance_pct'].mean():.2f}%")

print("\n=== LOSS TRADES: LOW R:R (<1.0) bad setup trades ===")
low_rr_loss = df[(df['is_loss']) & (df['rr_ratio'] < 1.0)]
print(f"Count: {len(low_rr_loss)}")
print(f"Avg score: {low_rr_loss['composite_score'].mean():.1f}")

print("\n=== SECTOR BREAKDOWN OF LOSSES ===")
sector_loss = losses.groupby('sector').agg(
    count=('is_loss', 'sum'),
    avg_score=('composite_score', 'mean'),
    avg_days=('days_to_outcome', 'mean')
).sort_values('count', ascending=False).head(10)
print(sector_loss.to_string())

print("\n=== MARKET CAP TIER LOSS RATES ===")
all_res = all_res.merge(df[['symbol','signal_date','sl_distance_pct','t1_upside_pct','rr_ratio']], on=['symbol','signal_date'], how='left')
for tier in ['large', 'mid', 'small']:
    sub = all_res[all_res['market_cap_tier'] == tier]
    if len(sub) > 0:
        loss_r = len(sub[sub['is_loss']]) / len(sub) * 100
        print(f"  {tier}: {len(sub)} trades, loss={loss_r:.1f}%")

print("\n=== SL DISTANCE BUCKETS vs LOSS RATE ===")
all_res['sl_bucket'] = pd.cut(
    all_res['sl_distance_pct'],
    bins=[0, 2, 3, 4, 5, 6, 8, 100],
    labels=['<2%', '2-3%', '3-4%', '4-5%', '5-6%', '6-8%', '>8%']
)
for bucket in ['<2%', '2-3%', '3-4%', '4-5%', '5-6%', '6-8%', '>8%']:
    sub = all_res[all_res['sl_bucket'] == bucket]
    if len(sub) > 0:
        loss_r = len(sub[sub['is_loss']]) / len(sub) * 100
        win_r = len(sub[sub['is_win']]) / len(sub) * 100
        print(f"  {bucket}: {len(sub)} trades, loss={loss_r:.1f}%, win={win_r:.1f}%")

print("\n=== SPEED OF LOSS (EARLY vs LATE LOSSES) ===")
early_loss = losses[losses['days_to_outcome'] <= 3]
late_loss = losses[losses['days_to_outcome'] > 3]
print(f"Early losses (<=3 days): {len(early_loss)} ({len(early_loss)/len(losses)*100:.1f}%)")
print(f"  Avg score: {early_loss['composite_score'].mean():.1f}")
print(f"  Avg SL distance: {early_loss['sl_distance_pct'].mean():.2f}%")
print(f"Late losses (>3 days): {len(late_loss)} ({len(late_loss)/len(losses)*100:.1f}%)")
print(f"  Avg score: {late_loss['composite_score'].mean():.1f}")
print(f"  Avg SL distance: {late_loss['sl_distance_pct'].mean():.2f}%")

print("\n=== HYPOTHETICAL: WHAT IF WE REQUIRED SCORE >= 62 ===")
filtered = all_res[all_res['composite_score'] >= 62]
total_f = len(filtered)
loss_f = len(filtered[filtered['is_loss']])
win_f = len(filtered[filtered['is_win']])
print(f"Trades: {total_f}, Losses: {loss_f} ({loss_f/total_f*100:.1f}%), Wins: {win_f} ({win_f/total_f*100:.1f}%)")

print("\n=== HYPOTHETICAL: WHAT IF WE REQUIRED SCORE >= 63 ===")
filtered = all_res[all_res['composite_score'] >= 63]
total_f = len(filtered)
loss_f = len(filtered[filtered['is_loss']])
win_f = len(filtered[filtered['is_win']])
print(f"Trades: {total_f}, Losses: {loss_f} ({loss_f/total_f*100:.1f}%), Wins: {win_f} ({win_f/total_f*100:.1f}%)")

print("\n=== HYPOTHETICAL: WHAT IF WE REQUIRED SCORE >= 65 ===")
filtered = all_res[all_res['composite_score'] >= 65]
total_f = len(filtered)
loss_f = len(filtered[filtered['is_loss']])
win_f = len(filtered[filtered['is_win']])
print(f"Trades: {total_f}, Losses: {loss_f} ({loss_f/total_f*100:.1f}%), Wins: {win_f} ({win_f/total_f*100:.1f}%)")

print("\n=== HYPOTHETICAL: WHAT IF WE REQUIRED R:R >= 1.5 ===")
filtered = all_res[all_res['rr_ratio'] >= 1.5]
total_f = len(filtered)
loss_f = len(filtered[filtered['is_loss']])
win_f = len(filtered[filtered['is_win']])
print(f"Trades: {total_f}, Losses: {loss_f} ({loss_f/total_f*100:.1f}%), Wins: {win_f} ({win_f/total_f*100:.1f}%)")

print("\n=== HYPOTHETICAL: WHAT IF WE REQUIRED R:R >= 2.0 ===")
filtered = all_res[all_res['rr_ratio'] >= 2.0]
total_f = len(filtered)
loss_f = len(filtered[filtered['is_loss']])
win_f = len(filtered[filtered['is_win']])
print(f"Trades: {total_f}, Losses: {loss_f} ({loss_f/total_f*100:.1f}%), Wins: {win_f} ({win_f/total_f*100:.1f}%)")

conn.close()
print("\nDone.")
