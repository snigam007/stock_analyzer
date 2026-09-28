"""
scripts/backtest_all_quantum_improvements.py
============================================
Comprehensive 5-Year Full-Cycle Backtest (2021-09-27 to 2026-09-25 / 1,298 sessions)
evaluating all proposed improvements for BOTH Swing and SIP engines:

1. SWING IMPROVEMENTS:
   - Baseline: Current Half-Kelly + Flat 4% Pyramiding
   - Variant 1: ATR-Volatility Pyramiding (Trigger @ Entry + 1.5x ATR, SL -> BE + 0.2x ATR)
   - Variant 2: 20-Day Stale Trade Rotation (Exit flat trades after 20 sessions if gain < 1.0x ATR)
   - Variant 3: 15-Day Stale Trade Rotation (Faster recycling)
   - Variant 4: Combined Synergy (Half-Kelly + ATR Pyramiding + 20-Day Stale Exit)

2. SIP IMPROVEMENTS:
   - Baseline: Current Conviction Half-Kelly (59.53% XIRR)
   - Variant 1: Max Position Cap 50% (vs 45%)
   - Variant 2: Sensitive Dip Deployer (90% Cash on 3.0% Pullback)
   - Variant 3: Parabolic Skim @ +120% Gain (10% Trim to fund dip buys)
   - Variant 4: 🏆 The Frontier Holy Grail (Dip 90% @ 3.0% + Skim 120% @ 10% + Cap 50% + LiquidBees + Zero Hedge)
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
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from core.sip_audit_backtester import run_monthly_sip_backtest, calculate_xirr
from scripts.backtest_60_plus_alpha_frontiers import BASE_CHAMP
from scripts.audit_true_quantum_champions_5year import (
    load_fast_5year_market_and_stocks,
    FastMarketRegimeRow
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BacktestAllImprovements")

DB_PATH = ROOT_DIR / "data" / "stock_analyzer.db"


def run_swing_simulation_advanced(
    trading_dates,
    stock_dfs,
    mkt_map,
    initial_capital=500000.0,
    start_date=None,
    end_date=None,
    pyramid_mode="FLAT_4PCT",  # "FLAT_4PCT" or "ATR_1_5X"
    stale_exit_days=None,      # None or int (e.g. 15, 20)
    lookback_trades=30
):
    filtered_dates = [d for d in trading_dates if (start_date is None or d >= start_date) and (end_date is None or d <= end_date)]
    if not filtered_dates:
        return {}

    max_slots = 3
    bear_fortress_active = True
    tiers = [(1.5, 0.333), (3.0, 0.333), (8.5, 0.334)]

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

            # Stale Trade Rotation
            if stale_exit_days is not None and holding_days >= stale_exit_days and not pos['pyramided'] and pos['tier_idx'] == 0:
                # If trade has not reached +1.0x ATR within stale_exit_days
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

            # Pyramiding Logic
            if not pos['pyramided']:
                if pyramid_mode == "ATR_1_5X":
                    trigger_price = pos['entry_price'] + (1.5 * atr)
                    ratchet_sl = pos['entry_price'] + (0.2 * atr)
                else:
                    trigger_price = pos['entry_price'] * 1.04
                    ratchet_sl = pos['entry_price'] * 1.002

                if h >= trigger_price:
                    add_shares = int(pos['original_shares'] * 0.5)
                    add_cost = add_shares * c
                    if cash >= add_cost and add_shares > 0:
                        cash -= add_cost
                        pos['shares'] += add_shares
                        pos['avg_price'] = (pos['avg_price'] * (pos['shares'] - add_shares) + add_cost) / pos['shares']
                        pos['stop_loss'] = max(pos['stop_loss'], ratchet_sl)
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
            recent_closed = closed_trades[-lookback_trades:] if len(closed_trades) >= 10 else []
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
        "total_realized_pnl": round(tot_profit - tot_loss, 2)
    }


def run_all_comprehensive_backtests():
    t0 = time.time()
    logger.info("Executing Master 5-Year Improvement Backtest Suite (2021-2026)...")

    # Load market and stocks data
    mkt_map, trading_dates, stock_dfs = load_fast_5year_market_and_stocks(DB_PATH)
    start_d = date(2021, 9, 27)
    end_d = date(2026, 9, 25)

    n_start = mkt_map[start_d].market_close
    n_end = mkt_map[end_d].market_close
    n_ret = (n_end / n_start - 1.0) * 100.0
    tot_days = (end_d - start_d).days
    n_cagr = ((n_end / n_start) ** (365.0 / tot_days) - 1.0) * 100.0

    print("\n" + "=" * 110)
    print(f"  MARKET BENCHMARK: NIFTY 50 (^NSEI): {n_start:,.1f} -> {n_end:,.1f} (+{n_ret:.2f}% Absolute | +{n_cagr:.2f}% CAGR)")
    print("=" * 110)

    # ─────────────────────────────────────────────────────────────────────────────
    # 1. SWING IMPROVEMENTS BACKTEST
    # ─────────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 110)
    print("🚀 SECTION 1: SWING CHAMPION ADVANCED IMPROVEMENT LEVERS (₹5.00 Lakhs Starting Capital)")
    print("=" * 110)

    swing_configs = [
        ("Current Active Champion (Half-Kelly + Flat 4% Pyramid)", {
            "pyramid_mode": "FLAT_4PCT", "stale_exit_days": None
        }),
        ("Lever 1: ATR-Volatility Pyramiding (+1.5x ATR)", {
            "pyramid_mode": "ATR_1_5X", "stale_exit_days": None
        }),
        ("Lever 2: 20-Day Stale Momentum Rotation", {
            "pyramid_mode": "FLAT_4PCT", "stale_exit_days": 20
        }),
        ("Lever 3: 15-Day Faster Stale Momentum Rotation", {
            "pyramid_mode": "FLAT_4PCT", "stale_exit_days": 15
        }),
        ("Lever 4: 🏆 Grand Synergy (Half-Kelly + ATR Pyramiding + 20-Day Stale)", {
            "pyramid_mode": "ATR_1_5X", "stale_exit_days": 20
        }),
        ("Lever 5: 💎 Ultra-Velocity Synergy (Half-Kelly + ATR Pyramiding + 15-Day Stale)", {
            "pyramid_mode": "ATR_1_5X", "stale_exit_days": 15
        }),
    ]

    swing_results = []
    for label, cfg in swing_configs:
        res = run_swing_simulation_advanced(
            trading_dates, stock_dfs, mkt_map,
            initial_capital=500000.0,
            start_date=start_d, end_date=end_d,
            **cfg
        )
        swing_results.append((label, res))
        print(f"[{label:<55}] Final: ₹{res['final_val']:>12,.2f} ({res['multiple']:>4.2f}x) | CAGR: {res['cagr']:>6.2f}% | MaxDD: {res['max_dd']:>5.2f}% | Calmar: {res['calmar']:>5.2f} | PF: {res['profit_factor']:>4.2f}x | Payoff: {res['payoff_ratio']:>5.2f}x | Trades: {res['total_trades']}")

    # ─────────────────────────────────────────────────────────────────────────────
    # 2. SIP IMPROVEMENTS BACKTEST
    # ─────────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 110)
    print("🚀 SECTION 2: SIP CHAMPION ADVANCED IMPROVEMENT LEVERS (₹14.65 Lakhs Invested over 60 Months)")
    print("=" * 110)

    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    session = Session()

    sip_configs = [
        ("Current Active Champion (Conviction Half-Kelly [30-10%])", {
            **BASE_CHAMP,
            "sizing_mode": "CONVICTION",
            "enable_conviction_weighting": True,
            "conviction_weights": [0.30, 0.25, 0.20, 0.15, 0.10]
        }),
        ("Lever 1: Position Cap 50% (vs 45%)", {
            **BASE_CHAMP,
            "sizing_mode": "CONVICTION",
            "enable_conviction_weighting": True,
            "conviction_weights": [0.30, 0.25, 0.20, 0.15, 0.10],
            "max_position_cap_pct": 50.0
        }),
        ("Lever 2: Ultra-Sensitive Dip Buying (90% Cash on 3.0% Pullback)", {
            **BASE_CHAMP,
            "sizing_mode": "CONVICTION",
            "enable_conviction_weighting": True,
            "conviction_weights": [0.30, 0.25, 0.20, 0.15, 0.10],
            "dip_threshold_pct": 3.0,
            "dip_deploy_pct": 90.0
        }),
        ("Lever 3: Parabolic Skim @ +120% Gain (10% Trim)", {
            **BASE_CHAMP,
            "sizing_mode": "CONVICTION",
            "enable_conviction_weighting": True,
            "conviction_weights": [0.30, 0.25, 0.20, 0.15, 0.10],
            "skim_milestone_pct": 120.0,
            "skim_ratio_pct": 10.0
        }),
        ("Lever 4: 🏆 The Frontier Holy Grail (Dip 90% @ 3% + Skim 120% @ 10% + Cap 50% + LiquidBees + Zero Hedge)", {
            **BASE_CHAMP,
            "sizing_mode": "CONVICTION",
            "enable_conviction_weighting": True,
            "conviction_weights": [0.30, 0.25, 0.20, 0.15, 0.10],
            "dip_threshold_pct": 3.0,
            "dip_deploy_pct": 90.0,
            "skim_milestone_pct": 120.0,
            "skim_ratio_pct": 10.0,
            "max_position_cap_pct": 50.0,
            "macro_hedge_pct": 0.0,
            "enable_macro_regime_gate": False,
            "enable_liquid_sweep": True
        })
    ]

    sip_results = []
    for label, params in sip_configs:
        res = run_monthly_sip_backtest(session, **params)
        cagr_xirr = res.get("strategy_net_xirr", 0.0)
        final_cor = res.get("final_strategy_value", 0.0)
        tot_inv = res.get("total_capital_invested", 0.0)
        net_prof = res.get("net_strategy_profit", 0.0)
        mult = final_cor / max(1.0, tot_inv)
        pf = res.get("profit_factor", 0.0)
        payoff = res.get("payoff_ratio", 0.0)
        mdd = res.get("strategy_max_dd", 0.0)
        wr = res.get("win_rate", 0.0)
        tot_tr = res.get("total_trades", 0)

        sip_results.append((label, {
            "final_value": final_cor,
            "invested": tot_inv,
            "net_profit": net_prof,
            "multiplier": round(mult, 2),
            "xirr": round(cagr_xirr, 2),
            "profit_factor": round(pf, 2),
            "payoff_ratio": round(payoff, 2),
            "max_dd": round(mdd, 2),
            "win_rate": round(wr, 1),
            "trades": tot_tr
        }))
        print(f"[{label:<55}] Corpus: ₹{final_cor:>12,.2f} ({mult:>4.2f}x) | XIRR: {cagr_xirr:>6.2f}% | Net Profit: ₹{net_prof:>12,.2f} | PF: {pf:>4.2f}x | Payoff: {payoff:>5.2f}x | MaxDD: {mdd:>5.2f}%")

    session.close()

    print("\n" + "=" * 110)
    print(f"🏁 ALL TESTS COMPLETED IN {time.time()-t0:.2f}s")
    print("=" * 110)


if __name__ == "__main__":
    run_all_comprehensive_backtests()
