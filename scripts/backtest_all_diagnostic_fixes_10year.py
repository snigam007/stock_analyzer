"""
scripts/backtest_all_diagnostic_fixes_10year.py
================================================
Comprehensive 10-Year Detailed Backtest (2016-09-30 to 2026-09-29 / 2,470 Trading Sessions)
Evaluating all 4 Architectural Fixes identified in the Walkforward Discrepancy Audit:

1. Baseline: 3 Slots (33.3%), Intraday Low SL, No Circuit Breaker, No Swap
2. Fix 1: 4 Slots Capacity Expansion (25% per slot)
3. Fix 2: Close-Based Stop Confirmation (Eliminates intraday wick false shakeouts)
4. Fix 3: 3-Strike Heat Circuit Breaker (Halves sizing after 3 consecutive stops in 10 days)
5. Fix 4: Dynamic Momentum Swap Rule (Swaps unpyramided stagnant stock for 1.5x leader)
6. Grand Apex Synergy: All Fixes Combined (4 Slots + Close Stop + Circuit Breaker + Momentum Swap + Fast T1)
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
logger = logging.getLogger("DetailedFixes10YrBacktest")

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
        SELECT symbol, date, open, high, low, close, volume
        FROM daily_prices
        WHERE date >= '2015-01-01' AND symbol NOT IN ('^NSEI', 'NIFTY 50', 'NIFTY', 'GOLDBEES.NS')
        ORDER BY symbol, date ASC;
    """, conn)
    conn.close()

    stocks_df['date'] = pd.to_datetime(stocks_df['date']).dt.date
    stock_dfs = {}
    for sym, g in stocks_df.groupby('symbol'):
        if len(g) < 40:
            continue
        g = g.sort_values('date').reset_index(drop=True)
        c = g['close']
        h = g['high']
        l = g['low']

        g['ema_50'] = c.ewm(span=50, adjust=False).mean()
        g['ema_200'] = c.ewm(span=200, adjust=False).mean()

        hl = h - l
        hc = (h - c.shift(1)).abs()
        lc = (l - c.shift(1)).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        g['atr_14'] = tr.rolling(14, min_periods=14).mean().fillna(c * 0.02)

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
    return mkt_map, trading_dates, stock_dfs


def run_swing_variant(
    trading_dates: List[date],
    stock_dfs: Dict[str, pd.DataFrame],
    mkt_map: Dict[date, Any],
    initial_capital: float = 500000.0,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    max_slots: int = 3,
    use_close_stop: bool = False,
    enable_circuit_breaker: bool = False,
    enable_momentum_swap: bool = False,
    t1_mult: float = 1.2,
    enable_half_kelly: bool = True
) -> Dict[str, Any]:
    filtered_dates = [d for d in trading_dates if (start_date is None or d >= start_date) and (end_date is None or d <= end_date)]
    if not filtered_dates:
        return {}

    tiers = [(t1_mult, 0.333), (3.0, 0.333), (8.5, 0.334)]

    cash = initial_capital
    cash_liquidbees = 0.0
    open_positions = {}
    closed_trades = []
    equity_curve = []

    # Circuit breaker tracking
    loss_history = [] # list of (date, pnl)
    cb_active_until = None

    for idx_d, curr_d in enumerate(filtered_dates):
        mkt_row = mkt_map.get(curr_d)
        is_bull = mkt_row.is_bull if mkt_row else True
        active_allowed_slots = 1 if not is_bull else max_slots

        # Yield on unallocated cash
        if cash_liquidbees > 0:
            cash_liquidbees += cash_liquidbees * (0.065 / 365.0)

        # Check circuit breaker status
        if cb_active_until and curr_d < cb_active_until:
            cb_multiplier = 0.50
        else:
            cb_multiplier = 1.0
            cb_active_until = None

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

            # Stop Loss Check (Close-based vs Intraday Low)
            is_stopped = (c <= pos['stop_loss']) if use_close_stop else (l <= pos['stop_loss'])

            if is_stopped:
                exit_price = min(pos['stop_loss'], c) if use_close_stop else min(pos['stop_loss'], float(row['open']))
                pnl = (exit_price - pos['avg_price']) * pos['shares']
                pnl_pct = (exit_price - pos['avg_price']) / pos['avg_price'] * 100.0
                cash += pos['shares'] * exit_price
                closed_trades.append({
                    'symbol': sym, 'pnl': pnl, 'pnl_pct': pnl_pct,
                    'hold_days': hold_days,
                    'outcome': 'SL_HIT' if pnl <= 0 else 'TRAILING_SL_HIT'
                })
                del open_positions[sym]

                # Update circuit breaker tracking
                loss_history.append((curr_d, pnl))
                if enable_circuit_breaker and pnl <= 0:
                    # Check if 3 losses in last 10 days
                    cutoff_d = curr_d - timedelta(days=10)
                    recent_losses = [lh for lh in loss_history if lh[0] >= cutoff_d and lh[1] <= 0]
                    if len(recent_losses) >= 3:
                        cb_active_until = curr_d + timedelta(days=7) # Throttle 50% for 7 days
                continue

            # 15-Day Stale Momentum Rotation
            if hold_days >= 15 and not pos['pyramided'] and pos['tier_idx'] == 0:
                if h < pos['entry_price'] + (1.0 * atr):
                    exit_price = c
                    pnl = (exit_price - pos['avg_price']) * pos['shares']
                    pnl_pct = (exit_price - pos['avg_price']) / pos['avg_price'] * 100.0
                    cash += pos['shares'] * exit_price
                    closed_trades.append({
                        'symbol': sym, 'pnl': pnl, 'pnl_pct': pnl_pct,
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
                    cash += pos['shares'] * c
                    pnl = (c - pos['avg_price']) * pos['shares']
                    pnl_pct = (c - pos['avg_price']) / pos['avg_price'] * 100.0
                    closed_trades.append({
                        'symbol': sym, 'pnl': pnl, 'pnl_pct': pnl_pct,
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

                if cp < 30 or atr <= 0:
                    continue

                if (cp >= e50 >= e200 * 0.98) and (m1 > 0 and m3 > 0 and m6 > 10.0) and (45.0 <= rsi <= 72.0):
                    candidates.append((sym, score, cp, atr))

        candidates.sort(key=lambda x: x[1], reverse=True)

        # 4. Dynamic Momentum Swap Check
        # If slots are full, but candidate #1 has momentum score > 1.5x of an unpyramided Tier 0 holding (> 7 days old, < 1.0 ATR gain)
        if enable_momentum_swap and len(open_positions) >= active_allowed_slots and len(candidates) > 0:
            top_sym, top_score, top_cp, top_atr = candidates[0]
            for held_sym, held_pos in list(open_positions.items()):
                held_hold_days = (curr_d - held_pos['entry_date']).days
                if not held_pos['pyramided'] and held_pos['tier_idx'] == 0 and held_hold_days >= 7:
                    held_score = float(stock_dfs[held_sym].loc[curr_d]['multi_lookback_score']) if curr_d in stock_dfs[held_sym].index else 0.0
                    if top_score >= max(20.0, held_score * 1.5):
                        # Liquidate stagnant holding to liberate slot for explosive leader
                        exit_price = float(stock_dfs[held_sym].loc[curr_d]['close'])
                        pnl = (exit_price - held_pos['avg_price']) * held_pos['shares']
                        pnl_pct = (exit_price - held_pos['avg_price']) / held_pos['avg_price'] * 100.0
                        cash += held_pos['shares'] * exit_price
                        closed_trades.append({
                            'symbol': held_sym, 'pnl': pnl, 'pnl_pct': pnl_pct,
                            'hold_days': held_hold_days,
                            'outcome': 'MOMENTUM_SWAP'
                        })
                        del open_positions[held_sym]
                        break

        # 5. Check Entries
        needed_slots = active_allowed_slots - len(open_positions)
        if needed_slots > 0 and (cash + cash_liquidbees) > 20000:
            if cash_liquidbees > 0:
                cash += cash_liquidbees
                cash_liquidbees = 0.0

            # Slot sizing
            base_slot_cap = total_equity / max_slots
            if enable_half_kelly:
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
                slot_fraction = max(0.18, min(1.0 / max_slots, (f_star * 0.5) + (0.5 / max_slots)))
                slot_capital = total_equity * slot_fraction * cb_multiplier
            else:
                slot_capital = base_slot_cap * cb_multiplier

            for sym, score, cp, atr in candidates[:needed_slots]:
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

        # 6. Fortress Cash Sweep
        if not is_bull and len(open_positions) <= 1 and cash > 50000:
            sweep_amt = cash * 0.70
            cash -= sweep_amt
            cash_liquidbees += sweep_amt

    # Liquidate at end
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
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "gross_profit": round(tot_profit, 2),
        "gross_loss": round(tot_loss, 2)
    }


def execute_all_fixes_audit():
    mkt_map, trading_dates, stock_dfs = load_data()
    start_d = date(2016, 9, 30)
    end_d = date(2026, 9, 29)

    print("\n" + "=" * 115)
    print("🏆 10-YEAR HISTORICAL AUDIT: TESTING ALL 4 ARCHITECTURAL FIXES (2016-09-30 to 2026-09-29)")
    print("=" * 115)

    variants = [
        ("0. Baseline: 3 Slots (Intraday Low SL, No CB, No Swap)", {
            "max_slots": 3, "use_close_stop": False, "enable_circuit_breaker": False, "enable_momentum_swap": False
        }),
        ("1. Fix 1: 4 Slots Expansion (25% Sizing - Resolves Slot-Lock)", {
            "max_slots": 4, "use_close_stop": False, "enable_circuit_breaker": False, "enable_momentum_swap": False
        }),
        ("2. Fix 2: Close-Based SL Confirmation (Eliminates False Shakeouts)", {
            "max_slots": 3, "use_close_stop": True, "enable_circuit_breaker": False, "enable_momentum_swap": False
        }),
        ("3. Fix 3: 3-Strike Heat Circuit Breaker (Halves Sizing on Losses)", {
            "max_slots": 3, "use_close_stop": False, "enable_circuit_breaker": True, "enable_momentum_swap": False
        }),
        ("4. Fix 4: Dynamic Momentum Swap (Swaps Stagnant for 1.5x Leaders)", {
            "max_slots": 3, "use_close_stop": False, "enable_circuit_breaker": False, "enable_momentum_swap": True
        }),
        ("5. Synergy A: 4 Slots + Close-Based SL Confirmation", {
            "max_slots": 4, "use_close_stop": True, "enable_circuit_breaker": False, "enable_momentum_swap": False
        }),
        ("6. Synergy B: 4 Slots + Close SL + Momentum Swap", {
            "max_slots": 4, "use_close_stop": True, "enable_circuit_breaker": False, "enable_momentum_swap": True
        }),
        ("7. 👑 GRAND APEX SYNERGY: All 4 Fixes Combined (4 Slots + Close SL + CB + Swap)", {
            "max_slots": 4, "use_close_stop": True, "enable_circuit_breaker": True, "enable_momentum_swap": True
        })
    ]

    results = []
    for label, params in variants:
        res = run_swing_variant(
            trading_dates, stock_dfs, mkt_map,
            initial_capital=500000.0,
            start_date=start_d, end_date=end_d,
            **params
        )
        results.append({"name": label, **res})
        print(f"[{label:<70}] Final: ₹{res['final_val']:>12,.2f} ({res['multiple']:>5.2f}x) | CAGR: {res['cagr']:>6.2f}% | PF: {res['profit_factor']:>4.2f}x | RR: {res['payoff_ratio']:>5.2f}x | WR: {res['win_rate']:>5.1f}% | MaxDD: {res['max_dd']:>5.2f}% | Calmar: {res['calmar']:>4.2f} | Trades: {res['total_trades']}")

    # Save to JSON
    report_path = ROOT_DIR / "data" / "ten_year_fixes_audit_results.json"
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 115)
    print(f"✅ DETAILED FIXES 10-YEAR AUDIT SAVED TO: {report_path}")
    print("=" * 115)
    return results


if __name__ == "__main__":
    execute_all_fixes_audit()
