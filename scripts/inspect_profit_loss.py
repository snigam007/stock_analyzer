import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import get_global_engine, get_session
from sqlalchemy import text
engine = get_global_engine()
import pandas as pd
import numpy as np

s = get_session(engine)
df = pd.read_sql("SELECT * FROM signal_audit_log WHERE COALESCE(asset_type, 'STOCK') = 'STOCK'", s.bind)
print(f"Total STOCK rows: {len(df)}")
print("\nStatus counts:\n", df['status'].value_counts())

resolved = df[df['status'] != 'PENDING']
print(f"\nResolved count: {len(resolved)}")
print("\nSignal breakdown in resolved:\n", resolved['signal'].value_counts())
print("\nSignal date range:", df['signal_date'].min(), "to", df['signal_date'].max())

# Gains and losses
gains = resolved[resolved['realized_gain_pct'] > 0]['realized_gain_pct']
losses = resolved[resolved['realized_gain_pct'] < 0]['realized_gain_pct']

print(f"\nWinners count: {len(gains)} | Avg Gain: +{gains.mean():.2f}% | Max Gain: +{gains.max():.2f}% | Total Gross Gain: +{gains.sum():.2f}%")
print(f"Losers count: {len(losses)} | Avg Loss: {losses.mean():.2f}% | Max Loss: {losses.min():.2f}% | Total Gross Loss: {losses.sum():.2f}%")
if len(losses) > 0 and abs(losses.sum()) > 0:
    pf = gains.sum() / abs(losses.sum())
    print(f"Profit Factor: {pf:.2f}x")

# Target distance vs SL distance at inception
df['t1_dist'] = np.where(df['signal']=='BUY', (df['target_1'] - df['entry_price']) / df['entry_price'] * 100, (df['entry_price'] - df['target_1']) / df['entry_price'] * 100)
df['sl_dist'] = np.where(df['signal']=='BUY', (df['entry_price'] - df['stop_loss']) / df['entry_price'] * 100, (df['stop_loss'] - df['entry_price']) / df['entry_price'] * 100)

print(f"\nAt Inception Avg T1 Distance: +{df['t1_dist'].mean():.2f}%")
print(f"At Inception Avg SL Distance: -{df['sl_dist'].mean():.2f}%")
print(f"Reward/Risk Ratio at Inception: {df['t1_dist'].mean() / df['sl_dist'].mean():.2f}x")

# Breakdown of resolved statuses
print("\nResolved Status Detail:")
for st in resolved['status'].unique():
    sub = resolved[resolved['status'] == st]
    print(f"  {st:20s}: count={len(sub):4d} ({len(sub)/len(resolved)*100:.1f}%) | avg_pnl={sub['realized_gain_pct'].mean():+.2f}%")

# In-play positions
pending = df[df['status'] == 'PENDING']
print(f"\nIn-Play Positions ({len(pending)}):")
green = pending[pending['unrealized_gain_pct'] > 0]
red = pending[pending['unrealized_gain_pct'] <= 0]
print(f"  Green ({len(green)} / {len(pending)} = {len(green)/len(pending)*100:.1f}%): avg={green['unrealized_gain_pct'].mean():+.2f}%")
print(f"  Red   ({len(red)} / {len(pending)} = {len(red)/len(pending)*100:.1f}%): avg={red['unrealized_gain_pct'].mean():+.2f}%")

# Market performance during signal dates
nifty = pd.read_sql("SELECT date, close FROM index_prices WHERE symbol='^NSEI' ORDER BY date DESC LIMIT 20", s.bind)
print("\nRecent NIFTY prices:")
print(nifty)

# Signal dates distribution
print("\nSignals generated per date:")
print(df['signal_date'].value_counts().sort_index())

# Check BUY vs SELL performance
print("\nPerformance by Signal Type (BUY vs SELL):")
for sig in ['BUY', 'SELL']:
    sig_res = resolved[resolved['signal'] == sig]
    sig_wins = sig_res[sig_res['realized_gain_pct'] > 0]
    sig_loss = sig_res[sig_res['realized_gain_pct'] < 0]
    print(f"  {sig:4s}: Total={len(sig_res)}, Wins={len(sig_wins)} ({len(sig_wins)/max(1, len(sig_res))*100:.1f}%), Avg Win=+{sig_wins['realized_gain_pct'].mean():.2f}%, Avg Loss={sig_loss['realized_gain_pct'].mean():.2f}%, Gross Gain={sig_wins['realized_gain_pct'].sum():.1f}%, Gross Loss={sig_loss['realized_gain_pct'].sum():.1f}%")

s.close()
