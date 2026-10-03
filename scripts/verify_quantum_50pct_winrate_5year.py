"""
scripts/verify_quantum_50pct_winrate_5year.py
==============================================
5-Year Verification: Breaking the 50% Win Rate & 2.0x Profit Factor Barrier
(2021-09-27 to 2026-09-25 / 1,420 Trading Sessions across 304 NSE Equities)

Core Hypothesis to Verify:
1. Fast Tier-1 Harvest (+1.0x ATR trim 25% + instant Breakeven ratchet):
   Converts trades that stall at +1.2R to +1.4R from losses into confirmed wins.
2. Andreas Clenow Exponential Momentum & R-Squared Smoothness Gate:
   Filters out choppy high-beta noise; restricts capital to clean institutional trends.
3. Target: Win Rate > 50.0%, Profit Factor > 1.8x - 2.0x, Max Drawdown < 20%.
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

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("QuantumWinRateVerification")

DB_PATH = ROOT_DIR / "data" / "stock_analyzer.db"


def compute_hurst_exponent_dfa(series: np.ndarray, min_window: int = 8, max_window: int = 30) -> float:
    """Computes Hurst exponent via simplified Detrended Fluctuation Analysis (DFA)."""
    n = len(series)
    if n < max_window:
        return 0.5
    y = np.cumsum(series - np.mean(series))
    scales = np.unique(np.linspace(min_window, min(max_window, n // 2), 5).astype(int))
    fluctuations = []
    for scale in scales:
        n_segments = n // scale
        if n_segments == 0:
            continue
        segment_rms = []
        for i in range(n_segments):
            segment = y[i * scale : (i + 1) * scale]
            t = np.arange(scale)
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
    poly = np.polyfit(np.log(scales[:len(fluctuations)]), np.log(np.maximum(fluctuations, 1e-6)), 1)
    return max(0.01, min(0.99, float(poly[0])))


def compute_bipower_variation(returns: np.ndarray) -> Tuple[float, float]:
    """Computes Continuous Volatility and Jump Standard Deviation."""
    if len(returns) < 10:
        return (float(np.std(returns)) if len(returns) > 1 else 0.02), 0.0
    r = returns[-20:]
    rv = float(np.sum(r ** 2))
    abs_r = np.abs(r)
    bv = float((math.pi / 2.0) * (len(r) / (len(r) - 1)) * np.sum(abs_r[1:] * abs_r[:-1]))
    jump_var = max(0.0, rv - bv)
    continuous_vol = math.sqrt(max(1e-6, bv / len(r)))
    jump_std = math.sqrt(max(0.0, jump_var / len(r)))
    return continuous_vol, jump_std


def compute_fast_clenow_momentum(close_series: pd.Series, window: int = 90) -> Tuple[pd.Series, pd.Series]:
    """
    Computes Andreas Clenow Exponential Momentum (Annualized Slope) and R-Squared Smoothness.
    Vectorized via linear convolution: ln(P_t) = alpha + beta * t.
    """
    n = len(close_series)
    if n < window:
        return pd.Series(0.0, index=close_series.index), pd.Series(0.0, index=close_series.index)

    c_vals = np.maximum(0.1, np.nan_to_num(close_series.values, nan=100.0))
    log_c = np.log(c_vals)
    w = window
    weights = np.arange(w) - (w - 1) / 2.0
    s_tt = w * (w * w - 1) / 12.0

    # Fast convolutions
    s_yt = np.convolve(log_c, weights[::-1], mode='valid')
    ones = np.ones(w)
    sum_y = np.convolve(log_c, ones, mode='valid')
    sum_y2 = np.convolve(log_c ** 2, ones, mode='valid')
    s_yy = np.maximum(1e-9, sum_y2 - (sum_y ** 2) / w)

    beta = s_yt / s_tt
    ann_slope = (np.exp(beta * 252.0) - 1.0) * 100.0

    # R^2 = S_yt^2 / (S_tt * S_yy)
    r2 = (s_yt ** 2) / np.maximum(1e-9, s_tt * s_yy)
    r2 = np.clip(r2, 0.0, 1.0)

    # Pad prefix so length matches close_series
    pad_len = n - len(ann_slope)
    full_slope = np.concatenate([np.zeros(pad_len), ann_slope])
    full_r2 = np.concatenate([np.zeros(pad_len), r2])

    return (
        pd.Series(full_slope, index=close_series.index),
        pd.Series(full_r2, index=close_series.index)
    )


def load_5year_data(db_path: Path):
    t0 = time.time()
    conn = sqlite3.connect(str(db_path))

    # Benchmark NIFTY 50
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

    mkt_map = {
        r['date']: {
            'close': r['close'],
            'ema_50': r['ema_50'],
            'ema_21': r['ema_21'],
            'mom_3d': r['mom_3d'],
            'is_bull': bool(r['is_bull'])
        }
        for _, r in nifty_df.iterrows()
    }
    trading_dates = nifty_df['date'].tolist()

    # Stock Data
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
        if len(g) < 95:
            continue
        g = g.sort_values('date').reset_index(drop=True)
        c = g['close']
        h = g['high']
        l = g['low']
        v = g['volume']

        # Log Returns & Dollar Volume
        log_ret = np.log(c / c.shift(1).replace(0, np.nan)).fillna(0.0)
        g['log_return'] = log_ret
        g['log_dollar_vol'] = np.log(c * v + 1.0)
        mean_ldv = g['log_dollar_vol'].rolling(60, min_periods=20).mean()
        std_ldv = g['log_dollar_vol'].rolling(60, min_periods=20).std().replace(0, 1.0)
        g['z_log_dollar_vol'] = (g['log_dollar_vol'] - mean_ldv) / std_ldv

        # Moving Averages
        g['ema_9'] = c.ewm(span=9, adjust=False).mean()
        g['ema_21'] = c.ewm(span=21, adjust=False).mean()
        g['ema_50'] = c.ewm(span=50, adjust=False).mean()
        g['ema_200'] = c.ewm(span=200, adjust=False).mean()

        # ATR
        hl = h - l
        hc = (h - c.shift(1)).abs()
        lc = (l - c.shift(1)).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        g['atr_14'] = tr.rolling(14, min_periods=14).mean().fillna(c * 0.02)

        # Multi-Lookback Momentum
        g['mom_1m'] = ((c - c.shift(20)) / c.shift(20) * 100.0).fillna(0.0)
        g['mom_3m'] = ((c - c.shift(60)) / c.shift(60) * 100.0).fillna(0.0)
        g['mom_6m'] = ((c - c.shift(126)) / c.shift(126) * 100.0).fillna(0.0)

        # RSIs (14-day and Connors 2-day)
        delta = c.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14, min_periods=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14, min_periods=14).mean()
        rs = gain / loss.replace(0, 0.0001)
        g['rsi_14'] = 100.0 - (100.0 / (1.0 + rs)).fillna(50.0)

        gain2 = (delta.where(delta > 0, 0)).rolling(2, min_periods=2).mean()
        loss2 = (-delta.where(delta < 0, 0)).rolling(2, min_periods=2).mean()
        rs2 = gain2 / loss2.replace(0, 0.0001)
        g['rsi_2'] = 100.0 - (100.0 / (1.0 + rs2)).fillna(50.0)

        # Clenow 90-Day Exponential Momentum & R^2
        ann_slope, r2_val = compute_fast_clenow_momentum(c, window=90)
        g['clenow_slope'] = ann_slope
        g['clenow_r2'] = r2_val
        g['clenow_score'] = ann_slope * r2_val

        # Precompute Rolling Hurst & JEV
        n_rows = len(g)
        hurst_arr = np.full(n_rows, 0.5)
        jump_std_arr = np.full(n_rows, 0.0)
        log_ret_vals = log_ret.values
        
        for idx in range(60, n_rows, 3):
            window_ret = log_ret_vals[idx - 60 : idx]
            h_val = compute_hurst_exponent_dfa(window_ret)
            _, j_std = compute_bipower_variation(window_ret)
            hurst_arr[idx : min(idx + 3, n_rows)] = h_val
            jump_std_arr[idx : min(idx + 3, n_rows)] = j_std

        g['hurst_60'] = hurst_arr
        g['jump_std_20'] = jump_std_arr

        stock_dfs[sym] = g.set_index('date')

    logger.info(f"Loaded {len(stock_dfs)} stocks in {time.time()-t0:.2f}s")
    return mkt_map, trading_dates, stock_dfs


def run_verification_simulation(
    trading_dates: List[date],
    stock_dfs: Dict[str, pd.DataFrame],
    mkt_map: Dict[date, Any],
    variant_name: str,
    tier1_mult: float = 1.5,
    tier1_ratio: float = 0.333,
    use_clenow_gate: bool = False,
    min_clenow_r2: float = 0.45,
    min_clenow_slope: float = 15.0,
    instant_be_at_t1: bool = True,
    use_jev_downsizing: bool = True,
    initial_capital: float = 500000.0,
    start_date: date = date(2021, 9, 27),
    end_date: date = date(2026, 9, 25)
) -> Dict[str, Any]:
    """Runs high-precision 5-year simulation targeting >50% win rate."""
    filtered_dates = [d for d in trading_dates if start_date <= d <= end_date]
    if not filtered_dates:
        return {}

    max_slots = 3
    # Dynamic Tiers based on tier1_mult
    tiers = [(tier1_mult, tier1_ratio), (2.8, 0.333), (8.0, 0.334)]

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

            # Stop Loss Trigger
            if l <= pos['stop_loss']:
                exit_price = min(pos['stop_loss'], float(row['open']))
                rem_pnl = (exit_price - pos['avg_price']) * pos['shares']
                total_trade_pnl = pos['harvested_pnl'] + rem_pnl
                total_invested = pos['total_invested']
                pnl_pct = (total_trade_pnl / max(1.0, total_invested)) * 100.0
                cash += pos['shares'] * exit_price
                closed_trades.append({
                    'symbol': sym,
                    'pnl': total_trade_pnl,
                    'pnl_pct': pnl_pct,
                    'hold_days': (curr_d - pos['entry_date']).days,
                    'outcome': 'SL_HIT' if total_trade_pnl <= 0 else 'PROFITABLE_EXIT'
                })
                del open_positions[sym]
                continue

            # Winner Pyramiding (+4.0% gain -> Add +50% size)
            if not pos['pyramided'] and h >= pos['entry_price'] * 1.04:
                add_shares = int(pos['original_shares'] * 0.5)
                add_cost = add_shares * c
                if cash >= add_cost and add_shares > 0:
                    cash -= add_cost
                    pos['shares'] += add_shares
                    pos['total_invested'] += add_cost
                    pos['avg_price'] = (pos['avg_price'] * (pos['shares'] - add_shares) + add_cost) / pos['shares']
                    pos['stop_loss'] = max(pos['stop_loss'], pos['entry_price'] * 1.002)
                    pos['pyramided'] = True

            # Dynamic Tier Harvesting
            cur_tier = pos['tier_idx']
            if cur_tier < len(tiers) - 1:
                tier_mult, trim_ratio = tiers[cur_tier]
                if h >= pos['entry_price'] + (tier_mult * atr):
                    trim_shares = int(pos['original_shares'] * trim_ratio)
                    if trim_shares > 0 and pos['shares'] > trim_shares:
                        t_price = pos['entry_price'] + (tier_mult * atr)
                        trim_proceeds = trim_shares * t_price
                        trim_pnl = (t_price - pos['avg_price']) * trim_shares
                        cash += trim_proceeds
                        pos['harvested_pnl'] += trim_pnl
                        pos['shares'] -= trim_shares
                        pos['tier_idx'] += 1
                        
                        # At Tier 1 harvest, instantly lock Breakeven + small buffer
                        if instant_be_at_t1:
                            pos['stop_loss'] = max(pos['stop_loss'], pos['entry_price'] * 1.002)
                        else:
                            pos['stop_loss'] = max(pos['stop_loss'], pos['entry_price'] + (cur_tier * 0.5 * atr))
            else:
                # Runner Moonbag Tier (Chandelier trailing stop)
                highest_since = pos.get('highest_close', c)
                if c > highest_since:
                    pos['highest_close'] = c
                chand_stop = pos['highest_close'] - (2.5 * atr)
                pos['stop_loss'] = max(pos['stop_loss'], chand_stop)

                upper_mult = tiers[-1][0]
                if h >= pos['entry_price'] + (upper_mult * atr):
                    cash += pos['shares'] * c
                    rem_pnl = (c - pos['avg_price']) * pos['shares']
                    total_trade_pnl = pos['harvested_pnl'] + rem_pnl
                    pnl_pct = (total_trade_pnl / max(1.0, pos['total_invested'])) * 100.0
                    closed_trades.append({
                        'symbol': sym,
                        'pnl': total_trade_pnl,
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

        # 3. Candidate Screening & Entry
        needed_slots = active_allowed_slots - len(open_positions)
        if needed_slots > 0 and (cash + cash_liquidbees) > 20000:
            if cash_liquidbees > 0:
                cash += cash_liquidbees
                cash_liquidbees = 0.0

            # Dynamic Fractional Kelly Sizing
            recent_closed = closed_trades[-30:] if len(closed_trades) >= 10 else []
            if len(recent_closed) >= 10:
                w = [t['pnl'] for t in recent_closed if t['pnl'] > 0]
                l = [abs(t['pnl']) for t in recent_closed if t['pnl'] <= 0]
                p = len(w) / len(recent_closed)
                b = (np.mean(w) / max(1.0, np.mean(l))) if (w and l) else 2.5
            else:
                p = 0.45
                b = 2.5
            f_star = (p * b - (1.0 - p)) / max(0.1, b)
            k_frac = max(0.20, min(0.333, (f_star * 0.4) + 0.15))
            slot_capital = total_equity * k_frac

            candidates = []
            for sym, df_s in stock_dfs.items():
                if sym in open_positions or curr_d not in df_s.index:
                    continue

                row = df_s.loc[curr_d]
                cp = float(row['close'])
                op = float(row['open'])
                lp = float(row['low'])
                e21 = float(row['ema_21'])
                e50 = float(row['ema_50'])
                e200 = float(row['ema_200'])
                rsi = float(row['rsi_14'])
                rsi2 = float(row['rsi_2'])
                atr = float(row['atr_14'])
                hurst = float(row['hurst_60'])
                z_ldv = float(row['z_log_dollar_vol'])
                j_std = float(row['jump_std_20'])
                cl_slope = float(row['clenow_slope'])
                cl_r2 = float(row['clenow_r2'])
                cl_score = float(row['clenow_score'])

                if cp < 30 or atr <= 0:
                    continue

                # 1. Macro Trend Alignment & Persistence
                if not (cp >= e50 >= e200 * 0.98 and hurst > 0.51):
                    continue

                # 2. Clenow Exponential Trend Smoothness Gate
                if use_clenow_gate:
                    if cl_r2 < min_clenow_r2 or cl_slope < min_clenow_slope:
                        continue

                # 3. Log Dollar Volume Liquidity Gate
                if z_ldv < 0.15:
                    continue

                # 4. Pullback Mean-Reversion Trigger
                is_pullback = (rsi2 <= 38.0) or (lp <= e21 * 1.015 and cp >= e21 * 0.98) or (rsi <= 50.0)
                is_reversal = (cp >= op) or (cp >= e21)
                if not (is_pullback and is_reversal):
                    continue

                ranking_score = cl_score if use_clenow_gate else (0.4 * row['mom_6m'] + 0.35 * row['mom_3m'] + 0.25 * row['mom_1m'])
                candidates.append((sym, ranking_score, cp, atr, j_std))

            candidates.sort(key=lambda x: x[1], reverse=True)
            for sym, score, cp, atr, j_std in candidates[:needed_slots]:
                if use_jev_downsizing and j_std > 0.015:
                    downsize = max(0.5, 0.02 / (0.02 + j_std))
                    trade_capital = slot_capital * downsize
                else:
                    trade_capital = slot_capital

                alloc = min(cash * 0.95, trade_capital)
                shares = int(alloc / cp)
                if shares > 0 and cash >= (shares * cp):
                    cost = shares * cp
                    cash -= cost
                    init_sl = cp - (1.75 * atr)

                    open_positions[sym] = {
                        'entry_date': curr_d,
                        'entry_price': cp,
                        'avg_price': cp,
                        'shares': shares,
                        'original_shares': shares,
                        'total_invested': cost,
                        'harvested_pnl': 0.0,
                        'atr': atr,
                        'stop_loss': init_sl,
                        'pyramided': False,
                        'tier_idx': 0,
                        'highest_close': cp
                    }

    # Final Metrics
    final_val = equity_curve[-1] if equity_curve else initial_capital
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
    print("=" * 105)
    print(" 5-YEAR EMPIRICAL VERIFICATION: PUSHING WIN RATE > 50% & PROFIT FACTOR > 2.0x (2021-2026)")
    print("=" * 105)

    mkt_map, trading_dates, stock_dfs = load_5year_data(DB_PATH)

    variants = [
        {
            'name': '1. Previous Best (Pullback + T1 @ 1.5 ATR)',
            'tier1_mult': 1.5,
            'tier1_ratio': 0.333,
            'use_clenow_gate': False,
            'instant_be_at_t1': False,
            'use_jev_downsizing': False
        },
        {
            'name': '2. + Fast T1 Harvest (+1.0x ATR + Instant Breakeven)',
            'tier1_mult': 1.0,
            'tier1_ratio': 0.25,
            'use_clenow_gate': False,
            'instant_be_at_t1': True,
            'use_jev_downsizing': False
        },
        {
            'name': '3. + Clenow R^2 Trend Smoothness Gate (R^2 > 0.45)',
            'tier1_mult': 1.5,
            'tier1_ratio': 0.333,
            'use_clenow_gate': True,
            'min_clenow_r2': 0.45,
            'min_clenow_slope': 15.0,
            'instant_be_at_t1': False,
            'use_jev_downsizing': False
        },
        {
            'name': '4. Clenow Gate + Fast T1 Harvest (+1.0x ATR BE)',
            'tier1_mult': 1.0,
            'tier1_ratio': 0.25,
            'use_clenow_gate': True,
            'min_clenow_r2': 0.45,
            'min_clenow_slope': 15.0,
            'instant_be_at_t1': True,
            'use_jev_downsizing': False
        },
        {
            'name': '5. Apex Quantum Champion: Fast T1 + Clenow + JEV Sizing',
            'tier1_mult': 1.0,
            'tier1_ratio': 0.25,
            'use_clenow_gate': True,
            'min_clenow_r2': 0.45,
            'min_clenow_slope': 15.0,
            'instant_be_at_t1': True,
            'use_jev_downsizing': True
        }
    ]

    results = []
    for var in variants:
        t_start = time.time()
        res = run_verification_simulation(
            trading_dates=trading_dates,
            stock_dfs=stock_dfs,
            mkt_map=mkt_map,
            variant_name=var['name'],
            tier1_mult=var['tier1_mult'],
            tier1_ratio=var['tier1_ratio'],
            use_clenow_gate=var['use_clenow_gate'],
            min_clenow_r2=var.get('min_clenow_r2', 0.45),
            min_clenow_slope=var.get('min_clenow_slope', 15.0),
            instant_be_at_t1=var['instant_be_at_t1'],
            use_jev_downsizing=var['use_jev_downsizing']
        )
        elapsed = time.time() - t_start
        results.append(res)
        print(f"Completed {var['name']} in {elapsed:.2f}s | WinRate: {res['win_rate']}% | PF: {res['profit_factor']}x | CAGR: {res['cagr']}%")

    print("\n" + "=" * 110)
    print(f"{'Strategy Variant':<50} | {'Trades':<6} | {'WinRate':<7} | {'SL Hit':<7} | {'PF':<5} | {'Payoff':<6} | {'CAGR':<6} | {'MaxDD':<6} | {'Calmar':<6}")
    print("-" * 110)
    for r in results:
        print(f"{r['variant']:<50} | {r['trades']:<6} | {r['win_rate']:<6.1f}% | {r['sl_hit_rate']:<6.1f}% | {r['profit_factor']:<4.2f}x | {r['payoff_ratio']:<5.2f}x | {r['cagr']:<5.1f}% | {r['max_dd']:<5.1f}% | {r['calmar']:<5.2f}")
    print("=" * 110)

    output_path = ROOT_DIR / "data" / "verified_quantum_50pct_winrate_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFinal verification report saved to: {output_path}")


if __name__ == "__main__":
    main()
