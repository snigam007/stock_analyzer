"""
scripts/test_microstructure_champions.py
========================================
Deep Fine-Tuning of Microstructure Champions (AVWAP + Volume Profile + GEX + JEV)
Target: Break 50% Win Rate, > 2.10x Profit Factor, and Maximize Calmar Ratio
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

from scripts.backtest_advanced_microstructure_5year import load_microstructure_5year_data, DB_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MicrostructureChampions")


def run_tuned_simulation(
    trading_dates: List[date],
    stock_dfs: Dict[str, pd.DataFrame],
    mkt_map: Dict[date, Any],
    variant_name: str,
    tier1_mult: float = 1.00,
    tier1_ratio: float = 0.25,
    use_avwap_gate: bool = True,
    avwap_tolerance: float = 0.992,
    use_volume_profile_filter: bool = True,
    use_gex_market_gate: bool = False,
    use_jev_downsizing: bool = True,
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
                e21 = float(row['ema_21'])
                e50 = float(row['ema_50'])
                e200 = float(row['ema_200'])
                rsi = float(row['rsi_14'])
                rsi2 = float(row['rsi_2'])
                atr = float(row['atr_14'])
                hurst = float(row['hurst_60'])
                z_ldv = float(row['z_log_dollar_vol'])
                j_std = float(row['jump_std_20'])
                avwap = float(row['avwap_60'])
                val = float(row['val_30'])
                vwap30 = float(row['vwap_30'])

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

                # Feature 1: Anchored VWAP Institutional Cost Basis
                if use_avwap_gate:
                    if cp < avwap * avwap_tolerance:
                        continue

                # Feature 2: Auction Market Theory & Volume Profile Value Area Filter
                if use_volume_profile_filter:
                    is_val_retest = (lp <= vwap30 * 1.02) and (cp >= val * 0.99)
                    if not is_val_retest:
                        continue

                ranking_score = 0.40 * row['mom_6m'] + 0.35 * row['mom_3m'] + 0.25 * row['mom_1m']
                candidates.append((sym, ranking_score, cp, atr, val, j_std))

            candidates.sort(key=lambda x: x[1], reverse=True)
            for sym, score, cp, atr, val, j_std in candidates[:needed_slots]:
                if use_jev_downsizing and j_std > 0.015:
                    downsize = max(0.5, 0.02 / (0.02 + j_std))
                    trade_capital = slot_capital * downsize
                else:
                    trade_capital = slot_capital

                alloc = min(cash * 0.95, trade_capital)
                shares = int(alloc // cp)
                if shares > 0:
                    trade_cost = shares * cp
                    cash -= trade_cost
                    
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
        'profit_factor': pf
    }


def main():
    print("=" * 115)
    print("  [CHAMPION TUNING] MICROSTRUCTURE & ORDERFLOW SWING TUNING")
    print("  Period: 2021-09-27 to 2026-09-25 (1,420 Sessions across 304 Equities)")
    print("=" * 115)

    mkt_map, trading_dates, stock_dfs = load_microstructure_5year_data(DB_PATH)

    configs = [
        # (name, t1_mult, use_vp, use_gex, use_jev, avwap_tol)
        ("1. Baseline (Persistent Pullback No VP/AVWAP)", 1.00, False, False, False, 0.992),
        ("2. AVWAP + VP (Pure, No JEV)", 1.00, True, False, False, 0.992),
        ("3. AVWAP + VP + JEV Jump Sizing", 1.00, True, False, True, 0.992),
        ("4. AVWAP + VP + GEX Gate + JEV", 1.00, True, True, True, 0.992),
        ("5. AVWAP + VP (T1 @ 0.90 ATR)", 0.90, True, False, True, 0.992),
        ("6. AVWAP + VP (T1 @ 1.05 ATR)", 1.05, True, False, True, 0.992),
        ("7. AVWAP + VP (Strict AVWAP 1.000)", 1.00, True, False, True, 1.000),
        ("8. AVWAP + VP (Forgiving AVWAP 0.985)", 1.00, True, False, True, 0.985),
    ]

    print(f"\n{'Configuration Name':<45} | {'Trades':<7} | {'WinRate':<8} | {'PF':<6} | {'CAGR':<7} | {'MaxDD':<7} | {'Calmar':<7} | {'Final Val (Rs)':<14}")
    print("-" * 125)

    for name, t1, vp, gex, jev, tol in configs:
        res = run_tuned_simulation(
            trading_dates=trading_dates,
            stock_dfs=stock_dfs,
            mkt_map=mkt_map,
            variant_name=name,
            tier1_mult=t1,
            tier1_ratio=0.25,
            use_avwap_gate=True if "Baseline" not in name else False,
            avwap_tolerance=tol,
            use_volume_profile_filter=vp,
            use_gex_market_gate=gex,
            use_jev_downsizing=jev,
            initial_capital=500000.0
        )
        print(f"{res['variant_name']:<45} | {res['trades']:<7} | {res['win_rate']:<7.1f}% | {res['profit_factor']:<5.2f}x | {res['cagr']:<6.1f}% | {res['max_dd']:<6.1f}% | {res['calmar']:<6.2f} | Rs {res['final_val']:>11,.0f}")

    print("=" * 125)


if __name__ == '__main__':
    main()
