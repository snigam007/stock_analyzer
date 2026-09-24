"""
Comprehensive Empirical Backtesting Suite for 5 Quantitative Improvements:
1. Smart Chandelier & Stepladder Trailing Stop vs Baseline Trailing Stop
2. Missed Alpha Recovery (VCP Pre-Breakout + Quality Mean Reversion)
3. Institutional Reward-to-Risk (R:R) Inception Floor
4. Conviction-Weighted Dynamic Sizing vs Equal Allocation
5. Sector Relative Strength (RS) Thematic Gating
"""

import sys
import io
from pathlib import Path
import sqlite3
import pandas as pd
import numpy as np

# Set UTF-8 encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
import core.sip_audit_backtester as bt_mod

DB_PATH = BASE_DIR / "data" / "stock_analyzer.db"

print("=" * 80)
print("INSTITUTIONAL QUANTITATIVE BACKTESTING & EMPIRICAL ALPHA ANALYSIS")
print("=" * 80)

# ==============================================================================
# TEST 1: TRAILING STOP LEAKAGE & CHANDELIER EXIT COMPARISON
# ==============================================================================
print("\n" + "=" * 80)
print("EXPERIMENT 1: SMART CHANDELIER & SCALE-OUT TRAILING STOP VS BASELINE")
print("=" * 80)

conn = sqlite3.connect(DB_PATH)

# Fetch signals from signal_audit_log where asset_type = 'STOCK'
query_signals = """
    SELECT s.id, s.signal_date, s.symbol, s.signal, s.entry_price, s.target_1, s.target_2, s.target_3, 
           s.stop_loss, s.status, s.realized_gain_pct, t.atr_14
    FROM signal_audit_log s
    LEFT JOIN (
        SELECT symbol, date, atr_14 FROM technical_indicators
    ) t ON s.symbol = t.symbol AND s.signal_date = t.date
    WHERE COALESCE(s.asset_type, 'STOCK') = 'STOCK'
    AND s.status != 'PENDING'
    ORDER BY s.signal_date ASC
"""
df_signals = pd.read_sql_query(query_signals, conn)
print(f"Total historical resolved signals available for exit replay: {len(df_signals)}")

# Replay forward daily prices for each signal to compare exit models:
# Model A: Baseline Recorded in DB (Current trailing stop)
# Model B: Breakeven Lock at +2.5% + Chandelier Stop (Highest High - 2.5 * ATR or 3.5%)
# Model C: 50% Scale-out at Target 1 + Chandelier Stop on remaining 50%

model_a_pnls = []
model_b_pnls = []
model_c_pnls = []
model_d_pnls = []
model_b_exits = {"BE_LOCK": 0, "CHANDELIER_TRAIL": 0, "T1_HIT": 0, "T2_HIT": 0, "T3_HIT": 0, "SL_HIT": 0}
model_c_exits = {"SCALE_OUT_T1": 0, "CHANDELIER_TRAIL": 0, "SL_HIT": 0}

# Pre-fetch forward prices for all symbols
symbols = df_signals['symbol'].unique()
prices_by_sym = {}
for sym in symbols:
    p_df = pd.read_sql_query(
        f"SELECT date, open, high, low, close FROM daily_prices WHERE symbol = '{sym}' ORDER BY date ASC",
        conn
    )
    p_df['date'] = p_df['date'].astype(str)
    prices_by_sym[sym] = p_df

for _, row in df_signals.iterrows():
    sym = row['symbol']
    sig_date = str(row['signal_date'])
    entry = float(row['entry_price'])
    sl = float(row['stop_loss'])
    t1 = float(row['target_1']) if row['target_1'] else entry * 1.05
    t2 = float(row['target_2']) if row['target_2'] else entry * 1.08
    t3 = float(row['target_3']) if row['target_3'] else entry * 1.15
    sig_type = row['signal']
    recorded_pnl = float(row['realized_gain_pct']) if row['realized_gain_pct'] is not None else 0.0
    model_a_pnls.append(recorded_pnl)

    atr = float(row['atr_14']) if row['atr_14'] and not np.isnan(row['atr_14']) else entry * 0.02
    atr_pct = (atr / entry) * 100.0

    p_df = prices_by_sym.get(sym)
    if p_df is None or p_df.empty:
        model_b_pnls.append(recorded_pnl)
        model_c_pnls.append(recorded_pnl)
        model_d_pnls.append(recorded_pnl)
        continue

    fwd_df = p_df[p_df['date'] > sig_date].head(45)
    if fwd_df.empty:
        model_b_pnls.append(recorded_pnl)
        model_c_pnls.append(recorded_pnl)
        model_d_pnls.append(recorded_pnl)
        continue

    # Simulate Model B: Breakeven at +2.5% gain, Chandelier trail (Highest High - 2.5 * ATR)
    curr_sl_b = sl
    be_locked_b = False
    highest_h_b = entry
    exit_pnl_b = None

    # Simulate Model C: 50% scale-out at T1, remainder trails Chandelier
    t1_hit_c = False
    t1_gain_c = (t1 - entry) / entry * 100.0 if sig_type == 'BUY' else (entry - t1) / entry * 100.0
    exit_pnl_c = None

    for _, f_row in fwd_df.iterrows():
        c = float(f_row['close'])
        h = float(f_row['high'])
        l = float(f_row['low'])
        highest_h_b = max(highest_h_b, h)

    # Simulate Model D: Stepladder Profit Floor + Tightened Chandelier (1.8 * ATR)
    # Stage 1: At +2.0% peak -> Stop moves to Breakeven (+0.3%)
    # Stage 2: At +3.5% peak -> Stop locks in +1.5% profit
    # Stage 3: At +5.0% peak (T1) -> Stop locks in +3.2% profit & trails at Highest Close - 1.8 * ATR
    curr_sl_d = sl
    be_locked_d = False
    p15_locked_d = False
    p32_locked_d = False
    exit_pnl_d = None

    for _, f_row in fwd_df.iterrows():
        c = float(f_row['close'])
        h = float(f_row['high'])
        l = float(f_row['low'])
        highest_h_b = max(highest_h_b, h)

        if sig_type == 'BUY':
            gain_peak = (highest_h_b - entry) / entry * 100.0
            
            # Breakeven lock check
            if gain_peak >= 2.5 and not be_locked_b:
                curr_sl_b = max(curr_sl_b, entry * 1.003)  # +0.3% lock
                be_locked_b = True

            # Chandelier Stop: Highest High - 2.5 * ATR
            if be_locked_b:
                chandelier_stop = highest_h_b - 2.5 * atr
                curr_sl_b = max(curr_sl_b, chandelier_stop)

            # Model D Stepladder logic
            if gain_peak >= 5.0 and not p32_locked_d:
                curr_sl_d = max(curr_sl_d, entry * 1.032, highest_h_b - 1.8 * atr)
                p32_locked_d = True
            elif gain_peak >= 3.5 and not p15_locked_d:
                curr_sl_d = max(curr_sl_d, entry * 1.015)
                p15_locked_d = True
            elif gain_peak >= 2.0 and not be_locked_d:
                curr_sl_d = max(curr_sl_d, entry * 1.003)
                be_locked_d = True

            if p32_locked_d:
                curr_sl_d = max(curr_sl_d, highest_h_b - 1.8 * atr)

            # Target 3 hit
            if h >= t3 and exit_pnl_b is None:
                exit_pnl_b = (t3 - entry) / entry * 100.0
                model_b_exits["T3_HIT"] += 1
                break
            # Target 2 hit
            elif h >= t2 and exit_pnl_b is None:
                exit_pnl_b = (t2 - entry) / entry * 100.0
                model_b_exits["T2_HIT"] += 1
                break
            # Stop breach check
            if c <= curr_sl_b:
                exit_pnl_b = (curr_sl_b - entry) / entry * 100.0
                if be_locked_b:
                    if curr_sl_b > entry * 1.005:
                        model_b_exits["CHANDELIER_TRAIL"] += 1
                    else:
                        model_b_exits["BE_LOCK"] += 1
                else:
                    model_b_exits["SL_HIT"] += 1
                break

            # Model D exit check
            if c <= curr_sl_d and exit_pnl_d is None:
                exit_pnl_d = (curr_sl_d - entry) / entry * 100.0

            # Model C scale out check
            if h >= t1 and not t1_hit_c:
                t1_hit_c = True
                model_c_exits["SCALE_OUT_T1"] += 1

            if t1_hit_c and c <= curr_sl_b and exit_pnl_c is None:
                rem_gain = (curr_sl_b - entry) / entry * 100.0
                exit_pnl_c = 0.5 * t1_gain_c + 0.5 * rem_gain
                model_c_exits["CHANDELIER_TRAIL"] += 1
                break
            elif not t1_hit_c and c <= curr_sl_b and exit_pnl_c is None:
                exit_pnl_c = (curr_sl_b - entry) / entry * 100.0
                model_c_exits["SL_HIT"] += 1
                break
        else:
            # Short / SELL
            drop_peak = (entry - min(entry, l)) / entry * 100.0
            if drop_peak >= 2.5 and not be_locked_b:
                curr_sl_b = min(curr_sl_b, entry * 0.997)
                be_locked_b = True
            if be_locked_b:
                chandelier_stop = l + 2.5 * atr
                curr_sl_b = min(curr_sl_b, chandelier_stop)

            if drop_peak >= 5.0 and not p32_locked_d:
                curr_sl_d = min(curr_sl_d, entry * 0.968, l + 1.8 * atr)
                p32_locked_d = True
            elif drop_peak >= 3.5 and not p15_locked_d:
                curr_sl_d = min(curr_sl_d, entry * 0.985)
                p15_locked_d = True
            elif drop_peak >= 2.0 and not be_locked_d:
                curr_sl_d = min(curr_sl_d, entry * 0.997)
                be_locked_d = True

            if p32_locked_d:
                curr_sl_d = min(curr_sl_d, l + 1.8 * atr)

            if l <= t3 and exit_pnl_b is None:
                exit_pnl_b = (entry - t3) / entry * 100.0
                model_b_exits["T3_HIT"] += 1
                break
            elif l <= t2 and exit_pnl_b is None:
                exit_pnl_b = (entry - t2) / entry * 100.0
                model_b_exits["T2_HIT"] += 1
                break
            if c >= curr_sl_b:
                exit_pnl_b = (entry - curr_sl_b) / entry * 100.0
                if be_locked_b:
                    model_b_exits["CHANDELIER_TRAIL"] += 1
                else:
                    model_b_exits["SL_HIT"] += 1
                break
            if c >= curr_sl_d and exit_pnl_d is None:
                exit_pnl_d = (entry - curr_sl_d) / entry * 100.0

    if exit_pnl_b is None:
        last_c = float(fwd_df.iloc[-1]['close'])
        exit_pnl_b = (last_c - entry) / entry * 100.0 if sig_type == 'BUY' else (entry - last_c) / entry * 100.0
    if exit_pnl_c is None:
        if t1_hit_c:
            last_c = float(fwd_df.iloc[-1]['close'])
            rem_gain = (last_c - entry) / entry * 100.0 if sig_type == 'BUY' else (entry - last_c) / entry * 100.0
            exit_pnl_c = 0.5 * t1_gain_c + 0.5 * rem_gain
        else:
            exit_pnl_c = exit_pnl_b
    if exit_pnl_d is None:
        exit_pnl_d = exit_pnl_b

    model_b_pnls.append(round(exit_pnl_b, 2))
    model_c_pnls.append(round(exit_pnl_c, 2))
    model_d_pnls.append(round(exit_pnl_d, 2))

def compute_perf_stats(pnl_list):
    arr = np.array(pnl_list)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    total_trades = len(arr)
    win_rate = len(wins) / total_trades * 100.0 if total_trades > 0 else 0.0
    avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(losses.mean()) if len(losses) > 0 else 0.0
    profit_factor = (wins.sum() / abs(losses.sum())) if len(losses) > 0 and abs(losses.sum()) > 0 else 999.0
    expectancy = float(arr.mean())
    net_pnl = float(arr.sum())
    return {
        "trades": total_trades,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "net_pnl": net_pnl
    }

s_a = compute_perf_stats(model_a_pnls)
s_b = compute_perf_stats(model_b_pnls)
s_c = compute_perf_stats(model_c_pnls)
s_d = compute_perf_stats(model_d_pnls)

print(f"{'Exit Strategy Model':<35} | {'Win Rate':<9} | {'Avg Win':<8} | {'Avg Loss':<9} | {'Profit Factor':<14} | {'Expectancy':<11} | {'Net Return'}")
print("-" * 115)
print(f"{'Model A (Baseline Fixed Retrace)':<35} | {s_a['win_rate']:>7.1f}% | {s_a['avg_win']:>+6.2f}% | {s_a['avg_loss']:>+7.2f}% | {s_a['profit_factor']:>12.2f}x | {s_a['expectancy']:>+9.2f}% | {s_a['net_pnl']:>+9.1f}%")
print(f"{'Model B (BE Lock + Chandelier ATR)':<35} | {s_b['win_rate']:>7.1f}% | {s_b['avg_win']:>+6.2f}% | {s_b['avg_loss']:>+7.2f}% | {s_b['profit_factor']:>12.2f}x | {s_b['expectancy']:>+9.2f}% | {s_b['net_pnl']:>+9.1f}%")
print(f"{'Model C (50% T1 Scale + Chandelier)':<35} | {s_c['win_rate']:>7.1f}% | {s_c['avg_win']:>+6.2f}% | {s_c['avg_loss']:>+7.2f}% | {s_c['profit_factor']:>12.2f}x | {s_c['expectancy']:>+9.2f}% | {s_c['net_pnl']:>+9.1f}%")
print(f"{'Model D (Stepladder Floors + ATR)':<35} | {s_d['win_rate']:>7.1f}% | {s_d['avg_win']:>+6.2f}% | {s_d['avg_loss']:>+7.2f}% | {s_d['profit_factor']:>12.2f}x | {s_d['expectancy']:>+9.2f}% | {s_d['net_pnl']:>+9.1f}%")

print("\nModel B Exit Type Breakdown:")
for k, v in model_b_exits.items():
    print(f"  • {k:<20}: {v:>4} trades ({v/len(df_signals)*100:.1f}%)")

# ==============================================================================
# TEST 2: RECOVERING MISSED ALPHA (VCP COILING + QUALITY MEAN REVERSION)
# ==============================================================================
print("\n" + "=" * 80)
print("EXPERIMENT 2: ALPHA RECOVERY (VCP COILING + QUALITY MEAN REVERSION)")
print("=" * 80)

# Query recent missed alpha audit log
query_missed = """
    SELECT symbol, audit_date, gain_pct, start_score, 
           bottleneck, start_signal
    FROM missed_alpha_audit_log
    ORDER BY gain_pct DESC
"""
df_missed = pd.read_sql_query(query_missed, conn)
print(f"Total tracked explosive runners in audit log: {len(df_missed)}")

if not df_missed.empty:
    total_runners = len(df_missed)
    baseline_caught = len(df_missed[df_missed['start_signal'] == 'BUY'])
    baseline_missed = total_runners - baseline_caught
    
    recovered_runners = df_missed[
        (df_missed['start_signal'] != 'BUY') & 
        (
            ((df_missed['bottleneck'] == 'Volume Pre-Breakout Dryness') & (df_missed['start_score'] >= 50.0)) |
            ((df_missed['bottleneck'] == 'Score Calibration') & (df_missed['start_score'] >= 52.0)) |
            (df_missed['bottleneck'] == 'Below 50 EMA Filter')
        )
    ]
    recovered_count = len(recovered_runners)
    new_caught = baseline_caught + recovered_count
    new_missed = total_runners - new_caught
    
    total_alpha_available = df_missed['gain_pct'].sum()
    baseline_alpha_caught = df_missed[df_missed['start_signal'] == 'BUY']['gain_pct'].sum()
    recovered_alpha = recovered_runners['gain_pct'].sum()
    new_alpha_caught = baseline_alpha_caught + recovered_alpha
    
    print(f"\n{'Metric':<35} | {'Baseline (Current)':<20} | {'With VCP & Mean Rev Recovery':<28} | {'Delta Edge'}")
    print("-" * 105)
    print(f"{'Runner Capture Rate':<35} | {baseline_caught}/{total_runners} ({baseline_caught/total_runners*100:.1f}%)      | {new_caught}/{total_runners} ({new_caught/total_runners*100:.1f}%)                 | +{(new_caught - baseline_caught)/total_runners*100:+.1f}%")
    print(f"{'False Negative Rate':<35} | {baseline_missed}/{total_runners} ({baseline_missed/total_runners*100:.1f}%)      | {new_missed}/{total_runners} ({new_missed/total_runners*100:.1f}%)                 | -{(baseline_missed - new_missed)/total_runners*100:.1f}%")
    print(f"{'Total Alpha Captured':<35} | +{baseline_alpha_caught:>7.1f}%               | +{new_alpha_caught:>7.1f}%                        | +{recovered_alpha:>+7.1f}%")
    print(f"{'Alpha Capture Efficiency':<35} | {baseline_alpha_caught/total_alpha_available*100:>7.1f}%               | {new_alpha_caught/total_alpha_available*100:>7.1f}%                        | +{(new_alpha_caught - baseline_alpha_caught)/total_alpha_available*100:+.1f}%")

    print("\nTop Recovered High-Alpha Runners:")
    for _, r in recovered_runners.head(5).iterrows():
        print(f"  • {r['symbol']:<12} | Gain: +{r['gain_pct']:>5.1f}% | Pre-Score: {r['start_score']:.1f} | Bottleneck: {r['bottleneck']}")

# ==============================================================================
# TEST 3: INSTITUTIONAL REWARD-TO-RISK (R:R) INCEPTION FILTER
# ==============================================================================
print("\n" + "=" * 80)
print("EXPERIMENT 3: INSTITUTIONAL REWARD-TO-RISK (R:R) INCEPTION FILTER")
print("=" * 80)

# Calculate inception R:R for df_signals
df_signals['t1_dist'] = np.where(
    df_signals['signal'] == 'BUY',
    (df_signals['target_1'] - df_signals['entry_price']) / df_signals['entry_price'] * 100.0,
    (df_signals['entry_price'] - df_signals['target_1']) / df_signals['entry_price'] * 100.0
)
df_signals['sl_dist'] = np.where(
    df_signals['signal'] == 'BUY',
    (df_signals['entry_price'] - df_signals['stop_loss']) / df_signals['entry_price'] * 100.0,
    (df_signals['stop_loss'] - df_signals['entry_price']) / df_signals['entry_price'] * 100.0
)
df_signals['rr_ratio'] = df_signals['t1_dist'] / df_signals['sl_dist'].replace(0, 0.01)

rr_thresholds = [0.0, 1.2, 1.5, 1.8, 2.0]
print(f"{'Min R:R Threshold':<20} | {'Signals Kept':<14} | {'Filter Rate':<12} | {'Win Rate':<10} | {'Avg Win':<9} | {'Avg Loss':<9} | {'Profit Factor':<14} | {'Expectancy'}")
print("-" * 115)

for th in rr_thresholds:
    sub = df_signals[df_signals['rr_ratio'] >= th]
    arr = sub['realized_gain_pct'].dropna().values
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    wr = len(wins) / len(arr) * 100.0 if len(arr) > 0 else 0.0
    aw = float(wins.mean()) if len(wins) > 0 else 0.0
    al = float(losses.mean()) if len(losses) > 0 else 0.0
    pf = (wins.sum() / abs(losses.sum())) if len(losses) > 0 and abs(losses.sum()) > 0 else 999.0
    exp = float(arr.mean()) if len(arr) > 0 else 0.0
    kept_pct = len(sub) / len(df_signals) * 100.0
    filtered_pct = 100.0 - kept_pct
    print(f"{'>= ' + str(th) + 'x R:R':<20} | {len(sub):>5} ({kept_pct:>5.1f}%) | {filtered_pct:>9.1f}%  | {wr:>8.1f}% | {aw:>+7.2f}% | {al:>+7.2f}% | {pf:>12.2f}x | {exp:>+8.2f}%")

# ==============================================================================
# TEST 4: ASYMMETRIC CONVICTION-WEIGHTED ALLOCATION (SIP BACKTEST)
# ==============================================================================
print("\n" + "=" * 80)
print("EXPERIMENT 4: CONVICTION-WEIGHTED SIZING VS EQUAL ALLOCATION (MULTI-TIMEFRAME)")
print("=" * 80)

session = get_session(get_global_engine())

lookbacks = [24, 36, 60]
profiles = ["BALANCED", "RISKY"]

print(f"{'Lookback':<10} | {'Risk Profile':<13} | {'Allocation Mode':<18} | {'Final Value (₹)':<16} | {'Strategy XIRR':<14} | {'Win Rate':<9} | {'Alpha vs Nifty'}")
print("-" * 105)

for lb in lookbacks:
    for prof in profiles:
        # Run Equal Weighting
        res_eq = bt_mod.run_monthly_sip_backtest(
            session,
            monthly_wallet=20000,
            months_lookback=lb,
            annual_step_up_pct=10.0,
            risk_profile=prof,
            enable_conviction_weighting=False
        )
        # Run Conviction Weighting
        res_cv = bt_mod.run_monthly_sip_backtest(
            session,
            monthly_wallet=20000,
            months_lookback=lb,
            annual_step_up_pct=10.0,
            risk_profile=prof,
            enable_conviction_weighting=True
        )
        
        diff_val = res_cv['final_strategy_value'] - res_eq['final_strategy_value']
        diff_xirr = res_cv['strategy_xirr'] - res_eq['strategy_xirr']
        
        print(f"{str(lb) + ' Months':<10} | {prof:<13} | {'Equal Weight (20%)':<18} | ₹{res_eq['final_strategy_value']:>13,.0f} | {res_eq['strategy_xirr']:>12.2f}% | {res_eq['win_rate']:>7.1f}% | {res_eq.get('alpha', 0.0):>+11.2f}%")
        print(f"{str(lb) + ' Months':<10} | {prof:<13} | {'Conviction (30-10%)':<18} | ₹{res_cv['final_strategy_value']:>13,.0f} | {res_cv['strategy_xirr']:>12.2f}% | {res_cv['win_rate']:>7.1f}% | {res_cv.get('alpha', 0.0):>+11.2f}%")
        print(f"{'':<10} | {'':<13} | {'  -> ADVANTAGE':<18} | {diff_val:>+14,.0f} | {diff_xirr:>+11.2f}% XIRR Edge |")
        print("-" * 105)

# ==============================================================================
# TEST 5: SECTOR RELATIVE STRENGTH (RS) THEMATIC GATING
# ==============================================================================
print("\n" + "=" * 80)
print("EXPERIMENT 5: SECTOR RELATIVE STRENGTH (RS) GATING")
print("=" * 80)

# Merge signals with sector
q_sector_trades = """
    SELECT s.symbol, s.signal_date, s.signal, s.realized_gain_pct, st.sector
    FROM signal_audit_log s
    JOIN stocks st ON s.symbol = st.symbol
    WHERE s.status != 'PENDING'
    AND COALESCE(s.asset_type, 'STOCK') = 'STOCK'
    AND s.realized_gain_pct IS NOT NULL
"""
df_sec_trades = pd.read_sql_query(q_sector_trades, conn)

sector_stats = []
for sec, group in df_sec_trades.groupby('sector'):
    arr = group['realized_gain_pct'].values
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    wr = len(wins) / len(arr) * 100.0 if len(arr) > 0 else 0.0
    pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 and abs(losses.sum()) > 0 else 99.0
    exp = float(arr.mean())
    sector_stats.append({
        'sector': sec,
        'trades': len(arr),
        'win_rate': wr,
        'profit_factor': pf,
        'expectancy': exp,
        'net_pnl': float(arr.sum())
    })

df_sec_summary = pd.DataFrame(sector_stats).sort_values(by='expectancy', ascending=False)
top_sectors = df_sec_summary.head(4)['sector'].tolist()
bottom_sectors = df_sec_summary.tail(4)['sector'].tolist()

top_trades = df_sec_trades[df_sec_trades['sector'].isin(top_sectors)]['realized_gain_pct'].values
bottom_trades = df_sec_trades[df_sec_trades['sector'].isin(bottom_sectors)]['realized_gain_pct'].values

top_wins = top_trades[top_trades > 0]
top_losses = top_trades[top_trades < 0]
top_wr = len(top_wins) / len(top_trades) * 100.0
top_pf = top_wins.sum() / abs(top_losses.sum()) if len(top_losses) > 0 else 99.0

bot_wins = bottom_trades[bottom_trades > 0]
bot_losses = bottom_trades[bottom_trades < 0]
bot_wr = len(bot_wins) / len(bottom_trades) * 100.0 if len(bottom_trades) > 0 else 0.0
bot_pf = bot_wins.sum() / abs(bot_losses.sum()) if len(bot_losses) > 0 and abs(bot_losses.sum()) > 0 else 0.0

print(f"{'Sector Basket':<30} | {'Trades':<8} | {'Win Rate':<9} | {'Profit Factor':<14} | {'Avg Return / Trade':<20} | {'Total Gain'}")
print("-" * 105)
print(f"{'Leading Sectors (Top Quartile)':<30} | {len(top_trades):>6}   | {top_wr:>7.1f}% | {top_pf:>12.2f}x | {top_trades.mean():>+18.2f}% | {top_trades.sum():>+9.1f}%")
print(f"{'Lagging Sectors (Bottom Quartile)':<30} | {len(bottom_trades):>6}   | {bot_wr:>7.1f}% | {bot_pf:>12.2f}x | {bottom_trades.mean():>+18.2f}% | {bottom_trades.sum():>+9.1f}%")
print(f"{'EDGE OF SECTOR GATING':<30} |        | {top_wr - bot_wr:>+7.1f}% | {top_pf - bot_pf:>+12.2f}x | {top_trades.mean() - bottom_trades.mean():>+18.2f}% |")

print("\nTop 4 Outperforming Sectors:")
for _, r in df_sec_summary.head(4).iterrows():
    print(f"  [Top] {r['sector']:<35}: {r['trades']:>3} trades | WinRate: {r['win_rate']:>5.1f}% | PF: {r['profit_factor']:>5.2f}x | Expectancy: {r['expectancy']:>+5.2f}%")

print("\nBottom 4 Underperforming Sectors (To Filter/Hedge):")
for _, r in df_sec_summary.tail(4).iterrows():
    print(f"  [Lag] {r['sector']:<35}: {r['trades']:>3} trades | WinRate: {r['win_rate']:>5.1f}% | PF: {r['profit_factor']:>5.2f}x | Expectancy: {r['expectancy']:>+5.2f}%")

conn.close()
session.close()

print("\n" + "=" * 80)
print("ALL 5 EMPIRICAL BACKTESTS COMPLETED SUCCESSFULLY!")
print("=" * 80)
