"""
Comprehensive improvement opportunity audit.
Analyses remaining alpha across: target accuracy, XIRR, sector timing, signal decay, 
volume profile quality, and portfolio-level correlation risk.
"""
import sqlite3
import pandas as pd
import numpy as np

conn = sqlite3.connect('data/stock_analyzer.db')

q = """
SELECT sal.status, sal.realized_gain_pct, sal.days_to_outcome,
       sal.signal, sal.composite_score, stk.market_cap_tier, stk.sector,
       sal.signal_date, sal.exit_date, sal.entry_price, sal.target_1, sal.target_2, sal.stop_loss,
       sal.symbol, sal.risk_level, sal.trailing_stop
FROM signal_audit_log sal
LEFT JOIN stocks stk ON sal.symbol = stk.symbol
WHERE sal.asset_type = 'STOCK' AND sal.status != 'PENDING'
"""
df = pd.read_sql(q, conn)
df['gain'] = df['realized_gain_pct'].fillna(0)
df['is_win'] = df['status'].isin(['T1_HIT','T2_HIT','T3_HIT','TRAILING_SL_HIT'])
df['is_loss'] = (df['status']=='SL_HIT') & (df['gain']<=0)
df['annualized_r'] = (df['gain']/100.0) * (365.0 / df['days_to_outcome'].clip(lower=1))
df['t1_upside'] = ((df['target_1'] - df['entry_price'])/df['entry_price']*100).abs()
df['sl_dist'] = ((df['entry_price'] - df['stop_loss'])/df['entry_price']*100).abs()

print("=" * 65)
print("A. HOLDING PERIOD & XIRR EFFICIENCY")
print("=" * 65)
print(f"Avg days per WIN: {df.loc[df['is_win'],'days_to_outcome'].mean():.1f}")
print(f"Avg days per LOSS: {df.loc[df['is_loss'],'days_to_outcome'].mean():.1f}")
print(f"Median days per WIN: {df.loc[df['is_win'],'days_to_outcome'].median():.0f}")
print(f"Avg annualized return (wins): {df.loc[df['is_win'],'annualized_r'].mean()*100:.1f}%")
print(f"Avg annualized return (losses): {df.loc[df['is_loss'],'annualized_r'].mean()*100:.1f}%")
print(f"Best XIRR bucket?")
# XIRR by holding period bucket
df['hold_bucket'] = pd.cut(df['days_to_outcome'], bins=[0,3,7,10,15,30], labels=['1-3d','4-7d','8-10d','11-15d','16-30d'])
for b in ['1-3d','4-7d','8-10d','11-15d','16-30d']:
    sub = df[df['hold_bucket']==b]
    if len(sub) > 5:
        ann = sub.loc[sub['is_win'],'annualized_r'].mean()*100
        loss_r = sub['is_loss'].sum()/len(sub)*100
        print(f"  {b}: {len(sub)} trades, win_ann={ann:.0f}%, loss_rate={loss_r:.1f}%")

print("\n" + "=" * 65)
print("B. TARGET ACCURACY: LEAVING MONEY ON TABLE")
print("=" * 65)
for s in ['T1_HIT','T2_HIT','T3_HIT','TRAILING_SL_HIT','SL_HIT']:
    sub = df[df['status']==s]
    if len(sub):
        print(f"  {s}: {len(sub)} ({len(sub)/len(df)*100:.1f}%), avg_gain={sub['gain'].mean():.2f}%, avg_days={sub['days_to_outcome'].mean():.1f}")

trail = df[df['status']=='TRAILING_SL_HIT'].copy()
trail['gain_vs_t1'] = trail['gain'] - trail['t1_upside']
print(f"\n  Trailing SL exits vs T1 upside:")
print(f"  Avg gain: {trail['gain'].mean():.2f}%")
print(f"  Avg T1 target upside: {trail['t1_upside'].mean():.2f}%")
print(f"  Money left on table (avg): {trail['gain_vs_t1'].mean():.2f}%")
short = trail[trail['gain_vs_t1'] < -1.0]
print(f"  Exited >1% before T1: {len(short)}/{len(trail)} ({len(short)/max(1,len(trail))*100:.1f}%)")

print("\n" + "=" * 65)
print("C. SIGNAL FRESHNESS DECAY: DO OLD SIGNALS UNDERPERFORM?")
print("=" * 65)
# Check if signal_date to analysis date lag matters
df['signal_date_dt'] = pd.to_datetime(df['signal_date'], errors='coerce')
df['dow'] = df['signal_date_dt'].dt.day_of_week  # 0=Monday
dow_labels = {0:'Mon',1:'Tue',2:'Wed',3:'Thu',4:'Fri'}
print("Win rate by signal day-of-week:")
for d, lbl in dow_labels.items():
    sub = df[df['dow']==d]
    if len(sub) > 5:
        wr = sub['is_win'].sum()/len(sub)*100
        avg_g = sub['gain'].mean()
        print(f"  {lbl}: {len(sub)} signals, win_rate={wr:.1f}%, avg_gain={avg_g:.2f}%")

print("\n" + "=" * 65)
print("D. SECTOR TIMING: WHICH SECTORS ARE STILL LEAKING ALPHA?")
print("=" * 65)
sect_perf = df.groupby('sector').agg(
    total=('gain','count'),
    wins=('is_win','sum'),
    losses=('is_loss','sum'),
    avg_gain=('gain','mean'),
    avg_annualized=('annualized_r','mean')
).sort_values('avg_annualized', ascending=True)
sect_perf['win_rate'] = sect_perf['wins']/sect_perf['total']*100
sect_perf['loss_rate'] = sect_perf['losses']/sect_perf['total']*100
sect_perf['avg_annualized_pct'] = sect_perf['avg_annualized']*100
print(sect_perf[['total','win_rate','loss_rate','avg_gain','avg_annualized_pct']].to_string())

print("\n" + "=" * 65)
print("E. COMPOSITE SCORE CALIBRATION: IS THE SCORE PREDICTIVE?")
print("=" * 65)
# How well does composite score predict gain? (IC)
resolved = df.dropna(subset=['composite_score','gain'])
corr = resolved['composite_score'].corr(resolved['gain'])
print(f"  Score vs Gain Pearson IC: {corr:.4f} (0=no predictive power, 1=perfect)")
# Score decile analysis
resolved['score_decile'] = pd.qcut(resolved['composite_score'], q=5, labels=['Q1(low)','Q2','Q3','Q4','Q5(high)'])
print("  Win rate by score quintile:")
for q in ['Q1(low)','Q2','Q3','Q4','Q5(high)']:
    sub = resolved[resolved['score_decile']==q]
    if len(sub):
        wr = sub['is_win'].sum()/len(sub)*100
        ag = sub['gain'].mean()
        print(f"    {q}: {len(sub)} trades, win_rate={wr:.1f}%, avg_gain={ag:.2f}%")

print("\n" + "=" * 65)
print("F. MULTI-STOCK CONCENTRATION / DUPLICATE SIGNAL RISK")
print("=" * 65)
# How many stocks get multiple signals? Repeated signals dilute diversification
symbol_counts = df.groupby('symbol')['status'].count()
print(f"  Unique stocks traded: {len(symbol_counts)}")
print(f"  Stocks with >3 signals: {(symbol_counts>3).sum()}")
print(f"  Stocks with >5 signals: {(symbol_counts>5).sum()}")
repeat_stocks = symbol_counts[symbol_counts>3].index.tolist()
if repeat_stocks:
    rep_df = df[df['symbol'].isin(repeat_stocks)]
    rep_wr = rep_df['is_win'].sum()/len(rep_df)*100
    all_wr = df['is_win'].sum()/len(df)*100
    print(f"  Repeat stock (>3 signals) win rate: {rep_wr:.1f}% vs overall {all_wr:.1f}%")

print("\n" + "=" * 65)
print("G. RISK_LEVEL CALIBRATION: IS RISKY ACTUALLY RISKY?")
print("=" * 65)
for rl in ['SAFE','MODERATE','RISKY']:
    sub = df[df['risk_level']==rl]
    if len(sub):
        wr = sub['is_win'].sum()/len(sub)*100
        lr = sub['is_loss'].sum()/len(sub)*100
        ann = sub.loc[sub['is_win'],'annualized_r'].mean()*100
        print(f"  {rl}: {len(sub)} trades, win={wr:.1f}%, loss={lr:.1f}%, win_ann_r={ann:.0f}%")

print("\n" + "=" * 65)
print("H. SIGNAL-DATE MOMENTUM CARRY: SAME WEEK SIGNALS BETTER?")
print("=" * 65)
# Check if signal that exits in <5 days has better annualized
fast = df[(df['is_win']) & (df['days_to_outcome']<=5)]
slow = df[(df['is_win']) & (df['days_to_outcome']>5)]
print(f"  Fast wins (<=5d): {len(fast)} trades, ann={fast['annualized_r'].mean()*100:.0f}% avg, gain={fast['gain'].mean():.2f}%")
print(f"  Slow wins (>5d): {len(slow)} trades, ann={slow['annualized_r'].mean()*100:.0f}% avg, gain={slow['gain'].mean():.2f}%")

# Check T2 + T3 hit rate
print(f"\n  T2 hit rate: {len(df[df['status']=='T2_HIT'])/len(df)*100:.1f}% of all resolved")
print(f"  T3 hit rate: {len(df[df['status']=='T3_HIT'])/len(df)*100:.1f}% of all resolved")
t2_gain = df.loc[df['status']=='T2_HIT','gain'].mean()
t3_gain = df.loc[df['status']=='T3_HIT','gain'].mean()
print(f"  T2 avg gain: {t2_gain:.2f}%")
print(f"  T3 avg gain: {t3_gain:.2f}%")

conn.close()
print("\nDone.")
