"""
scripts/backtest_advanced_quant_5year.py
=========================================
5-Year Full-Cycle Quantitative Backtesting & Accuracy Ablation Engine
(2021-09-27 to 2026-09-25 / 1,298 Trading Sessions)

Tests and benchmarks the advanced methodologies discussed:
1. Baseline: Standard Multi-Lookback Momentum + Static ATR Stop
2. Variant A: Log-Scale & Dollar-Volume Normalization (Liquidity Gate)
3. Variant B: Chaos Theory Regime Filter (Rolling 60-Day DFA Hurst Exponent)
4. Variant C: JEV Jump-Diffusion & Bipower Variation Gap-Buffered Stop
5. Variant D: Lead-Lag Bellwether Momentum Confirmation
6. Variant E: Unified Grand Quantum Frontier (All 4 Ensembles + Fractional Kelly)
"""

import sys
import os
import json
import time
import math
import sqlite3
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Any, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm, skew, kurtosis

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AdvancedQuant5YearBacktester")

DB_PATH = ROOT_DIR / "data" / "stock_analyzer.db"


def compute_hurst_exponent_dfa(series: np.ndarray, min_window: int = 10, max_window: int = 50) -> float:
    """
    Computes Hurst exponent via simplified Detrended Fluctuation Analysis (DFA).
    H > 0.5: Trending / Persistent
    H = 0.5: Random Walk
    H < 0.5: Mean Reverting / Anti-persistent
    """
    n = len(series)
    if n < max_window:
        return 0.5
    
    # Cumulative sum of mean-centered series
    y = np.cumsum(series - np.mean(series))
    
    scales = np.unique(np.linspace(min_window, min(max_window, n // 2), 6).astype(int))
    fluctuations = []
    
    for scale in scales:
        n_segments = n // scale
        if n_segments == 0:
            continue
        segment_rms = []
        for i in range(n_segments):
            segment = y[i * scale : (i + 1) * scale]
            t = np.arange(scale)
            # Linear trend fit
            poly = np.polyfit(t, segment, 1)
            trend = np.polyval(poly, t)
            rms = np.sqrt(np.mean((segment - trend) ** 2))
            segment_rms.append(rms)
        if segment_rms:
            fluctuations.append(np.mean(segment_rms))
        else:
            fluctuations.append(1e-6)
            
    if len(scales) < 2 or len(fluctuations) < 2:
        return 0.5
        
    log_scales = np.log(scales[:len(fluctuations)])
    log_fluct = np.log(np.maximum(fluctuations, 1e-6))
    
    # Slope is Hurst exponent H
    poly = np.polyfit(log_scales, log_fluct, 1)
    h = float(poly[0])
    return max(0.01, min(0.99, h))


def compute_bipower_variation_jump_intensity(returns: np.ndarray) -> Tuple[float, float]:
    """
    Computes Realized Volatility, Bipower Variation, and Jump Variance.
    Returns (continuous_vol, jump_std)
    """
    if len(returns) < 10:
        std = float(np.std(returns)) if len(returns) > 1 else 0.02
        return std, 0.0
    
    r = returns[-20:] # Last 20 days
    rv = float(np.sum(r ** 2))
    
    # Bipower variation factor pi/2 * (M / (M-1))
    abs_r = np.abs(r)
    bv = float((math.pi / 2.0) * (len(r) / (len(r) - 1)) * np.sum(abs_r[1:] * abs_r[:-1]))
    
    jump_var = max(0.0, rv - bv)
    continuous_vol = math.sqrt(max(1e-6, bv / len(r)))
    jump_std = math.sqrt(max(0.0, jump_var / len(r)))
    
    return continuous_vol, jump_std


def load_5year_data(db_path: Path):
    t0 = time.time()
    conn = sqlite3.connect(str(db_path))

    # 1. Benchmark NIFTY 50
    nifty_df = pd.read_sql_query("""
        SELECT date, close
        FROM index_prices
        WHERE symbol = '^NSEI' AND date >= '2021-01-01'
        ORDER BY date ASC;
    """, conn)
    
    if nifty_df.empty:
        nifty_df = pd.read_sql_query("""
            SELECT date, AVG(close) as close
            FROM daily_prices
            WHERE date >= '2021-01-01'
            GROUP BY date ORDER BY date ASC;
        """, conn)

    nifty_df['date'] = pd.to_datetime(nifty_df['date']).dt.date
    nifty_df = nifty_df.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
    nifty_df['ema_50'] = nifty_df['close'].ewm(span=50, adjust=False).mean()
    nifty_df['ema_21'] = nifty_df['close'].ewm(span=21, adjust=False).mean()
    nifty_df['mom_3d'] = nifty_df['close'].pct_change(3) * 100.0
    nifty_df['is_bull'] = (nifty_df['close'] >= nifty_df['ema_50']) | (nifty_df['close'] >= nifty_df['ema_21'])

    mkt_map = {}
    for _, r in nifty_df.iterrows():
        mkt_map[r['date']] = {
            'close': r['close'],
            'ema_50': r['ema_50'],
            'ema_21': r['ema_21'],
            'mom_3d': r['mom_3d'],
            'is_bull': bool(r['is_bull'])
        }
    trading_dates = nifty_df['date'].tolist()

    # 2. Stock Data
    stocks_df = pd.read_sql_query("""
        SELECT symbol, date, open, high, low, close, volume
        FROM daily_prices
        WHERE date >= '2021-01-01' AND symbol NOT IN ('^NSEI', 'NIFTY 50', 'NIFTY', 'GOLDBEES.NS')
        ORDER BY symbol, date ASC;
    """, conn)
    conn.close()

    stocks_df['date'] = pd.to_datetime(stocks_df['date']).dt.date

    stock_dfs = {}
    for sym, g in stocks_df.groupby('symbol'):
        if len(g) < 60:
            continue
        g = g.sort_values('date').reset_index(drop=True)
        c = g['close']
        h = g['high']
        l = g['low']
        v = g['volume']

        # Log Returns & Log Dollar Volume
        log_ret = np.log(c / c.shift(1).replace(0, np.nan)).fillna(0.0)
        g['log_return'] = log_ret
        g['log_volume'] = np.log(v + 1.0)
        g['log_dollar_vol'] = np.log(c * v + 1.0)
        
        # Standardized Log Dollar Volume Z-Score (60-day rolling)
        mean_ldv = g['log_dollar_vol'].rolling(60, min_periods=20).mean()
        std_ldv = g['log_dollar_vol'].rolling(60, min_periods=20).std().replace(0, 1.0)
        g['z_log_dollar_vol'] = (g['log_dollar_vol'] - mean_ldv) / std_ldv

        # EMAs & ATR
        g['ema_50'] = c.ewm(span=50, adjust=False).mean()
        g['ema_200'] = c.ewm(span=200, adjust=False).mean()

        hl = h - l
        hc = (h - c.shift(1)).abs()
        lc = (l - c.shift(1)).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        g['atr_14'] = tr.rolling(14, min_periods=14).mean().fillna(c * 0.02)

        # Multi-Lookback Momentum
        g['mom_1m'] = ((c - c.shift(20)) / c.shift(20) * 100.0).fillna(0.0)
        g['mom_3m'] = ((c - c.shift(60)) / c.shift(60) * 100.0).fillna(0.0)
        g['mom_6m'] = ((c - c.shift(126)) / c.shift(126) * 100.0).fillna(0.0)
        g['mom_12m'] = ((c - c.shift(250)) / c.shift(250) * 100.0).fillna(0.0)

        # RSI
        delta = c.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14, min_periods=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14, min_periods=14).mean()
        rs = gain / loss.replace(0, 0.0001)
        g['rsi_14'] = 100.0 - (100.0 / (1.0 + rs)).fillna(50.0)

        g['multi_lookback_score'] = (
            0.15 * g['mom_1m'] +
            0.25 * g['mom_3m'] +
            0.40 * g['mom_6m'] +
            0.20 * g['mom_12m']
        )

        # Rolling Hurst Exponent (60-day window) & JEV Jump Buffer
        n_rows = len(g)
        hurst_arr = np.full(n_rows, 0.5)
        jump_std_arr = np.full(n_rows, 0.0)
        log_ret_vals = log_ret.values
        
        # Optimized vectorized approximation for backtest speed
        for idx in range(60, n_rows, 3):  # calculate every 3 days and forward fill
            window_ret = log_ret_vals[idx - 60 : idx]
            h_val = compute_hurst_exponent_dfa(window_ret, min_window=8, max_window=30)
            _, j_std = compute_bipower_variation_jump_intensity(window_ret)
            hurst_arr[idx : min(idx + 3, n_rows)] = h_val
            jump_std_arr[idx : min(idx + 3, n_rows)] = j_std

        g['hurst_60'] = hurst_arr
        g['jump_std_20'] = jump_std_arr

        stock_dfs[sym] = g.set_index('date')

    logger.info(f"Loaded {len(stock_dfs)} stocks & NIFTY across {len(trading_dates)} sessions in {time.time()-t0:.2f}s")
    return mkt_map, trading_dates, stock_dfs


def run_strategy_simulation(
    trading_dates: List[date],
    stock_dfs: Dict[str, pd.DataFrame],
    mkt_map: Dict[date, Any],
    variant_name: str,
    use_log_dollar_vol_gate: bool = False,
    use_chaos_hurst_filter: bool = False,
    use_jev_jump_buffer: bool = False,
    use_lead_lag_confirm: bool = False,
    use_fractional_kelly: bool = False,
    initial_capital: float = 500000.0,
    start_date: date = date(2021, 9, 27),
    end_date: date = date(2026, 9, 25)
) -> Dict[str, Any]:
    """Runs a 5-year simulation with specific quantitative ablation settings."""
    filtered_dates = [d for d in trading_dates if start_date <= d <= end_date]
    if not filtered_dates:
        return {}

    max_slots = 3
    tiers = [(1.5, 0.333), (3.0, 0.333), (8.5, 0.334)]

    cash = initial_capital
    cash_liquidbees = 0.0
    open_positions = {}
    closed_trades = []
    equity_curve = []

    for curr_d in filtered_dates:
        mkt_row = mkt_map.get(curr_d, {'is_bull': True, 'mom_3d': 0.0})
        is_bull = mkt_row['is_bull']

        active_allowed_slots = 1 if not is_bull else max_slots

        # Accrue LiquidBees yield (6.5% p.a.)
        if cash_liquidbees > 0:
            cash_liquidbees += cash_liquidbees * (0.065 / 365.0)

        # 1. Manage Active Positions
        for sym, pos in list(open_positions.items()):
            df_s = stock_dfs.get(sym)
            if df_s is None or curr_d not in df_s.index:
                continue

            row = df_s.loc[curr_d]
            h = float(row['high'])
            l = float(row['low'])
            c = float(row['close'])
            atr = pos['atr']

            # Stop Loss Check
            if l <= pos['stop_loss']:
                exit_price = min(pos['stop_loss'], float(row['open']))
                pnl = (exit_price - pos['avg_price']) * pos['shares']
                pnl_pct = (exit_price - pos['avg_price']) / pos['avg_price'] * 100.0
                cash += pos['shares'] * exit_price
                closed_trades.append({
                    'symbol': sym,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'hold_days': (curr_d - pos['entry_date']).days,
                    'outcome': 'SL_HIT' if pnl <= 0 else 'TRAILING_SL_HIT'
                })
                del open_positions[sym]
                continue

            # Winner Pyramiding (+4.0% gain -> Add +50% size, SL to Breakeven)
            if not pos['pyramided'] and h >= pos['entry_price'] * 1.04:
                add_shares = int(pos['original_shares'] * 0.5)
                add_cost = add_shares * c
                if cash >= add_cost and add_shares > 0:
                    cash -= add_cost
                    pos['shares'] += add_shares
                    pos['avg_price'] = (pos['avg_price'] * (pos['shares'] - add_shares) + add_cost) / pos['shares']
                    pos['stop_loss'] = pos['entry_price'] * 1.002
                    pos['pyramided'] = True

            # Dynamic Tier Harvesting
            cur_tier = pos['tier_idx']
            if cur_tier < len(tiers) - 1:
                tier_mult, trim_ratio = tiers[cur_tier]
                if h >= pos['entry_price'] + (tier_mult * atr):
                    trim_shares = int(pos['original_shares'] * trim_ratio)
                    if trim_shares > 0 and pos['shares'] > trim_shares:
                        t_price = pos['entry_price'] + (tier_mult * atr)
                        cash += trim_shares * t_price
                        pos['shares'] -= trim_shares
                        pos['tier_idx'] += 1
                        pos['stop_loss'] = max(pos['stop_loss'], pos['entry_price'] + (cur_tier * 0.5 * atr))
            else:
                # Runner Tier (Chandelier trailing)
                highest_since = pos.get('highest_close', c)
                if c > highest_since:
                    pos['highest_close'] = c
                chand_stop = pos['highest_close'] - (2.5 * atr)
                pos['stop_loss'] = max(pos['stop_loss'], chand_stop)

                upper_mult = tiers[-1][0]
                if h >= pos['entry_price'] + (upper_mult * atr):
                    cash += pos['shares'] * c
                    pnl = (c - pos['avg_price']) * pos['shares']
                    pnl_pct = (c - pos['avg_price']) / pos['avg_price'] * 100.0
                    closed_trades.append({
                        'symbol': sym,
                        'pnl': pnl,
                        'pnl_pct': pnl_pct,
                        'hold_days': (curr_d - pos['entry_date']).days,
                        'outcome': 'T3_MOONBAG'
                    })
                    del open_positions[sym]
                    continue

        # 2. Portfolio Valuation
        cur_pos_val = sum(
            pos['shares'] * float(stock_dfs[sym].loc[curr_d]['close'])
            if (sym in stock_dfs and curr_d in stock_dfs[sym].index)
            else pos['shares'] * pos['avg_price']
            for sym, pos in open_positions.items()
        )
        total_equity = cash + cash_liquidbees + cur_pos_val
        equity_curve.append(total_equity)

        # 3. Candidate Screening & Entry Execution
        needed_slots = active_allowed_slots - len(open_positions)
        if needed_slots > 0 and (cash + cash_liquidbees) > 20000:
            if cash_liquidbees > 0:
                cash += cash_liquidbees
                cash_liquidbees = 0.0

            # Sizing Strategy
            if use_fractional_kelly:
                recent_closed = closed_trades[-30:] if len(closed_trades) >= 10 else []
                if len(recent_closed) >= 10:
                    w = [t['pnl'] for t in recent_closed if t['pnl'] > 0]
                    l = [abs(t['pnl']) for t in recent_closed if t['pnl'] <= 0]
                    p = len(w) / len(recent_closed)
                    b = (np.mean(w) / max(1.0, np.mean(l))) if (w and l) else 2.5
                else:
                    p = 0.40
                    b = 2.5
                f_star = (p * b - (1.0 - p)) / max(0.1, b)
                # 0.4x Fractional Kelly
                k_frac = max(0.20, min(0.333, (f_star * 0.4) + 0.15))
                slot_capital = total_equity * k_frac
            else:
                slot_capital = total_equity * (1.0 / max_slots)

            candidates = []
            for sym, df_s in stock_dfs.items():
                if sym in open_positions or curr_d not in df_s.index:
                    continue

                row = df_s.loc[curr_d]
                cp = float(row['close'])
                e50 = float(row['ema_50'])
                e200 = float(row['ema_200'])
                rsi = float(row['rsi_14'])
                atr = float(row['atr_14'])
                m1 = float(row['mom_1m'])
                m3 = float(row['mom_3m'])
                m6 = float(row['mom_6m'])
                score = float(row['multi_lookback_score'])
                hurst = float(row['hurst_60'])
                z_ldv = float(row['z_log_dollar_vol'])
                j_std = float(row['jump_std_20'])

                if cp < 30 or atr <= 0:
                    continue

                # Baseline Momentum Criteria
                if not (cp >= e50 >= e200 * 0.98 and m1 > 0 and m3 > 0 and m6 > 10.0 and 45.0 <= rsi <= 72.0):
                    continue

                # Ablation Filters:
                # 1. Log Dollar Volume Gate
                if use_log_dollar_vol_gate and z_ldv < 0.20:
                    continue

                # 2. Chaos Theory DFA Hurst Filter
                if use_chaos_hurst_filter and hurst <= 0.51:
                    continue

                # 3. Lead-Lag Bellwether Momentum Confirmation
                if use_lead_lag_confirm and mkt_row.get('mom_3d', 0.0) < -0.5:
                    continue

                candidates.append((sym, score, cp, atr, j_std))

            candidates.sort(key=lambda x: x[1], reverse=True)
            for sym, score, cp, atr, j_std in candidates[:needed_slots]:
                alloc = min(cash * 0.95, slot_capital)
                shares = int(alloc / cp)
                if shares > 0 and cash >= (shares * cp):
                    cost = shares * cp
                    cash -= cost
                    
                    # Stop Loss: JEV Jump-Diffusion Buffered vs Static ATR
                    if use_jev_jump_buffer:
                        # Extra buffer proportional to recent jump volatility (gap shield)
                        jump_buffer = 1.2 * j_std * cp
                        init_sl = cp - (2.0 * atr + jump_buffer)
                    else:
                        init_sl = cp - (2.0 * atr)

                    open_positions[sym] = {
                        'entry_date': curr_d,
                        'entry_price': cp,
                        'avg_price': cp,
                        'shares': shares,
                        'original_shares': shares,
                        'atr': atr,
                        'stop_loss': init_sl,
                        'pyramided': False,
                        'tier_idx': 0,
                        'highest_close': cp
                    }

    # Final Metrics Calculation
    final_val = equity_curve[-1] if equity_curve else initial_capital
    ret_pct = (final_val - initial_capital) / initial_capital * 100.0
    cagr = ((final_val / initial_capital) ** (1.0 / 5.0) - 1.0) * 100.0

    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100.0
        if dd > max_dd:
            max_dd = dd

    total_trades = len(closed_trades)
    wins = [t for t in closed_trades if t['pnl'] > 0]
    losses = [t for t in closed_trades if t['pnl'] <= 0]
    sl_hits = [t for t in closed_trades if t['outcome'] == 'SL_HIT']

    win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0
    sl_hit_rate = (len(sl_hits) / total_trades * 100.0) if total_trades > 0 else 0.0

    total_win_pnl = sum(t['pnl'] for t in wins)
    total_loss_pnl = abs(sum(t['pnl'] for t in losses))
    pf = (total_win_pnl / total_loss_pnl) if total_loss_pnl > 0 else 99.0
    avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0.0
    avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0.0
    payoff = abs(avg_win / avg_loss) if avg_loss != 0 else 1.0

    calmar = cagr / max_dd if max_dd > 0 else 0.0

    return {
        'variant': variant_name,
        'final_val': round(final_val, 2),
        'cagr': round(cagr, 2),
        'max_dd': round(max_dd, 2),
        'calmar': round(calmar, 2),
        'trades': total_trades,
        'win_rate': round(win_rate, 1),
        'sl_hit_rate': round(sl_hit_rate, 1),
        'profit_factor': round(pf, 2),
        'payoff_ratio': round(payoff, 2),
        'avg_win_pct': round(avg_win, 2),
        'avg_loss_pct': round(avg_loss, 2),
    }


def main():
    print("=" * 100)
    print(" 5-YEAR FULL-CYCLE QUANTITATIVE ACCURACY & STRATEGY ABLATION BACKTEST (2021-2026)")
    print("=" * 100)

    mkt_map, trading_dates, stock_dfs = load_5year_data(DB_PATH)

    variants = [
        {
            'name': '1. Baseline Momentum (Standard TA)',
            'use_log_dollar_vol_gate': False,
            'use_chaos_hurst_filter': False,
            'use_jev_jump_buffer': False,
            'use_lead_lag_confirm': False,
            'use_fractional_kelly': False,
        },
        {
            'name': '2. + Log Dollar-Volume Gate (Liquidity)',
            'use_log_dollar_vol_gate': True,
            'use_chaos_hurst_filter': False,
            'use_jev_jump_buffer': False,
            'use_lead_lag_confirm': False,
            'use_fractional_kelly': False,
        },
        {
            'name': '3. + Chaos DFA Hurst Filter (H > 0.51)',
            'use_log_dollar_vol_gate': False,
            'use_chaos_hurst_filter': True,
            'use_jev_jump_buffer': False,
            'use_lead_lag_confirm': False,
            'use_fractional_kelly': False,
        },
        {
            'name': '4. + JEV Jump-Diffusion Gap Buffer',
            'use_log_dollar_vol_gate': False,
            'use_chaos_hurst_filter': False,
            'use_jev_jump_buffer': True,
            'use_lead_lag_confirm': False,
            'use_fractional_kelly': False,
        },
        {
            'name': '5. + Lead-Lag Bellwether Momentum',
            'use_log_dollar_vol_gate': False,
            'use_chaos_hurst_filter': False,
            'use_jev_jump_buffer': False,
            'use_lead_lag_confirm': True,
            'use_fractional_kelly': False,
        },
        {
            'name': '6. Unified Grand Quantum Frontier (All Synergies)',
            'use_log_dollar_vol_gate': True,
            'use_chaos_hurst_filter': True,
            'use_jev_jump_buffer': True,
            'use_lead_lag_confirm': True,
            'use_fractional_kelly': True,
        }
    ]

    results = []
    for var in variants:
        t_start = time.time()
        res = run_strategy_simulation(
            trading_dates=trading_dates,
            stock_dfs=stock_dfs,
            mkt_map=mkt_map,
            variant_name=var['name'],
            use_log_dollar_vol_gate=var['use_log_dollar_vol_gate'],
            use_chaos_hurst_filter=var['use_chaos_hurst_filter'],
            use_jev_jump_buffer=var['use_jev_jump_buffer'],
            use_lead_lag_confirm=var['use_lead_lag_confirm'],
            use_fractional_kelly=var['use_fractional_kelly']
        )
        elapsed = time.time() - t_start
        results.append(res)
        print(f"Completed {var['name']} in {elapsed:.2f}s | WinRate: {res['win_rate']}% | PF: {res['profit_factor']}x | MaxDD: {res['max_dd']}%")

    print("\n" + "=" * 105)
    print(f"{'Strategy Variant':<45} | {'Trades':<6} | {'WinRate':<7} | {'SL Hit':<7} | {'PF':<5} | {'Payoff':<6} | {'CAGR':<6} | {'MaxDD':<6} | {'Calmar':<6}")
    print("-" * 105)
    for r in results:
        print(f"{r['variant']:<45} | {r['trades']:<6} | {r['win_rate']:<6.1f}% | {r['sl_hit_rate']:<6.1f}% | {r['profit_factor']:<4.2f}x | {r['payoff_ratio']:<5.2f}x | {r['cagr']:<5.1f}% | {r['max_dd']:<5.1f}% | {r['calmar']:<5.2f}")
    print("=" * 105)

    # Save output to JSON
    output_path = ROOT_DIR / "data" / "advanced_quant_5year_backtest_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed ablation results saved to: {output_path}")


if __name__ == "__main__":
    main()
