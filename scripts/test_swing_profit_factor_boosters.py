"""
scripts/test_swing_profit_factor_boosters.py
============================================
Evaluates architectural levers to boost Swing Profit Factor from 1.07x up to 1.5x - 2.0x+:
1. Volume Expansion Gate (V >= 1.0x / 1.3x 20-day Volume SMA)
2. 200-EMA Positive Trend Slope (Prevents counter-trend or sideways traps)
3. Sector Orthogonal Shield (Max 1 active swing trade per sector)
4. Fast Profit Lock T1 (+1.2x ATR vs +1.5x ATR)
"""

import sys
import os
import time
import math
import sqlite3
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Any, Optional

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from scripts.audit_true_quantum_champions_5year import (
    load_fast_5year_market_and_stocks,
    FastMarketRegimeRow
)

DB_PATH = ROOT_DIR / "data" / "stock_analyzer.db"


def run_swing_booster_simulation(
    trading_dates,
    stock_dfs,
    mkt_map,
    stock_sector_map,
    initial_capital=500000.0,
    start_date=None,
    end_date=None,
    volume_mult=None,          # e.g. 1.0 or 1.25 or None
    require_ema200_rising=False,
    max_trades_per_sector=None,# e.g. 1 or None
    t1_mult=1.5                # 1.5 or 1.2
):
    filtered_dates = [d for d in trading_dates if (start_date is None or d >= start_date) and (end_date is None or d <= end_date)]
    if not filtered_dates:
        return {}

    max_slots = 3
    bear_fortress_active = True
    tiers = [(t1_mult, 0.333), (3.0, 0.333), (8.5, 0.334)]

    cash = initial_capital
    cash_liquidbees = 0.0
    open_positions = {}
    closed_trades = []
    equity_curve = []

    for curr_d in filtered_dates:
        mkt_row = mkt_map.get(curr_d)
        is_bull = mkt_row.is_bull if mkt_row else True
        active_allowed_slots = 1 if (bear_fortress_active and not is_bull) else max_slots

        # Yield on LiquidBees
        if cash_liquidbees > 0:
            cash_liquidbees += cash_liquidbees * (0.065 / 365.0)

        # 1. Manage Open Positions
        for sym, pos in list(open_positions.items()):
            df_s = stock_dfs.get(sym)
            if df_s is None or curr_d not in df_s.index:
                continue

            row = df_s.loc[curr_d]
            h = float(row['high'])
            l = float(row['low'])
            c = float(row['close'])
            atr = pos['atr']
            holding_days = (curr_d - pos['entry_date']).days

            # Stop Loss Hit
            if l <= pos['stop_loss']:
                exit_price = min(pos['stop_loss'], float(row['open']))
                pnl = (exit_price - pos['avg_price']) * pos['shares']
                pnl_pct = (exit_price - pos['avg_price']) / pos['avg_price'] * 100.0
                cash += pos['shares'] * exit_price
                closed_trades.append({
                    'symbol': sym, 'pnl': pnl, 'pnl_pct': pnl_pct,
                    'hold_days': holding_days,
                    'outcome': 'SL_HIT' if pnl <= 0 else 'TRAILING_SL_HIT'
                })
                del open_positions[sym]
                continue

            # 15-Day Stale Momentum Rotation
            if holding_days >= 15 and not pos['pyramided'] and pos['tier_idx'] == 0:
                if h < pos['entry_price'] + (1.0 * atr):
                    exit_price = c
                    pnl = (exit_price - pos['avg_price']) * pos['shares']
                    pnl_pct = (exit_price - pos['avg_price']) / pos['avg_price'] * 100.0
                    cash += pos['shares'] * exit_price
                    closed_trades.append({
                        'symbol': sym, 'pnl': pnl, 'pnl_pct': pnl_pct,
                        'hold_days': holding_days,
                        'outcome': 'STALE_ROTATION'
                    })
                    del open_positions[sym]
                    continue

            # Winner Pyramiding (+4.0% gain -> Add +50% size, ratchets SL to Breakeven)
            if not pos['pyramided'] and h >= pos['entry_price'] * 1.04:
                add_shares = int(pos['original_shares'] * 0.5)
                add_cost = add_shares * c
                if cash >= add_cost and add_shares > 0:
                    cash -= add_cost
                    pos['shares'] += add_shares
                    pos['avg_price'] = (pos['avg_price'] * (pos['shares'] - add_shares) + add_cost) / pos['shares']
                    pos['stop_loss'] = pos['entry_price'] * 1.002
                    pos['pyramided'] = True

            # Dynamic Tier Exits
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
                # Final Runner Tier
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
                        'symbol': sym, 'pnl': pnl, 'pnl_pct': pnl_pct,
                        'hold_days': holding_days,
                        'outcome': 'T3_MOONBAG'
                    })
                    del open_positions[sym]
                    continue

        # 2. Portfolio Equity Check (Pre-Entry)
        cur_pos_val = sum(
            pos['shares'] * float(stock_dfs[sym].loc[curr_d]['close']) if (sym in stock_dfs and curr_d in stock_dfs[sym].index) else pos['shares'] * pos['avg_price']
            for sym, pos in open_positions.items()
        )
        total_equity = cash + cash_liquidbees + cur_pos_val
        equity_curve.append(total_equity)

        # 3. Check for New Entries
        needed_slots = active_allowed_slots - len(open_positions)
        if needed_slots > 0 and (cash + cash_liquidbees) > 20000:
            if cash_liquidbees > 0:
                cash += cash_liquidbees
                cash_liquidbees = 0.0

            # Rolling Half-Kelly Calculation
            recent_closed = closed_trades[-30:] if len(closed_trades) >= 10 else []
            if len(recent_closed) >= 10:
                w_trades = [t['pnl'] for t in recent_closed if t['pnl'] > 0]
                l_trades = [abs(t['pnl']) for t in recent_closed if t['pnl'] <= 0]
                p_win = len(w_trades) / len(recent_closed)
                b_payoff = (np.mean(w_trades) / max(1.0, np.mean(l_trades))) if (w_trades and l_trades) else 3.0
            else:
                p_win = 0.30
                b_payoff = 3.0
            f_star = (p_win * b_payoff - (1.0 - p_win)) / max(0.1, b_payoff)
            half_k_frac = max(0.22, min(0.333, (f_star * 0.5) + 0.15))
            slot_capital = total_equity * half_k_frac

            # Active sectors in open positions
            open_sectors = {stock_sector_map.get(s, "General") for s in open_positions}

            candidates = []
            for sym, df_s in stock_dfs.items():
                if sym in open_positions:
                    continue
                sym_sec = stock_sector_map.get(sym, "General")
                if max_trades_per_sector is not None and sym_sec in open_sectors:
                    continue

                if curr_d in df_s.index:
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
                    vol = float(row['volume']) if 'volume' in row else 0.0
                    vol_sma = float(row['vol_sma20']) if 'vol_sma20' in row else 1.0

                    if cp < 30 or atr <= 0:
                        continue

                    # Volume Filter Check
                    if volume_mult is not None and vol < (vol_sma * volume_mult):
                        continue

                    # 200 EMA Slope Check
                    if require_ema200_rising:
                        e200_prev = float(row['ema_200_prev20']) if 'ema_200_prev20' in row else e200
                        if e200 < e200_prev:
                            continue

                    # Multi-Lookback Momentum Screen
                    if (cp >= e50 >= e200 * 0.98) and (m1 > 0 and m3 > 0 and m6 > 10.0) and (45.0 <= rsi <= 72.0):
                        candidates.append((sym, score, cp, atr, sym_sec))

            candidates.sort(key=lambda x: x[1], reverse=True)
            for sym, score, cp, atr, sym_sec in candidates[:needed_slots]:
                alloc = min(cash * 0.95, slot_capital)
                shares = int(alloc / cp)
                if shares > 0 and cash >= (shares * cp):
                    cost = shares * cp
                    cash -= cost
                    init_sl = cp - (2.0 * atr)
                    open_positions[sym] = {
                        'entry_date': curr_d,
                        'entry_price': cp,
                        'avg_price': cp,
                        'shares': shares,
                        'original_shares': shares,
                        'stop_loss': init_sl,
                        'atr': atr,
                        'tier_idx': 0,
                        'pyramided': False,
                        'highest_close': cp
                    }
                    open_sectors.add(sym_sec)

        # 4. Fortress Cash Sweep if slots restricted
        if bear_fortress_active and not is_bull and len(open_positions) <= 1 and cash > 50000:
            sweep_amt = cash * 0.70
            cash -= sweep_amt
            cash_liquidbees += sweep_amt

    # Liquidate remaining open positions at end
    last_d = filtered_dates[-1]
    for sym, pos in list(open_positions.items()):
        c_price = pos['avg_price']
        if sym in stock_dfs and last_d in stock_dfs[sym].index:
            c_price = float(stock_dfs[sym].loc[last_d]['close'])
        cash += pos['shares'] * c_price
        pnl = (c_price - pos['avg_price']) * pos['shares']
        pnl_pct = (c_price - pos['avg_price']) / pos['avg_price'] * 100.0
        closed_trades.append({'symbol': sym, 'pnl': pnl, 'pnl_pct': pnl_pct, 'hold_days': (last_d - pos['entry_date']).days, 'outcome': 'AUDIT_END'})

    final_val = cash + cash_liquidbees
    tot_days = (filtered_dates[-1] - filtered_dates[0]).days
    cagr = ((final_val / initial_capital) ** (365.0 / max(1, tot_days)) - 1.0) * 100.0

    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak: peak = v
        dd = (peak - v) / peak * 100.0
        if dd > max_dd: max_dd = dd

    wins = [t for t in closed_trades if t['pnl'] > 0]
    losses = [t for t in closed_trades if t['pnl'] <= 0]
    win_rate = len(wins) / max(1, len(closed_trades)) * 100.0
    tot_profit = sum(t['pnl'] for t in wins)
    tot_loss = abs(sum(t['pnl'] for t in losses))
    pf = tot_profit / max(1.0, tot_loss)
    avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0.0
    avg_loss = abs(np.mean([t['pnl'] for t in losses])) if losses else 1.0
    payoff = avg_win / max(1.0, avg_loss)
    calmar = cagr / max(0.1, max_dd)

    return {
        "final_val": round(final_val, 2),
        "cagr": round(cagr, 2),
        "multiple": round(final_val / initial_capital, 2),
        "max_dd": round(max_dd, 2),
        "calmar": round(calmar, 2),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(pf, 2),
        "payoff_ratio": round(payoff, 2),
        "total_trades": len(closed_trades),
        "gross_profit": round(tot_profit, 2),
        "gross_loss": round(tot_loss, 2)
    }


def run_experiment():
    t0 = time.time()
    mkt_map, trading_dates, stock_dfs = load_fast_5year_market_and_stocks(DB_PATH)
    start_d = date(2021, 9, 27)
    end_d = date(2026, 9, 25)

    # Precompute volume SMA and 200 EMA slope on each stock dataframe
    conn = sqlite3.connect(str(DB_PATH))
    sec_df = pd.read_sql_query("SELECT symbol, sector FROM stocks", conn)
    conn.close()
    stock_sec_map = dict(zip(sec_df['symbol'], sec_df['sector']))

    for sym, df_s in stock_dfs.items():
        if 'volume' in df_s.columns:
            df_s['vol_sma20'] = df_s['volume'].rolling(20, min_periods=5).mean().fillna(df_s['volume'])
        else:
            df_s['vol_sma20'] = 1.0
        df_s['ema_200_prev20'] = df_s['ema_200'].shift(20).fillna(df_s['ema_200'])

    candidates = [
        ("Current Champion (Half-Kelly + 15D Stale Rotation)", {}),
        ("Booster 1: Volume Filter (Vol >= 1.0x 20D SMA)", {"volume_mult": 1.0}),
        ("Booster 2: Volume Surge (Vol >= 1.25x 20D SMA)", {"volume_mult": 1.25}),
        ("Booster 3: Rising 200-EMA Macro Trend Filter", {"require_ema200_rising": True}),
        ("Booster 4: Sector Orthogonal Guard (Max 1 Per Sector)", {"max_trades_per_sector": 1}),
        ("Booster 5: Fast T1 Lock (+1.2x ATR vs +1.5x ATR)", {"t1_mult": 1.2}),
        ("🏆 Grand Booster Synergy: Vol 1.0x + Sector Guard + Rising 200-EMA", {
            "volume_mult": 1.0, "max_trades_per_sector": 1, "require_ema200_rising": True
        })
    ]

    print("\n" + "=" * 115)
    print("🔬 TESTING NEXT-LEVEL PROFIT FACTOR & WIN RATE BOOSTERS FOR QUANTUM SWING")
    print("=" * 115)

    for label, params in candidates:
        res = run_swing_booster_simulation(
            trading_dates, stock_dfs, mkt_map, stock_sec_map,
            initial_capital=500000.0,
            start_date=start_d, end_date=end_d,
            **params
        )
        print(f"[{label:<60}] Final: ₹{res['final_val']:>12,.2f} ({res['multiple']:>4.2f}x) | CAGR: {res['cagr']:>6.2f}% | PF: {res['profit_factor']:>4.2f}x | Payoff: {res['payoff_ratio']:>5.2f}x | WinRate: {res['win_rate']:>5.1f}% | MaxDD: {res['max_dd']:>5.2f}% | Calmar: {res['calmar']:>5.2f} | Trades: {res['total_trades']}")

    print("\n" + "=" * 115)
    print(f"🏁 COMPLETED IN {time.time()-t0:.2f}s")
    print("=" * 115)


if __name__ == "__main__":
    run_experiment()
