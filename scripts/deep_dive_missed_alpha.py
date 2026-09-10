import sys
import io
from pathlib import Path
import pandas as pd
import numpy as np
from sqlalchemy import text

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from db.database import get_session
from core.missed_signals import (
    scan_missed_opportunities,
    evaluate_missed_alpha_audit_accuracy,
    log_daily_missed_alpha_audit
)

session = get_session()

print("=" * 80)
print("🔍 COMPREHENSIVE MISSED ALPHA & FALSE NEGATIVE EMPIRICAL SURVEILLANCE REPORT")
print("=" * 80)

# 1. Historical Audit Log Analysis
eval_60d = evaluate_missed_alpha_audit_accuracy(session, days=60)
print("\n--- 1. HISTORICAL 60-DAY SURVEILLANCE AUDIT STATS ---")
print(f"Total High-Velocity Movers Tracked: {eval_60d.get('total_movers', 0)}")
print(f"Successfully Caught by BUY Engine:  {eval_60d.get('total_caught', 0)} ({eval_60d.get('capture_rate_pct', 0.0)}% Capture Rate)")
print(f"False Negatives (Missed on WATCH):  {eval_60d.get('total_missed', 0)} ({eval_60d.get('false_negative_rate_pct', 0.0)}% FN Rate)")
print(f"Average Missed Gain per Runner:     +{eval_60d.get('avg_missed_gain_pct', 0.0)}%")
print(f"Cumulative Uncaptured Alpha:        +{eval_60d.get('total_missed_alpha_pct', 0.0)}%")

print("\nHistorical Bottleneck Distribution in Audit Log:")
for btn, data in eval_60d.get('bottleneck_distribution', {}).items():
    print(f"  • {btn:<30} : {data['count']:>3} movers ({data['pct_of_missed']:>5.1f}%) | Avg Gain: +{data['avg_gain']:.2f}%")

print("\nHistorical Sector Vulnerability in Audit Log:")
for sec, cnt in sorted(eval_60d.get('sector_distribution', {}).items(), key=lambda x: x[1], reverse=True)[:8]:
    print(f"  • {sec:<30} : {cnt:>3} missed movers")

print("\nBuilt-in Quant Engine Insights:")
for ins in eval_60d.get('quant_insights', []):
    print(f"  {ins}")

# 2. Multi-Timeframe Velocity Analysis (Live Data Scan)
print("\n" + "=" * 80)
print("--- 2. MULTI-TIMEFRAME ALPHA CAPTURE MATRIX (LIVE UNIVERSE) ---")
print("=" * 80)

windows = [
    (1, 2.5, "1-Day Micro Surge"),
    (3, 3.5, "3-Day Fast Swing"),
    (5, 4.0, "5-Day Swing Trend"),
    (10, 6.0, "10-Day Medium Expansion"),
    (20, 8.0, "20-Day Position Run")
]

results = []
for lb, min_g, label in windows:
    scan = scan_missed_opportunities(session, lookback_days=lb, min_gain_pct=min_g)
    sm = scan['summary']
    results.append({
        "Window": label,
        "Lookback": f"{lb}d",
        "Hurdle": f"+{min_g}%",
        "Total Movers": sm['total_movers_detected'],
        "Caught (BUY)": sm['caught_buyers'],
        "Capture Rate": f"{sm['capture_rate_pct']}%",
        "Missed": sm['missed_movers_count'],
        "Avg Missed Gain": f"+{sm['avg_missed_gain_pct']:.2f}%",
        "Top Bottleneck": sm['top_bottleneck_factor']
    })

df_res = pd.DataFrame(results)
print(df_res.to_string(index=False))

# 3. Deep Dive into 5-Day and 10-Day Missed Movers
print("\n" + "=" * 80)
print("--- 3. DEEP DIVE: 5-DAY UNCAUGHT MOVERS (LOOKBACK=5, GAIN>=+4.0%) ---")
print("=" * 80)

scan_5d = scan_missed_opportunities(session, lookback_days=5, min_gain_pct=4.0)
missed_5d = pd.DataFrame(scan_5d.get('missed_movers', []))

if not missed_5d.empty:
    print(f"Total 5-day uncaught movers: {len(missed_5d)}")
    print(f"Gain range: +{missed_5d['gain_pct'].min():.2f}% to +{missed_5d['gain_pct'].max():.2f}% (Mean: +{missed_5d['gain_pct'].mean():.2f}%, Median: +{missed_5d['gain_pct'].median():.2f}%)")
    
    print("\nBottleneck Breakdown:")
    print(missed_5d['bottleneck'].value_counts().to_string())

    print("\nMarket Cap Tier Breakdown:")
    print(missed_5d['tier'].value_counts().to_string())

    print("\nSector Breakdown:")
    print(missed_5d['sector'].value_counts().to_string())

    print("\nPre-Run Technical & Score Characteristics (Averages):")
    print(f"  • Composite Score : {missed_5d['start_score'].mean():.1f} / 100 (Min: {missed_5d['start_score'].min():.1f}, Max: {missed_5d['start_score'].max():.1f})")
    print(f"  • RSI (14)        : {missed_5d['rsi'].mean():.1f} (Sluggish/Neutral band)")
    print(f"  • ADX             : {missed_5d['adx'].mean():.1f} (Low trend strength prior to expansion)")
    print(f"  • Volume Ratio    : {missed_5d['vol_ratio'].mean():.2f}x (Relative to 20-day volume)")

    print("\n--- TOP 15 LARGEST 5-DAY UNCAUGHT RUNNERS ---")
    top_missed = missed_5d.sort_values('gain_pct', ascending=False).head(15)
    for idx, r in top_missed.iterrows():
        print(f"• {r['symbol']:<12} ({r.get('name',''):<25}) | Gain: +{r['gain_pct']:>5.2f}% (₹{r['start_price']:>7.2f} -> ₹{r['end_price']:>7.2f})")
        print(f"  Tier: {r['tier']:<6} | Sector: {r['sector']}")
        print(f"  Start: Score={r['start_score']:.1f}, Signal={r['start_signal']}, RSI={r['rsi']:.1f}, ADX={r['adx']:.1f}, VolRatio={r['vol_ratio']:.2f}x")
        print(f"  Bottleneck: {r['bottleneck']}")
        print(f"  Diagnosis:  {r['diagnosis']}")
        print(f"  Catalyst:   {r['pattern_catalyst']}")
        print(f"  Takeaway:   {r['actionable_takeaway']}\n")

# 4. 10-Day Horizon Analysis
print("\n" + "=" * 80)
print("--- 4. DEEP DIVE: 10-DAY UNCAUGHT MOVERS (LOOKBACK=10, GAIN>=+6.0%) ---")
print("=" * 80)

scan_10d = scan_missed_opportunities(session, lookback_days=10, min_gain_pct=6.0)
missed_10d = pd.DataFrame(scan_10d.get('missed_movers', []))
if not missed_10d.empty:
    print(f"Total 10-day uncaught movers: {len(missed_10d)}")
    print(f"Top 10-day uncaught movers:")
    top_10 = missed_10d.sort_values('gain_pct', ascending=False).head(10)
    for idx, r in top_10.iterrows():
        print(f"• {r['symbol']:<12} | Gain: +{r['gain_pct']:>5.2f}% | Score: {r['start_score']:.1f} | RSI: {r['rsi']:.1f} | Bottleneck: {r['bottleneck']}")

# 5. Composite Score Distribution of Missed Movers
print("\n" + "=" * 80)
print("--- 5. SCORE THRESHOLD CLUSTERING (WHERE DO MISSED MOVERS SIT?) ---")
print("=" * 80)
if not missed_5d.empty:
    bins = [0, 45, 50, 55, 60, 65, 70, 100]
    labels = ["<45 (Weak)", "45-49 (Sub-par)", "50-54 (Neutral WATCH)", "55-59 (Near-Hurdle WATCH)", "60-64 (BUY Boundary)", "65-69 (Solid BUY)", "70+ (Strong BUY)"]
    missed_5d['score_bucket'] = pd.cut(missed_5d['start_score'], bins=bins, labels=labels, right=False)
    print("5-Day Missed Movers by Pre-Move Composite Score Bucket:")
    print(missed_5d['score_bucket'].value_counts(sort=False).to_string())

print("\nSurveillance Deep Dive completed successfully.")
