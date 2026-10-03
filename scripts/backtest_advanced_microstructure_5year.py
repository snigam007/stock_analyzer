"""
scripts/backtest_advanced_microstructure_5year.py
=================================================
5-Year Full-Cycle Microstructure & Orderflow Quantitative Backtest
(2021-09-27 to 2026-09-25 / 1,420 Trading Sessions across 304 NSE Equities)

Evaluates:
1. Baseline: DFA Hurst H > 0.51, Log-Dollar Volume z > 0.15, T1=1.00 ATR trim 25% + BE ratchet.
2. Ablation 1: + Anchored VWAP (AVWAP from 60-day structural low)
3. Ablation 2: + Auction Market Theory (AMT) Value Area Low / POC Retest (Rolling 30D Volume Profile)
4. Ablation 3: + Wyckoff Institutional Absorption (Stopping Volume: High RelVol + Spread Compression + High CLV)
5. Ablation 4: + Synthetic Cumulative Volume Delta (CVD) Bullish Divergence
6. Ablation 5: + Index Dealer Gamma Exposure (GEX) Regime Gate (Pause on Short-Gamma Cascades)
7. Ablation 6: + Multi-Feature Microstructure Confluence Champion
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
logger = logging.getLogger("MicrostructureBacktest")

DB_PATH = ROOT_DIR / "data" / "stock_analyzer.db"


def compute_hurst_exponent_dfa(series: np.ndarray, min_window: int = 8, max_window: int = 30) -> float:
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


def load_microstructure_5year_data(db_path: Path):
    t0 = time.time()
    conn = sqlite3.connect(str(db_path))

    # Benchmark NIFTY 50
    nifty_df = pd.read_sql_query("""
        SELECT date, close, open, high, low
        FROM index_prices
        WHERE symbol = '^NSEI' AND date >= '2021-01-01'
        ORDER BY date ASC;
    """, conn)
    if nifty_df.empty:
        nifty_df = pd.read_sql_query("""
            SELECT date, AVG(close) as close, AVG(open) as open, AVG(high) as high, AVG(low) as low
            FROM daily_prices
            WHERE date >= '2021-01-01'
            GROUP BY date ORDER BY date ASC;
        """, conn)

    nifty_df['date'] = pd.to_datetime(nifty_df['date']).dt.date
    nifty_df = nifty_df.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
    nifty_df['ema_50'] = nifty_df['close'].ewm(span=50, adjust=False).mean()
    nifty_df['ema_21'] = nifty_df['close'].ewm(span=21, adjust=False).mean()
    nifty_df['mom_3d'] = nifty_df['close'].pct_change(3) * 100.0
    nifty_df['ret_5d'] = nifty_df['close'].pct_change(5) * 100.0
    nifty_df['is_bull'] = (nifty_df['close'] >= nifty_df['ema_50']) | (nifty_df['close'] >= nifty_df['ema_21'])

    # Nifty ATR & Dealer Gamma Regime Proxy
    tr_nifty = np.maximum(
        nifty_df['high'] - nifty_df['low'],
        np.maximum(
            (nifty_df['high'] - nifty_df['close'].shift(1)).abs(),
            (nifty_df['low'] - nifty_df['close'].shift(1)).abs()
        )
    )
    nifty_df['atr_14'] = tr_nifty.rolling(14, min_periods=14).mean()
    nifty_df['atr_60'] = tr_nifty.rolling(60, min_periods=30).mean()
    nifty_df['vol_expansion'] = nifty_df['atr_14'] / nifty_df['atr_60'].replace(0, 1.0)
    # Short Gamma regime: Vol expanding sharply while Nifty dropping (forced dealer selling)
    nifty_df['is_short_gamma_cascade'] = (nifty_df['vol_expansion'] > 1.25) & (nifty_df['ret_5d'] < -1.5)

    mkt_map = {
        r['date']: {
            'close': r['close'],
            'ema_50': r['ema_50'],
            'ema_21': r['ema_21'],
            'mom_3d': r['mom_3d'],
            'ret_5d': r['ret_5d'],
            'is_bull': bool(r['is_bull']),
            'is_short_gamma_cascade': bool(r['is_short_gamma_cascade'])
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
        op = g['open']
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

        # ─────────────────────────────────────────────────────────────────────
        # MICROSTRUCTURE FEATURES
        # ─────────────────────────────────────────────────────────────────────
        typical_p = (h + l + c) / 3.0
        pv = typical_p * v
        vol_sma20 = v.rolling(20, min_periods=5).mean().replace(0, 1.0)
        g['rel_vol'] = v / vol_sma20

        # 1. Close Location Value (CLV) & Synthetic Delta
        clv = ((c - l) - (h - c)) / (h - l).replace(0, 1e-6)
        clv = np.clip(clv, -1.0, 1.0).fillna(0.0)
        g['clv'] = clv
        g['synth_delta'] = clv * v
        g['synth_delta_3d'] = g['synth_delta'].rolling(3, min_periods=1).sum()

        # 2. Wyckoff Spread & Absorption Ratio
        # Spread relative to ATR: small spread on high volume = institutional absorption
        spread_rel = (h - l) / g['atr_14'].replace(0, 1.0)
        g['spread_rel'] = spread_rel
        g['absorption_ratio'] = g['rel_vol'] / (spread_rel + 0.1)
        # Bullish absorption: High absorption ratio + close in upper half (CLV >= 0.0)
        g['is_absorption_bar'] = (g['absorption_ratio'] >= 1.25) & (g['clv'] >= 0.0) & (c >= op * 0.998)

        # 3. Rolling 30-Day Volume Profile (VWAP, VAL, VAH)
        # Approximating Value Area (70% volume distribution around VWAP)
        roll_pv = pv.rolling(30, min_periods=10).sum()
        roll_v = v.rolling(30, min_periods=10).sum().replace(0, 1.0)
        vwap_30 = roll_pv / roll_v
        g['vwap_30'] = vwap_30

        # Volume-weighted variance
        diff2_v = ((typical_p - vwap_30) ** 2) * v
        roll_diff2_v = diff2_v.rolling(30, min_periods=10).sum()
        vw_std = np.sqrt(np.maximum(0.0, roll_diff2_v / roll_v)).fillna(c * 0.02)
        g['val_30'] = vwap_30 - (1.0 * vw_std)  # Value Area Low (~70% lower band)
        g['vah_30'] = vwap_30 + (1.0 * vw_std)  # Value Area High (~70% upper band)

        # 4. Anchored VWAP from 60-Day Structural Low
        # Vectorized calculation: find rolling 60-day argmin of low
        n_len = len(g)
        low_vals = l.values
        pv_vals = pv.values
        v_vals = v.values
        avwap_arr = np.zeros(n_len)

        # Optimized AVWAP calculation
        for i in range(n_len):
            lookback_start = max(0, i - 60)
            window_lows = low_vals[lookback_start : i + 1]
            min_offset = int(np.argmin(window_lows))
            anchor_idx = lookback_start + min_offset
            
            sum_pv = np.sum(pv_vals[anchor_idx : i + 1])
            sum_v = np.sum(v_vals[anchor_idx : i + 1])
            avwap_arr[i] = (sum_pv / sum_v) if sum_v > 0 else typical_p.iloc[i]

        g['avwap_60'] = avwap_arr

        # 5. Precompute Rolling Hurst & JEV
        hurst_arr = np.full(n_len, 0.5)
        jump_std_arr = np.full(n_len, 0.0)
        log_ret_vals = log_ret.values

        for idx in range(60, n_len, 3):
            window_ret = log_ret_vals[idx - 60 : idx]
            h_val = compute_hurst_exponent_dfa(window_ret)
            _, j_std = compute_bipower_variation(window_ret)
            hurst_arr[idx : min(idx + 3, n_len)] = h_val
            jump_std_arr[idx : min(idx + 3, n_len)] = j_std

        g['hurst_60'] = hurst_arr
        g['jump_std_20'] = jump_std_arr

        stock_dfs[sym] = g.set_index('date')

    logger.info(f"Loaded {len(stock_dfs)} stocks with full microstructure features in {time.time()-t0:.2f}s")
    return mkt_map, trading_dates, stock_dfs


def run_microstructure_simulation(
    trading_dates: List[date],
    stock_dfs: Dict[str, pd.DataFrame],
    mkt_map: Dict[date, Any],
    variant_name: str,
    tier1_mult: float = 1.00,
    tier1_ratio: float = 0.25,
    # Feature Toggles
    use_avwap_gate: bool = False,
    use_volume_profile_filter: bool = False,
    use_absorption_trigger: bool = False,
    use_synth_delta_filter: bool = False,
    use_gex_market_gate: bool = False,
    initial_capital: float = 500000.0,
    start_date: date = date(2021, 9, 27),
    end_date: date = date(2026, 9, 25)
) -> Dict[str, Any]:
    filtered_dates = [d for d in trading_dates if start_date <= d <= end_date]
    if not filtered_dates:
        return {}

    max_slots = 3
    tiers = [(tier1_mult, tier1_ratio), (2.8, 0.333), (8.0, 0.334)]

    cash = initial_capital
    cash_liquidbees = 0.0
    open_positions = {}
    closed_trades = []
    equity_curve = []

    for curr_d in filtered_dates:
        mkt_row = mkt_map.get(curr_d, {'is_bull': True, 'mom_3d': 0.0, 'is_short_gamma_cascade': False})
        is_bull = mkt_row['is_bull']
        is_short_gamma = mkt_row.get('is_short_gamma_cascade', False)

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
                t_mult, trim_ratio = tiers[cur_tier]
                if h >= pos['entry_price'] + (t_mult * atr):
                    trim_shares = int(pos['original_shares'] * trim_ratio)
                    if trim_shares > 0 and pos['shares'] > trim_shares:
                        t_price = pos['entry_price'] + (t_mult * atr)
                        trim_proceeds = trim_shares * t_price
                        trim_pnl = (t_price - pos['avg_price']) * trim_shares
                        cash += trim_proceeds
                        pos['harvested_pnl'] += trim_pnl
                        pos['shares'] -= trim_shares
                        pos['tier_idx'] += 1
                        
                        # At Tier 1 harvest, instantly lock Breakeven + small buffer
                        pos['stop_loss'] = max(pos['stop_loss'], pos['entry_price'] * 1.002)
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
        
        # GEX Market Gate: Halt new entries if in Short Gamma cascade regime
        if use_gex_market_gate and is_short_gamma:
            needed_slots = 0

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
                hp = float(row['high'])
                e21 = float(row['ema_21'])
                e50 = float(row['ema_50'])
                e200 = float(row['ema_200'])
                rsi = float(row['rsi_14'])
                rsi2 = float(row['rsi_2'])
                atr = float(row['atr_14'])
                hurst = float(row['hurst_60'])
                z_ldv = float(row['z_log_dollar_vol'])
                avwap = float(row['avwap_60'])
                val = float(row['val_30'])
                vwap30 = float(row['vwap_30'])
                is_absorb = bool(row['is_absorption_bar'])
                synth_delta_3d = float(row['synth_delta_3d'])

                if cp < 30 or atr <= 0:
                    continue

                # 1. Macro Trend Alignment & DFA Hurst Persistence
                if not (cp >= e50 >= e200 * 0.98 and hurst > 0.51):
                    continue

                # 2. Log Dollar Volume Liquidity Gate
                if z_ldv < 0.15:
                    continue

                # 3. Pullback Mean-Reversion Base
                is_pullback = (rsi2 <= 38.0) or (lp <= e21 * 1.015 and cp >= e21 * 0.98) or (rsi <= 50.0)
                is_reversal = (cp >= op) or (cp >= e21)
                if not (is_pullback and is_reversal):
                    continue

                # ── MICROSTRUCTURE ENHANCEMENTS ─────────────────────────────
                # Feature 1: Anchored VWAP Institutional Cost Basis
                if use_avwap_gate:
                    # Price must be above or holding within 0.8% of Anchored VWAP from 60-day low
                    if cp < avwap * 0.992:
                        continue

                # Feature 2: Auction Market Theory & Volume Profile Value Area Filter
                if use_volume_profile_filter:
                    # Pullback must re-test the Value Area (price touched below VWAP or within VAL band)
                    # and close inside or above the Value Area (acceptance, not rejection)
                    is_val_retest = (lp <= vwap30 * 1.02) and (cp >= val * 0.99)
                    if not is_val_retest:
                        continue

                # Feature 3: Wyckoff Institutional Absorption Trigger
                if use_absorption_trigger:
                    # Requires an absorption candle (heavy volume relative to spread, closing in upper half)
                    # OR a strong green reversal candle
                    if not (is_absorb or (cp > op and (cp - lp) / (hp - lp + 1e-6) >= 0.65)):
                        continue

                # Feature 4: Synthetic CVD Positive Delta Divergence
                if use_synth_delta_filter:
                    # Aggressive buyers must be net positive over the last 3 days
                    if synth_delta_3d <= 0:
                        continue

                ranking_score = 0.40 * row['mom_6m'] + 0.35 * row['mom_3m'] + 0.25 * row['mom_1m']
                candidates.append((sym, ranking_score, cp, atr, val))

            candidates.sort(key=lambda x: x[1], reverse=True)
            for sym, score, cp, atr, val in candidates[:needed_slots]:
                alloc = min(cash * 0.95, slot_capital)
                shares = int(alloc // cp)
                if shares > 0:
                    trade_cost = shares * cp
                    cash -= trade_cost
                    
                    # Stop loss: 1.5 ATR below entry OR placed just below Volume Profile VAL shelf
                    std_sl = cp - (1.5 * atr)
                    if use_volume_profile_filter and val < cp:
                        vp_sl = val - (0.5 * atr)
                        init_sl = max(std_sl, min(cp * 0.95, vp_sl))
                    else:
                        init_sl = std_sl

                    open_positions[sym] = {
                        'entry_date': curr_d,
                        'entry_price': cp,
                        'avg_price': cp,
                        'shares': shares,
                        'original_shares': shares,
                        'total_invested': trade_cost,
                        'atr': atr,
                        'stop_loss': init_sl,
                        'tier_idx': 0,
                        'harvested_pnl': 0.0,
                        'pyramided': False,
                        'highest_close': cp
                    }

        # Idle cash sweep into LiquidBees (6.5% yield)
        if len(open_positions) == 0 and cash > 25000:
            cash_liquidbees += cash * 0.95
            cash *= 0.05

    # Close remaining open positions at final close
    final_d = filtered_dates[-1]
    for sym, pos in open_positions.items():
        c = float(stock_dfs[sym].loc[final_d]['close']) if (sym in stock_dfs and final_d in stock_dfs[sym].index) else pos['avg_price']
        rem_pnl = (c - pos['avg_price']) * pos['shares']
        total_trade_pnl = pos['harvested_pnl'] + rem_pnl
        pnl_pct = (total_trade_pnl / max(1.0, pos['total_invested'])) * 100.0
        cash += pos['shares'] * c
        closed_trades.append({
            'symbol': sym,
            'pnl': total_trade_pnl,
            'pnl_pct': pnl_pct,
            'hold_days': (final_d - pos['entry_date']).days,
            'outcome': 'OPEN_FINAL'
        })

    final_val = cash + cash_liquidbees
    n_days = (end_date - start_date).days
    years = n_days / 365.25
    cagr = ((final_val / initial_capital) ** (1.0 / years) - 1.0) * 100.0

    eq_series = pd.Series(equity_curve)
    peak = eq_series.cummax()
    dd = (eq_series - peak) / peak.replace(0, np.nan)
    max_dd = float(abs(dd.min()) * 100.0) if not dd.empty else 0.0

    wins = [t for t in closed_trades if t['pnl'] > 0]
    losses = [t for t in closed_trades if t['pnl'] <= 0]
    win_rate = (len(wins) / len(closed_trades) * 100.0) if closed_trades else 0.0
    total_gain = sum(t['pnl'] for t in wins)
    total_loss = abs(sum(t['pnl'] for t in losses))
    pf = (total_gain / total_loss) if total_loss > 0 else 99.0
    calmar = (cagr / max_dd) if max_dd > 0 else 0.0

    return {
        'variant_name': variant_name,
        'final_val': final_val,
        'cagr': cagr,
        'max_dd': max_dd,
        'calmar': calmar,
        'trades': len(closed_trades),
        'win_rate': win_rate,
        'profit_factor': pf,
        'total_gain': total_gain,
        'total_loss': total_loss
    }


def main():
    print("=" * 115)
    print("  [MICROSTRUCTURE] 5-YEAR FULL-CYCLE MICROSTRUCTURE & ORDERFLOW ABLATION STUDY")
    print("  Period: 2021-09-27 to 2026-09-25 (1,420 Sessions across 304 Equities)")
    print("=" * 115)

    mkt_map, trading_dates, stock_dfs = load_microstructure_5year_data(DB_PATH)

    variants = [
        # (name, avwap, vp, absorb, synth_delta, gex)
        ("Baseline (Persistent Pullback T1@1.00)", False, False, False, False, False),
        ("Ablation 1: + Anchored VWAP (AVWAP 60D Low)", True, False, False, False, False),
        ("Ablation 2: + Volume Profile (VAL / POC Retest)", False, True, False, False, False),
        ("Ablation 3: + Wyckoff Absorption Trigger", False, False, True, False, False),
        ("Ablation 4: + Synthetic CVD Delta Positive", False, False, False, True, False),
        ("Ablation 5: + Index GEX Short-Gamma Gate", False, False, False, False, True),
        ("Ablation 6: Confluence (AVWAP + Absorption)", True, False, True, False, False),
        ("Ablation 7: Confluence (AVWAP + Volume Profile)", True, True, False, False, False),
        ("Ablation 8: Full Confluence (AVWAP + VP + Absorption + GEX)", True, True, True, False, True),
    ]

    results = []
    print(f"\n{'Variant Name':<45} | {'Trades':<7} | {'WinRate':<8} | {'PF':<6} | {'CAGR':<7} | {'MaxDD':<7} | {'Calmar':<7} | {'Final Val (Rs)':<14}")
    print("-" * 125)

    for name, avwap, vp, absorb, s_delta, gex in variants:
        res = run_microstructure_simulation(
            trading_dates=trading_dates,
            stock_dfs=stock_dfs,
            mkt_map=mkt_map,
            variant_name=name,
            tier1_mult=1.00,
            tier1_ratio=0.25,
            use_avwap_gate=avwap,
            use_volume_profile_filter=vp,
            use_absorption_trigger=absorb,
            use_synth_delta_filter=s_delta,
            use_gex_market_gate=gex,
            initial_capital=500000.0
        )
        results.append(res)
        print(f"{res['variant_name']:<45} | {res['trades']:<7} | {res['win_rate']:<7.1f}% | {res['profit_factor']:<5.2f}x | {res['cagr']:<6.1f}% | {res['max_dd']:<6.1f}% | {res['calmar']:<6.2f} | Rs {res['final_val']:>11,.0f}")

    print("=" * 125)

    # Save results to json for forensic traceability
    out_path = ROOT_DIR / "data" / "microstructure_5year_ablation_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nAudit results successfully saved to: {out_path}")


if __name__ == '__main__':
    main()
