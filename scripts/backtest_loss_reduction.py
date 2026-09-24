"""
Deep Trailing Stop & SL Engineering Backtest
Tests 4 concrete hypotheses to reduce loss trades:
1. ATR-Volatility Adaptive SL (wider SL for high-vol, tighter for low-vol instruments)
2. Minimum R:R Enforcement Gate (minimum 1.5:1 R:R before logging signal)
3. Score Confidence Hybrid Gate (composite_score >= 62 OR SL distance in sweet spot 5-8%)
4. Large-Cap Tighter Entry Hurdle (large cap loss rate is 29.9% vs small=12% — needs special treatment)
"""
import sqlite3
import pandas as pd
import numpy as np

conn = sqlite3.connect('data/stock_analyzer.db')

# Pull all resolved STOCK trades
q = """
SELECT sal.id, sal.status, sal.composite_score, sal.realized_gain_pct, sal.risk_level,
       sal.signal, sal.entry_price, sal.stop_loss, sal.target_1, sal.target_2,
       sal.signal_date, sal.exit_date, sal.days_to_outcome, sal.symbol,
       sal.max_price_reached, sal.min_price_reached, sal.trailing_stop,
       stk.market_cap_tier, stk.sector
FROM signal_audit_log sal
LEFT JOIN stocks stk ON sal.symbol = stk.symbol
WHERE sal.asset_type = 'STOCK' AND sal.status != 'PENDING'
"""
df = pd.read_sql(q, conn)
conn.close()

df['is_loss'] = (df['status'] == 'SL_HIT') & (df['realized_gain_pct'].fillna(0) <= 0)
df['is_win'] = df['status'].isin(['T1_HIT', 'T2_HIT', 'T3_HIT', 'TRAILING_SL_HIT'])
df['sl_distance_pct'] = ((df['entry_price'] - df['stop_loss']) / df['entry_price'] * 100).abs()
df['t1_upside_pct'] = ((df['target_1'] - df['entry_price']) / df['entry_price'] * 100).abs()
df['rr_ratio'] = df['t1_upside_pct'] / df['sl_distance_pct'].replace(0, np.nan)
# Approx gain for wins (use realized_gain_pct)
df['gain_pct'] = df['realized_gain_pct'].fillna(0)

total = len(df)
base_losses = df['is_loss'].sum()
base_wins = df['is_win'].sum()
base_loss_pct = base_losses / total * 100
base_gain_sum = df.loc[df['gain_pct'] > 0, 'gain_pct'].sum()
base_loss_sum = df.loc[df['gain_pct'] < 0, 'gain_pct'].abs().sum()
base_pf = base_gain_sum / max(1, base_loss_sum)

print("=" * 65)
print("BASELINE")
print("=" * 65)
print(f"  Total trades: {total}, Losses: {base_losses} ({base_loss_pct:.1f}%), Wins: {base_wins} ({base_wins/total*100:.1f}%)")
print(f"  Profit Factor: {base_pf:.2f}x")
print(f"  Avg gain (wins): {df.loc[df['gain_pct']>0,'gain_pct'].mean():.2f}%")
print(f"  Avg loss (losses): {df.loc[df['gain_pct']<0,'gain_pct'].mean():.2f}%")


def simulate_filter(name, mask, df=df):
    """Simulate removing trades that DON'T pass the filter (mask=True means KEEP)"""
    kept = df[mask].copy()
    dropped = df[~mask].copy()
    losses_k = kept['is_loss'].sum()
    wins_k = kept['is_win'].sum()
    total_k = len(kept)
    
    gain_sum = kept.loc[kept['gain_pct'] > 0, 'gain_pct'].sum()
    loss_sum = kept.loc[kept['gain_pct'] < 0, 'gain_pct'].abs().sum()
    pf = gain_sum / max(0.01, loss_sum)
    
    print(f"\n{'=' * 65}")
    print(f"FILTER: {name}")
    print(f"{'=' * 65}")
    print(f"  Kept: {total_k}/{total} ({total_k/total*100:.1f}%), Dropped: {len(dropped)}")
    print(f"  Losses: {losses_k} ({losses_k/max(1,total_k)*100:.1f}%) vs baseline {base_loss_pct:.1f}%")
    print(f"  Wins: {wins_k} ({wins_k/max(1,total_k)*100:.1f}%)")
    print(f"  Profit Factor: {pf:.2f}x vs baseline {base_pf:.2f}x")
    
    # Loss reduction pct of baseline
    loss_reduction = (base_losses - losses_k) / base_losses * 100
    print(f"  Loss reduction: {loss_reduction:.1f}%")
    print(f"  Win retention: {wins_k/max(1,base_wins)*100:.1f}%")
    print(f"  Avg gain (wins): {kept.loc[kept['gain_pct']>0,'gain_pct'].mean():.2f}%")
    print(f"  Avg loss (losses): {kept.loc[kept['gain_pct']<0,'gain_pct'].mean():.2f}%")
    
    # Dropped trade analysis
    dropped_losses = dropped['is_loss'].sum()
    dropped_wins = dropped['is_win'].sum()
    print(f"\n  DROPPED: {dropped_losses} losses ({dropped_losses/max(1,len(dropped))*100:.1f}%) + {dropped_wins} wins ({dropped_wins/max(1,len(dropped))*100:.1f}%) in {len(dropped)} trades")
    
    return kept


# ─── HYPOTHESIS 1: R:R >= 1.5 Gate ───────────────────────────────────────────
# Only accept signals where T1 upside is at least 1.5x the SL risk
h1_mask = df['rr_ratio'] >= 1.5
simulate_filter("H1: Minimum R:R >= 1.5 Gate", h1_mask)

# ─── HYPOTHESIS 2: SL in Sweet Spot (5-8% away, not 3-5% zone) ──────────────
# Data shows 3-5% SL has 30-35% loss rate vs 5-8% zone at 20-22%
# This means SL is too tight — getting stopped out by noise
h2_mask = (df['sl_distance_pct'] >= 5.0) | (df['sl_distance_pct'] < 3.0)
simulate_filter("H2: SL Distance >= 5% (avoid tight 3-5% SL zone)", h2_mask)

# ─── HYPOTHESIS 3: Large-Cap Tighter Threshold (score >= 60 for large caps) ──
# Large caps have 29.9% loss rate vs mid=20.9%, small=12%
# Large caps need higher conviction threshold
h3_mask = ~((df['market_cap_tier'] == 'large') & (df['composite_score'] < 60.0))
simulate_filter("H3: Large-Cap Score Threshold >= 60 (from any)", h3_mask)

# ─── HYPOTHESIS 4: Composite: SL >= 5% AND R:R >= 1.3 ────────────────────────
h4_mask = (df['sl_distance_pct'] >= 5.0) & (df['rr_ratio'] >= 1.3)
simulate_filter("H4: SL >= 5% AND R:R >= 1.3", h4_mask)

# ─── HYPOTHESIS 5: Combined: Large-cap score>=60, all sl>=4.5, rr>=1.2 ───────
h5_mask = (
    ~((df['market_cap_tier'] == 'large') & (df['composite_score'] < 60.0))
) & (df['sl_distance_pct'] >= 4.5) & (df['rr_ratio'] >= 1.2)
simulate_filter("H5: Large>=60 + SL>=4.5% + R:R>=1.2", h5_mask)

# ─── HYPOTHESIS 6: Speed-of-loss gate: widen SL for short-duration trades ────
# Early losses (<=3 days) account for 37.3% of all losses
# These are likely whipsaws — overly tight SL
h6_mask = (df['sl_distance_pct'] >= 5.5) | df['market_cap_tier'].isin(['small'])
simulate_filter("H6: SL >= 5.5% (broader noise cushion) except small-cap", h6_mask)

# ─── HYPOTHESIS 7: Practical Compound: best of all above ─────────────────────
# Rule:
# - Large-cap: score >= 60 AND SL >= 5% AND R:R >= 1.3
# - Mid-cap: SL >= 4% AND R:R >= 1.2
# - Small-cap: no additional filter (already 12% loss rate)
h7_mask = (
    (df['market_cap_tier'] == 'small') |
    (
        (df['market_cap_tier'] == 'mid') &
        (df['sl_distance_pct'] >= 4.0) & (df['rr_ratio'] >= 1.2)
    ) |
    (
        (df['market_cap_tier'] == 'large') &
        (df['composite_score'] >= 60.0) &
        (df['sl_distance_pct'] >= 5.0) &
        (df['rr_ratio'] >= 1.3)
    )
)
simulate_filter("H7: COMPOUND (Tier-Adaptive SL + R:R + Large-Cap Score Gate)", h7_mask)

# ─── HYPOTHESIS 8: ATR-calibrated SL floor (SL >= ATR*2.5 minimum) ──────────
# Current: sl_atr_mult = 1.5 to 2.6 depending on ADX
# If we enforce minimum 5% SL, it kills whipsaws for large/mid caps
h8_mask = (
    (df['market_cap_tier'] == 'small') |
    ((df['market_cap_tier'] == 'mid') & (df['sl_distance_pct'] >= 4.5)) |
    ((df['market_cap_tier'] == 'large') & (df['composite_score'] >= 59.0) & (df['sl_distance_pct'] >= 5.5))
)
simulate_filter("H8: Tier-calibrated SL floors (large>=5.5%+score>=59, mid>=4.5%, small=any)", h8_mask)

print("\n\nDone!")
