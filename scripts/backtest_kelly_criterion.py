"""
scripts/backtest_kelly_criterion.py
===================================
Evaluates whether applying Kelly Criterion (Full-Kelly, Half-Kelly, Quarter-Kelly,
and ATR-Risk Kelly) improves performance over Fixed-Fractional Sizing across
the full 5-year cycle (2021-09-27 to 2026-09-25 / 1,298 trading sessions).

Tests:
1. SWING CHAMPION:
   - Baseline: Fixed Fractional (33.3% slot sizing, 3 slots)
   - Variant A: Rolling Half-Kelly Slot Sizing (f* = 0.5 * (p*b - q)/b)
   - Variant B: Rolling Quarter-Kelly Slot Sizing (f* = 0.25 * (p*b - q)/b)
   - Variant C: Rolling Full-Kelly Slot Sizing (f* = 1.0 * (p*b - q)/b)
   - Variant D: Volatility/ATR-Adjusted Half-Kelly Risk Sizing

2. SIP CHAMPION:
   - Baseline: Equal Sizing (20% per slot across 5 slots)
   - Variant A: Conviction / Asymmetric Sizing (30%, 25%, 20%, 15%, 10%)
   - Variant B: Clenow-Weighted Proportional Sizing
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
logger = logging.getLogger("KellyCriterionBacktest")

DB_PATH = ROOT_DIR / "data" / "stock_analyzer.db"


def run_swing_with_kelly_sizing(
    trading_dates,
    stock_dfs,
    mkt_map,
    initial_capital=500000.0,
    start_date=None,
    end_date=None,
    kelly_mode="BASELINE",  # "BASELINE", "FULL_KELLY", "HALF_KELLY", "QUARTER_KELLY", "ATR_KELLY"
    lookback_trades=30
):
    """
    Simulates the Swing Champion with dynamic Kelly Criterion sizing.
    Kelly formula: f* = (p * b - (1 - p)) / b
    where p = rolling win rate, b = rolling avg win / avg loss.
    """
    filtered_dates = [d for d in trading_dates if (start_date is None or d >= start_date) and (end_date is None or d <= end_date)]
    if not filtered_dates:
        return {}

    max_slots = 3
    bear_fortress_active = True
    pyramiding_active = True
    tiers = [(1.5, 0.333), (3.0, 0.333), (8.5, 0.334)]

    cash = initial_capital
    cash_liquidbees = 0.0
    open_positions = {}
    closed_trades = []
    equity_curve = []
    daily_dates = []

    # Prior baseline stats for cold start (from historical audits)
    # Win rate ~28%, Payoff ratio ~3.2x -> Kelly f* = (0.28 * 3.2 - 0.72) / 3.2 = 0.176 / 3.2 = 0.055 (5.5% risk or ~25% alloc)
    default_p = 0.30
    default_b = 3.0

    def compute_current_kelly_fraction(mode):
        if mode == "BASELINE":
            return 1.0 / max_slots  # 33.3%

        recent = closed_trades[-lookback_trades:] if len(closed_trades) >= 10 else []
        if len(recent) >= 10:
            wins = [t['pnl'] for t in recent if t['pnl'] > 0]
            losses = [abs(t['pnl']) for t in recent if t['pnl'] <= 0]
            p = len(wins) / len(recent) if recent else default_p
            avg_win = np.mean(wins) if wins else 1.0
            avg_loss = np.mean(losses) if losses else 1.0
            b = avg_win / max(1.0, avg_loss)
        else:
            p = default_p
            b = default_b

        # Kelly fraction: f* = (p * b - (1 - p)) / b
        f_star = (p * b - (1.0 - p)) / max(0.1, b)
        f_star = max(0.02, min(f_star, 0.40))  # bounded

        if mode == "FULL_KELLY":
            return min(0.50, f_star * 1.5)  # Cap at 50% per slot
        elif mode == "HALF_KELLY":
            return min(0.35, f_star * 0.75 + 0.10) # Bounded Half-Kelly allocation
        elif mode == "QUARTER_KELLY":
            return min(0.25, f_star * 0.40 + 0.08) # Conservative
        elif mode == "ATR_KELLY":
            # Risk-based fraction of equity: 0.5 * f* capped at 2.5% risk
            return max(0.008, min(0.025, f_star * 0.06))
        return 1.0 / max_slots

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

            # Stop Loss
            if l <= pos['stop_loss']:
                exit_price = min(pos['stop_loss'], float(row['open']))
                pnl = (exit_price - pos['avg_price']) * pos['shares']
                pnl_pct = (exit_price - pos['avg_price']) / pos['avg_price'] * 100.0
                cash += pos['shares'] * exit_price
                closed_trades.append({
                    'symbol': sym, 'pnl': pnl, 'pnl_pct': pnl_pct,
                    'hold_days': (curr_d - pos['entry_date']).days,
                    'outcome': 'SL_HIT' if pnl <= 0 else 'TRAILING_SL_HIT'
                })
                del open_positions[sym]
                continue

            # Pyramiding (+4.0% gain -> Add +50% size, ratchets SL to Breakeven)
            if pyramiding_active and not pos['pyramided'] and h >= pos['entry_price'] * 1.04:
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
                        'hold_days': (curr_d - pos['entry_date']).days,
                        'outcome': 'T3_MOONBAG'
                    })
                    del open_positions[sym]
                    continue

        # Current total equity
        cur_pos_val = sum(
            pos['shares'] * float(stock_dfs[sym].loc[curr_d]['close']) if (sym in stock_dfs and curr_d in stock_dfs[sym].index) else pos['shares'] * pos['avg_price']
            for sym, pos in open_positions.items()
        )
        total_equity = cash + cash_liquidbees + cur_pos_val
        equity_curve.append(total_equity)
        daily_dates.append(curr_d)

        # 2. Check for New Entries
        needed_slots = active_allowed_slots - len(open_positions)
        if needed_slots > 0 and (cash + cash_liquidbees) > 20000:
            if cash_liquidbees > 0:
                cash += cash_liquidbees
                cash_liquidbees = 0.0

            k_frac = compute_current_kelly_fraction(kelly_mode)

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
                if kelly_mode == "ATR_KELLY":
                    risk_rs = total_equity * k_frac
                    sl_dist = 2.0 * atr
                    shares = int(risk_rs / max(1.0, sl_dist))
                    alloc = shares * cp
                    if alloc > cash * 0.45:
                        alloc = cash * 0.45
                        shares = int(alloc / cp)
                else:
                    slot_capital = total_equity * k_frac
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

        # 3. Fortress Cash Sweep if slots restricted
        if bear_fortress_active and not is_bull and len(open_positions) <= 1 and cash > 50000:
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
        "mode": kelly_mode,
        "final_val": round(final_val, 2),
        "cagr": round(cagr, 2),
        "multiple": round(final_val / initial_capital, 2),
        "max_dd": round(max_dd, 2),
        "calmar": round(calmar, 2),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(pf, 2),
        "payoff_ratio": round(payoff, 2),
        "total_trades": len(closed_trades)
    }


def run_all_kelly_backtests():
    t0 = time.time()
    logger.info("Starting Full 5-Year Kelly Criterion Sizing Audit (2021-2026)...")

    mkt_map, trading_dates, stock_dfs = load_fast_5year_market_and_stocks(DB_PATH)
    start_d = date(2021, 9, 27)
    end_d = date(2026, 9, 25)

    print("\n" + "=" * 90)
    print("📊 1. SWING CHAMPION: FIXED FRACTIONAL VS KELLY CRITERION VARIANTS")
    print("=" * 90)

    modes = ["BASELINE", "HALF_KELLY", "QUARTER_KELLY", "FULL_KELLY", "ATR_KELLY"]
    swing_results = []

    for m in modes:
        res = run_swing_with_kelly_sizing(
            trading_dates, stock_dfs, mkt_map,
            initial_capital=500000.0,
            start_date=start_d, end_date=end_d,
            kelly_mode=m
        )
        swing_results.append(res)
        print(f"[{res['mode']:<14}] Final: ₹{res['final_val']:>12,.2f} | CAGR: {res['cagr']:>6.2f}% | MaxDD: {res['max_dd']:>5.2f}% | Calmar: {res['calmar']:>5.2f} | PF: {res['profit_factor']:>4.2f}x | Trades: {res['total_trades']}")

    print("\n" + "=" * 90)
    print("📊 2. SIP CHAMPION: EQUAL SIZING VS CONVICTION/KELLY ASYMMETRIC SIZING")
    print("=" * 90)

    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    session = Session()

    sip_variants = [
        ("Baseline (Equal Sizing)", {**BASE_CHAMP, "sizing_mode": "EQUAL"}),
        ("Conviction/Kelly Sizing [30, 25, 20, 15, 10]", {
            **BASE_CHAMP,
            "sizing_mode": "CONVICTION",
            "enable_conviction_weighting": True,
            "conviction_weights": [0.30, 0.25, 0.20, 0.15, 0.10]
        }),
        ("Steep Kelly Sizing [38, 28, 18, 11, 5]", {
            **BASE_CHAMP,
            "sizing_mode": "CONVICTION",
            "enable_conviction_weighting": True,
            "conviction_weights": [0.38, 0.28, 0.18, 0.11, 0.05]
        }),
        ("Inverse Vol / Risk Parity Sizing", {
            **BASE_CHAMP,
            "sizing_mode": "INVERSE_VOL"
        })
    ]

    sip_results = []
    for name, params in sip_variants:
        res = run_monthly_sip_backtest(session, **params)
        cagr_xirr = res.get("strategy_net_xirr", 0.0)
        final_cor = res.get("final_strategy_value", 0.0)
        tot_inv = res.get("total_capital_invested", 0.0)
        mult = final_cor / max(1.0, tot_inv)
        pf = res.get("profit_factor", 0.0)
        mdd = res.get("strategy_max_dd", 0.0)
        sip_results.append({
            "name": name,
            "final_value": final_cor,
            "invested": tot_inv,
            "multiplier": round(mult, 2),
            "xirr": round(cagr_xirr, 2),
            "profit_factor": round(pf, 2),
            "max_dd": round(mdd, 2)
        })
        print(f"[{name:<40}] Corpus: ₹{final_cor:>12,.2f} | XIRR: {cagr_xirr:>6.2f}% | Mult: {mult:>4.2f}x | PF: {pf:>4.2f}x | MaxDD: {mdd:>5.2f}%")

    session.close()

    print("\n" + "=" * 90)
    print("🏁 SUMMARY OF FINDINGS")
    print("=" * 90)
    print(f"Total time taken: {time.time()-t0:.2f}s")


if __name__ == "__main__":
    run_all_kelly_backtests()
