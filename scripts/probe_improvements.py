import sqlite3
import pandas as pd
import numpy as np

conn = sqlite3.connect('data/stock_analyzer.db')
q = """
SELECT sal.id, sal.status, sal.composite_score, sal.realized_gain_pct, sal.risk_level,
       sal.signal, sal.entry_price, sal.stop_loss, sal.target_1, sal.target_2, sal.target_3,
       sal.signal_date, sal.exit_date, sal.days_to_outcome, sal.symbol,
       sal.max_price_reached, sal.min_price_reached, sal.trailing_stop,
       sal.unrealized_gain_pct,
       stk.market_cap_tier, stk.sector
FROM signal_audit_log sal
LEFT JOIN stocks stk ON sal.symbol = stk.symbol
WHERE sal.asset_type = 'STOCK' AND sal.status != 'PENDING'
"""
df = pd.read_sql(q, conn)
conn.close()

df['is_loss'] = (df['status'] == 'SL_HIT') & (df['realized_gain_pct'].fillna(0) <= 0)
df['is_win'] = df['status'].isin(['T1_HIT', 'T2_HIT', 'T3_HIT', 'TRAILING_SL_HIT'])
df['gain_pct'] = df['realized_gain_pct'].fillna(0)
df['signal_date_dt'] = pd.to_datetime(df['signal_date'], errors='coerce')
df['dow'] = df['signal_date_dt'].dt.day_of_week

print("=== 1. BAD SECTORS ANALYSIS ===")
bad_sectors = ['Banking & Finance', 'Capital Goods & Engineering', 'Metals & Mining']
sub_bad = df[df['sector'].isin(bad_sectors)]
print(f"Total in bad sectors: {len(sub_bad)}, Losses: {sub_bad['is_loss'].sum()} ({sub_bad['is_loss'].mean()*100:.1f}%), Avg gain: {sub_bad['gain_pct'].mean():.2f}%")
for thr in [57, 58, 59, 60, 61, 62, 63]:
    kept = sub_bad[sub_bad['composite_score'] >= thr]
    print(f"  Score >= {thr}: {len(kept)} trades, Losses: {kept['is_loss'].sum()} ({kept['is_loss'].mean()*100:.1f}%), Avg gain: {kept['gain_pct'].mean():.2f}%")

print("\n=== 2. FRIDAY FILTER ANALYSIS ===")
fri = df[df['dow'] == 4]
non_fri = df[df['dow'] != 4]
print(f"Friday trades: {len(fri)}, Losses: {fri['is_loss'].sum()} ({fri['is_loss'].mean()*100:.1f}%), Avg gain: {fri['gain_pct'].mean():.2f}%")
print(f"Non-Friday trades: {len(non_fri)}, Losses: {non_fri['is_loss'].sum()} ({non_fri['is_loss'].mean()*100:.1f}%), Avg gain: {non_fri['gain_pct'].mean():.2f}%")

print("\n=== 3. MAX HOLD DURATION ANALYSIS ===")
for max_days in [5, 7, 10, 12, 15]:
    long_trades = df[df['days_to_outcome'] > max_days]
    print(f"Days > {max_days}: {len(long_trades)} trades, Losses: {long_trades['is_loss'].sum()} ({long_trades['is_loss'].mean()*100:.1f}%), Avg gain: {long_trades['gain_pct'].mean():.2f}%")

print("\n=== 4. TARGET REACH ANALYSIS (T2 / T3) ===")
# max_price_reached vs entry_price
df['max_gain_reached_pct'] = ((df['max_price_reached'] - df['entry_price']) / df['entry_price'] * 100)
df['t2_upside_pct'] = ((df['target_2'] - df['entry_price']) / df['entry_price'] * 100)
for t2_thresh in [4.5, 5.0, 5.5, 6.0, 7.0, 7.5]:
    hit_count = (df['max_gain_reached_pct'] >= t2_thresh).sum()
    print(f"Peak gain >= {t2_thresh}%: {hit_count}/{len(df)} ({hit_count/len(df)*100:.1f}%)")

print("\n=== 5. TRAILING SL ANALYSIS ===")
tsl = df[df['status'] == 'TRAILING_SL_HIT']
print(f"TSL count: {len(tsl)}, Avg gain: {tsl['gain_pct'].mean():.2f}%, Median gain: {tsl['gain_pct'].median():.2f}%")
print(f"TSL with gain < 1.5%: {(tsl['gain_pct'] < 1.5).sum()} ({((tsl['gain_pct'] < 1.5).mean()*100):.1f}%)")
print(f"TSL with days <= 2: {(tsl['days_to_outcome'] <= 2).sum()} ({((tsl['days_to_outcome'] <= 2).mean()*100):.1f}%)")
print(f"TSL that reached T1: {(tsl['max_price_reached'] >= tsl['target_1']).sum()} ({((tsl['max_price_reached'] >= tsl['target_1']).mean()*100):.1f}%)")

print("\n=== 6. RISK LEVEL ANALYSIS ===")
for rl in ['SAFE', 'MODERATE', 'RISKY']:
    sub_rl = df[df['risk_level'] == rl]
    gain_s = sub_rl.loc[sub_rl['gain_pct'] > 0, 'gain_pct'].sum()
    loss_s = sub_rl.loc[sub_rl['gain_pct'] < 0, 'gain_pct'].abs().sum()
    pf = gain_s / max(0.01, loss_s)
    print(f"Risk {rl}: {len(sub_rl)} trades, WR: {sub_rl['is_win'].mean()*100:.1f}%, LR: {sub_rl['is_loss'].mean()*100:.1f}%, PF: {pf:.2f}x, AvgGain: {sub_rl['gain_pct'].mean():.2f}%")
