"""
scripts/test_advanced_swing_improvements.py
===========================================
Empirical testing of advanced improvement frontiers on the 10-Year Walkforward dataset (2016-2026):
1. Accurate Trade PnL Accounting (including partial profit trims)
2. Weekly Trend Alignment Filter (Close >= 30-week EMA / Stan Weinstein Stage 2)
3. Volume Breakout Confirmation (Breakout Day Volume >= 1.25x 20-day Volume SMA)
4. Sector Exposure Limit (Max 2 slots / 50% max sector weight)
5. Universal LiquidBees Yield Sweeping (All idle cash earns 6.5% p.a.)
6. Synergies combining the top improvements
"""

import sys
import os
import json
import time
import math
import sqlite3
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AdvancedImprovements")

DB_PATH = ROOT_DIR / "data" / "stock_analyzer.db"


class FastMarketRegimeRow:
    __slots__ = ("market_close", "market_ema50", "market_ema21", "is_bull")
    def __init__(self, market_close, market_ema50, market_ema21, is_bull):
        self.market_close = market_close
        self.market_ema50 = market_ema50
        self.market_ema21 = market_ema21
        self.is_bull = is_bull


def load_data():
    t0 = time.time()
    conn = sqlite3.connect(str(DB_PATH))

    # Market Index
    nifty_df = pd.read_sql_query("""
        SELECT date, close
        FROM index_prices
        WHERE symbol = '^NSEI' AND date >= '2015-01-01'
        ORDER BY date ASC;
    """, conn)
    nifty_df['date'] = pd.to_datetime(nifty_df['date']).dt.date
    nifty_df = nifty_df.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
    nifty_df['ema_50'] = nifty_df['close'].ewm(span=50, adjust=False).mean()
    nifty_df['ema_21'] = nifty_df['close'].ewm(span=21, adjust=False).mean()
    nifty_df['is_bull'] = (nifty_df['close'] >= nifty_df['ema_50']) | (nifty_df['close'] >= nifty_df['ema_21'])

    mkt_map = {
        r['date']: FastMarketRegimeRow(r['close'], r['ema_50'], r['ema_21'], bool(r['is_bull']))
        for _, r in nifty_df.iterrows()
    }
    trading_dates = nifty_df['date'].tolist()

    # Stocks
    stocks_df = pd.read_sql_query("""
        SELECT p.symbol, p.date, p.open, p.high, p.low, p.close, p.volume,
               s.sector
        FROM daily_prices p
        LEFT JOIN stocks s ON p.symbol = s.symbol
        WHERE p.date >= '2015-01-01' AND p.symbol NOT IN ('^NSEI', 'NIFTY 50', 'NIFTY', 'GOLDBEES.NS')
        ORDER BY p.symbol, p.date ASC;
    """, conn)
    conn.close()

    stocks_df['date'] = pd.to_datetime(stocks_df['date']).dt.date
    stock_dfs = {}
    stock_sectors = {}

    for sym, g in stocks_df.groupby('symbol'):
        if len(g) < 40:
            continue
        g = g.sort_values('date').reset_index(drop=True)
        c = g['close']
        h = g['high']
        l = g['low']
        v = g['volume']

        sec = g['sector'].iloc[0] if 'sector' in g.columns and pd.notna(g['sector'].iloc[0]) else "General"
        stock_sectors[sym] = sec

        g['ema_50'] = c.ewm(span=50, adjust=False).mean()
        g['ema_200'] = c.ewm(span=200, adjust=False).mean()
        # 30-week EMA approx 150 daily sessions
        g['ema_150'] = c.ewm(span=150, adjust=False).mean()

        hl = h - l
        hc = (h - c.shift(1)).abs()
        lc = (l - c.shift(1)).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        g['atr_14'] = tr.rolling(14, min_periods=14).mean().fillna(c * 0.02)

        g['vol_sma20'] = v.rolling(20, min_periods=5).mean().fillna(v)

        g['mom_1m'] = ((c - c.shift(20)) / c.shift(20) * 100.0).fillna(0.0)
        g['mom_3m'] = ((c - c.shift(60)) / c.shift(60) * 100.0).fillna(0.0)
        g['mom_6m'] = ((c - c.shift(126)) / c.shift(126) * 100.0).fillna(0.0)
        g['mom_12m'] = ((c - c.shift(250)) / c.shift(250) * 100.0).fillna(0.0)

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
        stock_dfs[sym] = g.set_index('date')

    logger.info(f"Loaded {len(stock_dfs)} stocks across {len(trading_dates)} dates in {time.time()-t0:.2f}s")
    return mkt_map, trading_dates, stock_dfs, stock_sectors


def run_swing_simulation(
    trading_dates: List[date],
    stock_dfs: Dict[str, pd.DataFrame],
    stock_sectors: Dict[str, str],
    mkt_map: Dict[date, Any],
    initial_capital: float = 500000.0,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    max_slots: int = 4,
    use_close_stop: bool = True,
    use_weekly_trend_filter: bool = False,
    use_volume_filter: bool = False,
    min_volume_mult: float = 1.20,
    max_slots_per_sector: int = 4,  # default unlimited (up to max_slots)
    universal_liquid_yield: bool = True,
    liquid_yield_pct: float = 6.5,
    enable_momentum_swap: bool = False
) -> Dict[str, Any]:

    filtered_dates = [d for d in trading_dates if (start_date is None or d >= start_date) and (end_date is None or d <= end_date)]
    if not filtered_dates:
        return {}

    tiers = [(1.2, 0.333), (3.0, 0.333), (8.5, 0.334)]

    cash = initial_capital
    cash_liquidbees = 0.0
    open_positions = {}
    closed_trades = []
    equity_curve = []

    daily_yield_factor = (liquid_yield_pct / 100.0) / 365.0

    for idx_d, curr_d in enumerate(filtered_dates):
        mkt_row = mkt_map.get(curr_d)
        is_bull = mkt_row.is_bull if mkt_row else True
        active_allowed_slots = 1 if not is_bull else max_slots

        # Overnight yield on LiquidBees cash
        if universal_liquid_yield:
            # All uninvested cash earns overnight liquid yield
            cash += cash * daily_yield_factor
        elif cash_liquidbees > 0:
            cash_liquidbees += cash_liquidbees * daily_yield_factor

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
            hold_days = (curr_d - pos['entry_date']).days

            # Stop Loss Check
            is_stopped = (c <= pos['stop_loss']) if use_close_stop else (l <= pos['stop_loss'])

            if is_stopped:
                exit_price = min(pos['stop_loss'], c) if use_close_stop else min(pos['stop_loss'], float(row['open']))
                final_piece_pnl = (exit_price - pos['avg_price']) * pos['shares']
                pos['realized_pnl'] += final_piece_pnl
                cash += pos['shares'] * exit_price

                total_pnl = pos['realized_pnl']
                pnl_pct = (total_pnl / pos['total_invested']) * 100.0 if pos['total_invested'] > 0 else 0.0

                closed_trades.append({
                    'symbol': sym,
                    'pnl': total_pnl,
                    'pnl_pct': pnl_pct,
                    'hold_days': hold_days,
                    'outcome': 'SL_HIT' if total_pnl <= 0 else 'TRAILING_SL_HIT'
                })
                del open_positions[sym]
                continue

            # 15-Day Stale Momentum Rotation
            if hold_days >= 15 and not pos['pyramided'] and pos['tier_idx'] == 0:
                if h < pos['entry_price'] + (1.0 * atr):
                    exit_price = c
                    final_piece_pnl = (exit_price - pos['avg_price']) * pos['shares']
                    pos['realized_pnl'] += final_piece_pnl
                    cash += pos['shares'] * exit_price

                    total_pnl = pos['realized_pnl']
                    pnl_pct = (total_pnl / pos['total_invested']) * 100.0 if pos['total_invested'] > 0 else 0.0

                    closed_trades.append({
                        'symbol': sym,
                        'pnl': total_pnl,
                        'pnl_pct': pnl_pct,
                        'hold_days': hold_days,
                        'outcome': 'STALE_ROTATION'
                    })
                    del open_positions[sym]
                    continue

            # Ratchet to BE at +1.2x ATR
            if h >= pos['entry_price'] + (1.2 * atr):
                pos['stop_loss'] = max(pos['stop_loss'], pos['entry_price'] * 1.002)

            # Pyramiding (+4.0% gain -> Add +50% size, move SL to breakeven)
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

            # Dynamic Tier Exits
            cur_tier = pos['tier_idx']
            if cur_tier < len(tiers) - 1:
                tier_mult, trim_ratio = tiers[cur_tier]
                if h >= pos['entry_price'] + (tier_mult * atr):
                    trim_shares = int(pos['original_shares'] * trim_ratio)
                    if trim_shares > 0 and pos['shares'] > trim_shares:
                        t_price = pos['entry_price'] + (tier_mult * atr)
                        trim_pnl = (t_price - pos['avg_price']) * trim_shares
                        pos['realized_pnl'] += trim_pnl
                        cash += trim_shares * t_price
                        pos['shares'] -= trim_shares
                        pos['tier_idx'] += 1
                        pos['stop_loss'] = max(pos['stop_loss'], pos['entry_price'] + (cur_tier * 0.5 * atr))
            else:
                # Chandelier Moonbag Runner
                highest_since = pos.get('highest_close', c)
                if c > highest_since:
                    pos['highest_close'] = c
                chand_stop = pos['highest_close'] - (2.5 * atr)
                pos['stop_loss'] = max(pos['stop_loss'], chand_stop)

                upper_mult = tiers[-1][0]
                if h >= pos['entry_price'] + (upper_mult * atr):
                    final_piece_pnl = (c - pos['avg_price']) * pos['shares']
                    pos['realized_pnl'] += final_piece_pnl
                    cash += pos['shares'] * c

                    total_pnl = pos['realized_pnl']
                    pnl_pct = (total_pnl / pos['total_invested']) * 100.0 if pos['total_invested'] > 0 else 0.0

                    closed_trades.append({
                        'symbol': sym,
                        'pnl': total_pnl,
                        'pnl_pct': pnl_pct,
                        'hold_days': hold_days,
                        'outcome': 'T3_MOONBAG'
                    })
                    del open_positions[sym]
                    continue

        # 2. Portfolio Valuation
        cur_pos_val = sum(
            pos['shares'] * float(stock_dfs[sym].loc[curr_d]['close']) if (sym in stock_dfs and curr_d in stock_dfs[sym].index) else pos['shares'] * pos['avg_price']
            for sym, pos in open_positions.items()
        )
        total_equity = cash + cash_liquidbees + cur_pos_val
        equity_curve.append(total_equity)

        # 3. Screener Candidates
        candidates = []
        for sym, df_s in stock_dfs.items():
            if sym in open_positions:
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
                vol = float(row['volume'])
                vol_sma = float(row['vol_sma20'])
                e150 = float(row.get('ema_150', e200))

                if cp < 30 or atr <= 0:
                    continue

                # Baseline trend condition
                base_trend = (cp >= e50 >= e200 * 0.98) and (m1 > 0 and m3 > 0 and m6 > 10.0) and (45.0 <= rsi <= 72.0)
                if not base_trend:
                    continue

                # Weekly Trend Filter (Stan Weinstein Stage 2: Close >= 30-week EMA)
                if use_weekly_trend_filter and cp < e150:
                    continue

                # Volume Breakout Confirmation
                if use_volume_filter and vol < (vol_sma * min_volume_mult):
                    continue

                sec = stock_sectors.get(sym, "General")
                candidates.append((sym, score, cp, atr, sec))

        candidates.sort(key=lambda x: x[1], reverse=True)

        # 4. Momentum Swap
        if enable_momentum_swap and len(open_positions) >= active_allowed_slots and len(candidates) > 0:
            top_sym, top_score, top_cp, top_atr, top_sec = candidates[0]
            for held_sym, held_pos in list(open_positions.items()):
                held_hold_days = (curr_d - held_pos['entry_date']).days
                if not held_pos['pyramided'] and held_pos['tier_idx'] == 0 and held_hold_days >= 7:
                    held_score = float(stock_dfs[held_sym].loc[curr_d]['multi_lookback_score']) if curr_d in stock_dfs[held_sym].index else 0.0
                    if top_score >= max(20.0, held_score * 1.5):
                        exit_price = float(stock_dfs[held_sym].loc[curr_d]['close'])
                        final_piece_pnl = (exit_price - held_pos['avg_price']) * held_pos['shares']
                        held_pos['realized_pnl'] += final_piece_pnl
                        cash += held_pos['shares'] * exit_price

                        total_pnl = held_pos['realized_pnl']
                        pnl_pct = (total_pnl / held_pos['total_invested']) * 100.0 if held_pos['total_invested'] > 0 else 0.0

                        closed_trades.append({
                            'symbol': held_sym,
                            'pnl': total_pnl,
                            'pnl_pct': pnl_pct,
                            'hold_days': held_hold_days,
                            'outcome': 'MOMENTUM_SWAP'
                        })
                        del open_positions[held_sym]
                        break

        # 5. Open New Positions
        needed_slots = max(0, active_allowed_slots - len(open_positions))
        if needed_slots > 0 and candidates:
            # Count current sector exposure
            sector_counts = {}
            for pos in open_positions.values():
                s = pos.get('sector', 'General')
                sector_counts[s] = sector_counts.get(s, 0) + 1

            slot_fraction = 1.0 / max_slots
            slot_capital = total_equity * slot_fraction

            for sym, score, cp, atr, sec in candidates:
                if needed_slots <= 0:
                    break

                # Sector cap check
                if max_slots_per_sector < max_slots and sector_counts.get(sec, 0) >= max_slots_per_sector:
                    continue

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
                        'total_invested': cost,
                        'realized_pnl': 0.0,
                        'stop_loss': init_sl,
                        'atr': atr,
                        'tier_idx': 0,
                        'pyramided': False,
                        'highest_close': cp,
                        'sector': sec
                    }
                    sector_counts[sec] = sector_counts.get(sec, 0) + 1
                    needed_slots -= 1

        # Bear sweep if not universal yield
        if not universal_liquid_yield and not is_bull and len(open_positions) <= 1 and cash > 50000:
            sweep_amt = cash * 0.70
            cash -= sweep_amt
            cash_liquidbees += sweep_amt

    # Liquidate at end
    last_d = filtered_dates[-1]
    for sym, pos in list(open_positions.items()):
        c_price = pos['avg_price']
        if sym in stock_dfs and last_d in stock_dfs[sym].index:
            c_price = float(stock_dfs[sym].loc[last_d]['close'])
        final_piece_pnl = (c_price - pos['avg_price']) * pos['shares']
        pos['realized_pnl'] += final_piece_pnl
        cash += pos['shares'] * c_price
        total_pnl = pos['realized_pnl']
        pnl_pct = (total_pnl / pos['total_invested']) * 100.0 if pos['total_invested'] > 0 else 0.0
        closed_trades.append({
            'symbol': sym,
            'pnl': total_pnl,
            'pnl_pct': pnl_pct,
            'hold_days': (last_d - pos['entry_date']).days,
            'outcome': 'AUDIT_END'
        })

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
    rr_ratio = avg_win / max(1.0, avg_loss)

    return {
        "final_corpus": round(final_val, 2),
        "final_corpus_lakhs": round(final_val / 100000.0, 2),
        "cagr": round(cagr, 2),
        "max_drawdown": round(max_dd, 2),
        "calmar_ratio": round(cagr / max_dd, 2) if max_dd > 0 else 0.0,
        "win_rate": round(win_rate, 1),
        "profit_factor": round(pf, 2),
        "rr_ratio": round(rr_ratio, 2),
        "total_trades": len(closed_trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses)
    }


def main():
    mkt_map, trading_dates, stock_dfs, stock_sectors = load_data()
    start_d = date(2016, 9, 30)
    end_d = date(2026, 9, 29)

    experiments = [
        ("1. Prior Benchmark (Synergy A: 4 Slots + Close SL, No Idle Yield)", {
            "max_slots": 4, "use_close_stop": True, "universal_liquid_yield": False,
            "use_weekly_trend_filter": False, "use_volume_filter": False,
            "max_slots_per_sector": 4, "enable_momentum_swap": False
        }),
        ("2. Lever A: Universal LiquidBees Overnight Yield (6.5% on Idle Cash)", {
            "max_slots": 4, "use_close_stop": True, "universal_liquid_yield": True,
            "use_weekly_trend_filter": False, "use_volume_filter": False,
            "max_slots_per_sector": 4, "enable_momentum_swap": False
        }),
        ("3. Lever B: Weekly 30-WMA Trend Filter (Stan Weinstein Stage 2)", {
            "max_slots": 4, "use_close_stop": True, "universal_liquid_yield": True,
            "use_weekly_trend_filter": True, "use_volume_filter": False,
            "max_slots_per_sector": 4, "enable_momentum_swap": False
        }),
        ("4. Lever C: Volume Expansion Breakout (Vol >= 1.25x 20-SMA)", {
            "max_slots": 4, "use_close_stop": True, "universal_liquid_yield": True,
            "use_weekly_trend_filter": False, "use_volume_filter": True, "min_volume_mult": 1.25,
            "max_slots_per_sector": 4, "enable_momentum_swap": False
        }),
        ("5. Lever D: Sector Concentration Cap (Max 2 Slots / 50% per Sector)", {
            "max_slots": 4, "use_close_stop": True, "universal_liquid_yield": True,
            "use_weekly_trend_filter": False, "use_volume_filter": False,
            "max_slots_per_sector": 2, "enable_momentum_swap": False
        }),
        ("6. Lever E: Dynamic Momentum Swap (Stagnant to 1.5x Leader)", {
            "max_slots": 4, "use_close_stop": True, "universal_liquid_yield": True,
            "use_weekly_trend_filter": False, "use_volume_filter": False,
            "max_slots_per_sector": 4, "enable_momentum_swap": True
        }),
        ("7. 🌟 SUPREME COMBO 1: Liquid Yield + Weekly Trend + Sector Cap", {
            "max_slots": 4, "use_close_stop": True, "universal_liquid_yield": True,
            "use_weekly_trend_filter": True, "use_volume_filter": False,
            "max_slots_per_sector": 2, "enable_momentum_swap": False
        }),
        ("8. 👑 SUPREME COMBO 2: Liquid Yield + Weekly Trend + Volume Filter + Sector Cap", {
            "max_slots": 4, "use_close_stop": True, "universal_liquid_yield": True,
            "use_weekly_trend_filter": True, "use_volume_filter": True, "min_volume_mult": 1.20,
            "max_slots_per_sector": 2, "enable_momentum_swap": False
        }),
    ]

    print("\n" + "=" * 125)
    print("🚀 EMPIRICAL 10-YEAR WALKFORWARD (2016-2026): ADVANCED LEVERS BACKTEST (₹5.00 LAKHS INITIAL)")
    print("=" * 125)
    print(f"{'Strategy Variant':<58} | {'Corpus (₹)':<11} | {'CAGR %':<7} | {'MaxDD %':<7} | {'Calmar':<6} | {'WinRate %':<9} | {'PF':<5} | {'RR':<5} | {'Trades':<6}")
    print("-" * 125)

    results_data = []

    for name, params in experiments:
        t0 = time.time()
        res = run_swing_simulation(
            trading_dates, stock_dfs, stock_sectors, mkt_map,
            initial_capital=500000.0, start_date=start_d, end_date=end_d,
            **params
        )
        el = time.time() - t0
        res["name"] = name
        results_data.append(res)
        print(f"{name:<58} | ₹{res['final_corpus_lakhs']:>6.2f} L   | {res['cagr']:>6.2f}% | {res['max_drawdown']:>6.2f}% | {res['calmar_ratio']:>6.2f} | {res['win_rate']:>7.1f}% | {res['profit_factor']:>4.2f} | {res['rr_ratio']:>4.2f} | {res['total_trades']:<6}")

    print("=" * 125)

    out_file = ROOT_DIR / "data" / "advanced_swing_improvements_10yr.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results_data, f, indent=2)
    print(f"Results saved to {out_file}")


if __name__ == "__main__":
    main()
