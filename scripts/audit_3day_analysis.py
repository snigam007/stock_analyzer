import sys
import io
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Ensure UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import pandas as pd
import numpy as np
from sqlalchemy import text
from db.database import get_global_engine, get_session

engine = get_global_engine()
session = get_session(engine)

# Load all signals with their indicators, scores, sector, tier, and next-day price evolution
query = """
    SELECT 
        s.date as signal_date,
        s.symbol,
        stk.name,
        stk.sector,
        stk.market_cap_tier as tier,
        s.signal,
        s.current_price as entry_price,
        s.target_price_1,
        s.target_price_2,
        s.target_price_3,
        s.stop_loss,
        cs.composite_score,
        ti.rsi_14,
        ti.adx,
        ti.volume_ratio,
        ti.ema_50,
        ti.ema_200,
        ti.trend_direction,
        ti.trend_strength
    FROM signals s
    JOIN stocks stk ON s.symbol = stk.symbol
    LEFT JOIN composite_scores cs ON s.symbol = cs.symbol AND s.date = cs.date
    LEFT JOIN technical_indicators ti ON s.symbol = ti.symbol AND s.date = ti.date
    WHERE s.signal IN ('BUY', 'SELL')
    ORDER BY s.date, s.symbol
"""
df_sig = pd.read_sql(query, session.connection())
print(f"Total historical BUY/SELL signals loaded: {len(df_sig)}")

# Pull all daily prices for evaluation
p_query = """
    SELECT symbol, date, open, high, low, close, volume, daily_return
    FROM daily_prices
    WHERE date >= '2026-08-25'
    ORDER BY symbol, date
"""
df_prices = pd.read_sql(p_query, session.connection())

# Forward price matching
results = []
for _, row in df_sig.iterrows():
    sym = row['symbol']
    s_date = row['signal_date']
    sig = row['signal']
    entry = float(row['entry_price'])
    t1 = float(row['target_price_1']) if row['target_price_1'] else None
    t2 = float(row['target_price_2']) if row['target_price_2'] else None
    t3 = float(row['target_price_3']) if row['target_price_3'] else None
    sl = float(row['stop_loss']) if row['stop_loss'] else None
    
    # Forward days strictly after signal date
    fwd = df_prices[(df_prices['symbol'] == sym) & (df_prices['date'] > s_date)].sort_values('date')
    if fwd.empty:
        status = "PENDING (Latest Session)"
        max_gain = 0.0
        max_loss = 0.0
        final_return = 0.0
        days = 0
    else:
        days = len(fwd)
        highs = fwd['high'].astype(float).values
        lows = fwd['low'].astype(float).values
        closes = fwd['close'].astype(float).values
        
        if sig == 'BUY':
            max_gain = (np.max(highs) - entry) / entry * 100.0
            max_loss = (np.min(lows) - entry) / entry * 100.0
            final_return = (closes[-1] - entry) / entry * 100.0
            
            hit_t1 = (np.max(highs) >= t1) if t1 else False
            hit_t2 = (np.max(highs) >= t2) if t2 else False
            hit_t3 = (np.max(highs) >= t3) if t3 else False
            hit_sl = (np.min(lows) <= sl) if sl else False
        else: # SELL
            max_gain = (entry - np.min(lows)) / entry * 100.0
            max_loss = (entry - np.max(highs)) / entry * 100.0
            final_return = (entry - closes[-1]) / entry * 100.0
            
            hit_t1 = (np.min(lows) <= t1) if t1 else False
            hit_t2 = (np.min(lows) <= t2) if t2 else False
            hit_t3 = (np.min(lows) <= t3) if t3 else False
            hit_sl = (np.max(highs) >= sl) if sl else False
            
        if hit_t3:
            status = "T3 HIT (+15%+)"
        elif hit_t2:
            status = "T2 HIT (+8%+)"
        elif hit_t1:
            status = "T1 HIT (+4%+)"
        elif hit_sl and not hit_t1:
            status = "STOP LOSS TRIGGERED"
        elif final_return > 0:
            status = "IN PLAY (PROFITABLE)"
        else:
            status = "IN PLAY (DRAWDOWNS)"
            
    res = dict(row)
    res.update({
        'days_fwd': days,
        'status': status,
        'max_favorable_gain_pct': round(max_gain, 2),
        'max_adverse_loss_pct': round(max_loss, 2),
        'realized_return_pct': round(final_return, 2),
        'is_winner': 1 if ('HIT' in status or final_return > 0) else 0,
        'is_t1_hit': 1 if 'HIT' in status else 0,
        'is_sl_hit': 1 if 'STOP LOSS' in status else 0
    })
    results.append(res)

df_res = pd.DataFrame(results)

# ── 1. Global Performance Overview ─────────────────────────────────────────────
df_eval = df_res[df_res['days_fwd'] > 0]
print("\n================================================================================")
print("📊 3-DAY EMPIRICAL SIGNAL AUDIT & ACCURACY PERFORMANCE ANALYSIS")
print("================================================================================")
print(f"Total Tracked BUY/SELL Signals: {len(df_res)}")
print(f"Completed Forward Evaluations (1 to 2 forward sessions): {len(df_eval)}")
print(f"Pending Latest Session Signals (2026-08-27): {len(df_res[df_res['days_fwd'] == 0])}")

print("\n--- SIGNAL DISTRIBUTION ACROSS SESSIONS ---")
print(df_res.groupby(['signal_date', 'signal'])['symbol'].count())

print("\n--- OUTCOME STATUS BREAKDOWN ---")
print(df_eval['status'].value_counts())

print("\n--- KEY PERFORMANCE BENCHMARKS ---")
print(f"• Overall Win Rate (Target Hit / Profitable Close): {df_eval['is_winner'].mean()*100:.1f}%")
print(f"• Target 1 Hit Rate (+3.5% to +5.0%): {df_eval['is_t1_hit'].mean()*100:.1f}%")
print(f"• Stop Loss Hit Rate: {df_eval['is_sl_hit'].mean()*100:.1f}%")
print(f"• Average Max Favorable Excursion (Peak Gain MFE): +{df_eval['max_favorable_gain_pct'].mean():.2f}%")
print(f"• Average Max Adverse Excursion (Max Drawdown MAE): {df_eval['max_adverse_loss_pct'].mean():.2f}%")
print(f"• Profit Factor (Avg Gain / Avg Loss): {abs(df_eval[df_eval['max_favorable_gain_pct'] > 0]['max_favorable_gain_pct'].mean() / df_eval[df_eval['max_adverse_loss_pct'] < 0]['max_adverse_loss_pct'].mean()):.2f}")

# ── 2. Performance Segmented by Composite Score Tier ───────────────────────────
print("\n--- 1. PERFORMANCE BY COMPOSITE SCORE CONVICTION ---")
df_eval['score_tier'] = pd.cut(
    df_eval['composite_score'],
    bins=[0, 60, 70, 80, 100],
    labels=['Tier 4 (<60 Moderate)', 'Tier 3 (60-70 Good)', 'Tier 2 (70-80 High)', 'Tier 1 (80+ Elite)']
)
score_table = df_eval.groupby('score_tier', observed=False).agg(
    Signals=('symbol', 'count'),
    Win_Rate=('is_winner', lambda x: f"{x.mean()*100:.1f}%"),
    T1_Hit_Rate=('is_t1_hit', lambda x: f"{x.mean()*100:.1f}%"),
    SL_Rate=('is_sl_hit', lambda x: f"{x.mean()*100:.1f}%"),
    Avg_Peak_Gain=('max_favorable_gain_pct', lambda x: f"+{x.mean():.2f}%"),
    Avg_Drawdown=('max_adverse_loss_pct', lambda x: f"{x.mean():.2f}%")
)
print(score_table)

# ── 3. Performance by Market Cap Tier ──────────────────────────────────────────
print("\n--- 2. PERFORMANCE BY MARKET CAP TIER ---")
tier_table = df_eval.groupby('tier').agg(
    Signals=('symbol', 'count'),
    Win_Rate=('is_winner', lambda x: f"{x.mean()*100:.1f}%"),
    T1_Hit_Rate=('is_t1_hit', lambda x: f"{x.mean()*100:.1f}%"),
    Avg_Peak_Gain=('max_favorable_gain_pct', lambda x: f"+{x.mean():.2f}%"),
    Avg_Drawdown=('max_adverse_loss_pct', lambda x: f"{x.mean():.2f}%")
)
print(tier_table)

# ── 4. Performance by Sector ───────────────────────────────────────────────────
print("\n--- 3. TOP SECTORS BY WIN RATE & ALPHA GENERATION ---")
sec_table = df_eval.groupby('sector').agg(
    Signals=('symbol', 'count'),
    Win_Rate_Pct=('is_winner', lambda x: round(x.mean()*100, 1)),
    T1_Hit_Rate_Pct=('is_t1_hit', lambda x: round(x.mean()*100, 1)),
    Avg_Peak_Gain_Pct=('max_favorable_gain_pct', lambda x: round(x.mean(), 2)),
    Avg_Return_Pct=('realized_return_pct', lambda x: round(x.mean(), 2))
).sort_values(['Signals', 'Win_Rate_Pct'], ascending=[False, False])
print(sec_table.head(12))

# ── 5. Technical Confluence Filters Impact ──────────────────────────────────────
print("\n--- 4. CONFLUENCE FILTER IMPACT ON ACCURACY ---")

# Filter A: Volume Breakout (Volume Ratio >= 1.2x)
df_eval['vol_confluence'] = df_eval['volume_ratio'] >= 1.2
vol_perf = df_eval.groupby('vol_confluence').agg(
    Signals=('symbol', 'count'),
    Win_Rate=('is_winner', lambda x: f"{x.mean()*100:.1f}%"),
    T1_Hit_Rate=('is_t1_hit', lambda x: f"{x.mean()*100:.1f}%"),
    Avg_Peak_Gain=('max_favorable_gain_pct', lambda x: f"+{x.mean():.2f}%")
)
print("Volume Ratio >= 1.2x Confluence:")
print(vol_perf)

# Filter B: Trend Strength (ADX >= 25)
df_eval['strong_trend'] = df_eval['adx'] >= 25.0
adx_perf = df_eval.groupby('strong_trend').agg(
    Signals=('symbol', 'count'),
    Win_Rate=('is_winner', lambda x: f"{x.mean()*100:.1f}%"),
    T1_Hit_Rate=('is_t1_hit', lambda x: f"{x.mean()*100:.1f}%"),
    Avg_Peak_Gain=('max_favorable_gain_pct', lambda x: f"+{x.mean():.2f}%")
)
print("\nADX >= 25.0 Trend Strength Confluence:")
print(adx_perf)

# Filter C: 50 EMA Alignment
df_eval['ema_50_aligned'] = np.where(
    df_eval['signal'] == 'BUY',
    df_eval['entry_price'] > df_eval['ema_50'],
    df_eval['entry_price'] < df_eval['ema_50']
)
ema_perf = df_eval.groupby('ema_50_aligned').agg(
    Signals=('symbol', 'count'),
    Win_Rate=('is_winner', lambda x: f"{x.mean()*100:.1f}%"),
    T1_Hit_Rate=('is_t1_hit', lambda x: f"{x.mean()*100:.1f}%"),
    Avg_Peak_Gain=('max_favorable_gain_pct', lambda x: f"+{x.mean():.2f}%")
)
print("\n50 EMA Alignment Confluence:")
print(ema_perf)

# ── 6. Top Alpha Performers ────────────────────────────────────────────────────
print("\n--- 5. TOP 10 ALPHA OUTPERFORMERS ---")
top10 = df_eval.sort_values('max_favorable_gain_pct', ascending=False).head(10)
for idx, (_, w) in enumerate(top10.iterrows(), start=1):
    print(f"{idx:2d}. {w['symbol']:<10} | {w['signal']:<4} | Date: {w['signal_date']} | Score: {w['composite_score']:3.0f} | MFE: +{w['max_favorable_gain_pct']:>5.2f}% | Sector: {w['sector']} | Status: {w['status']}")

# ── 7. Worst Drawdowns Autopsy ─────────────────────────────────────────────────
print("\n--- 6. DRAWDOWN AUTOPSY: STOPPED OUT TRADES ---")
sl_trades = df_eval[df_eval['is_sl_hit'] == 1].sort_values('max_adverse_loss_pct', ascending=True).head(8)
for idx, (_, l) in enumerate(sl_trades.iterrows(), start=1):
    print(f"{idx:2d}. {l['symbol']:<10} | {l['signal']:<4} | Date: {l['signal_date']} | Score: {l['composite_score']:3.0f} | MAE: {l['max_adverse_loss_pct']:>5.2f}% | Sector: {l['sector']} | RSI: {l['rsi_14']:.1f} | ADX: {l['adx']:.1f}")

session.close()
