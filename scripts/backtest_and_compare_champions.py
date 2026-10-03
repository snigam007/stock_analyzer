"""
scripts/backtest_and_compare_champions.py
==========================================
Airtight Backtest & Walk-Forward Comparison Suite:
Compares the Current Champions against the New Recommended Challengers
over the identical 5-Year Full-Cycle (2021-09-27 to 2026-09-25 / 1,298 sessions / 60 Months).
"""
import sys
import os
import json
import time
import math
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Any

import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from core.sip_audit_backtester import run_monthly_sip_backtest
from scripts.audit_true_quantum_champions_5year import load_fast_5year_market_and_stocks

DB_PATH = ROOT_DIR / "data" / "stock_analyzer.db"
engine = create_engine(f"sqlite:///{DB_PATH}")
Session = sessionmaker(bind=engine)

# ==============================================================================
# 1. SIP ENGINE BACKTESTING
# ==============================================================================
HOLY_GRAIL_BASE = dict(
    monthly_wallet=20000.0,
    strategy="PURE_STOCKS",
    months_lookback=60,
    exit_protocol="ADAPTIVE_STRUCTURAL",
    risk_profile="RISKY",
    annual_step_up_pct=10.0,
    pyramid_winners=True,
    enable_dip_buying=True,
    dip_threshold_pct=3.0,
    dip_deploy_pct=90.0,
    enable_parabolic_skim=True,
    skim_milestone_pct=120.0,
    skim_ratio_pct=10.0,
    max_position_cap_pct=50.0,
    enable_loss_cooldown=True,
    cooldown_days=60,
    enable_sector_momentum_gate=True,
    enable_macro_regime_gate=False,
    macro_hedge_pct=0.0,
    enable_macro_rotation=True,
    enable_stepladder_trailing=True,
    sizing_mode="EQUAL",
    enable_correlation_clustering=True,
    max_pairwise_correlation=0.65,
    enable_friction_and_tax=True,
    enable_tax_harvesting=True,
    enable_volatility_targeting=False,
    enable_3tier_harvest=False,
    enable_clenow_momentum=False,
    enable_breadth_gate=True,
    target_stock_count=5,
    min_momentum_hurdle_pct=30.0,
    enable_sector_rotation_score=False,
    sector_boost_pct=50.0,
    enable_liquid_sweep=True,
    liquid_yield_pct=6.5,
    enable_sector_duopoly=False,
    sector_duopoly_max=2,
    enable_dynamic_cap_expansion=False,
    expanded_cap_pct=55.0
)

SIP_EXPERIMENTS = [
    ("👑 Current Champion (5-Stock Holy Grail Base)", {}),
    ("⚡ Challenger 1: Apex Quad Alpha (4-Stock Basket)", {"target_stock_count": 4}),
    ("⚡ Challenger 2: Sector Duopoly Engine (5 Stocks, Max 2 in #1 Sector)", {"enable_sector_duopoly": True, "sector_duopoly_max": 2}),
    ("💎 Challenger 3: Apex Quad Alpha + Sector Duopoly (4 Stocks + Duopoly)", {"target_stock_count": 4, "enable_sector_duopoly": True, "sector_duopoly_max": 2}),
    ("🚀 Challenger 4: Dynamic Runner Cap Expansion (55% Cap)", {"enable_dynamic_cap_expansion": True, "expanded_cap_pct": 55.0})
]


def run_sip_comparisons():
    print("\n" + "=" * 115)
    print("  1. SYSTEMATIC SIP WEALTH ACCUMULATOR: CURRENT CHAMPION VS CHALLENGERS (5-YEAR / 60 MONTHS)")
    print("=" * 115)
    session = Session()
    sip_results = []
    try:
        for idx, (label, overrides) in enumerate(SIP_EXPERIMENTS):
            t0 = time.time()
            cfg = HOLY_GRAIL_BASE.copy()
            cfg.update(overrides)
            res = run_monthly_sip_backtest(session, **cfg)
            elapsed = time.time() - t0
            
            xirr = res.get("strategy_xirr", 0.0)
            corpus = res.get("final_strategy_value", 0.0)
            profit = res.get("net_strategy_profit", 0.0)
            pf = res.get("profit_factor", 0.0)
            payoff = res.get("payoff_ratio", 0.0)
            dd = res.get("max_drawdown_pct", 0.0)
            trades = res.get("total_trades", 0)
            win_rate = res.get("win_rate", 0.0)
            calmar = round(xirr / max(1.0, dd), 2)
            
            sip_results.append({
                "label": label, "xirr": xirr, "corpus": corpus, "profit": profit,
                "pf": pf, "payoff": payoff, "dd": dd, "trades": trades,
                "win_rate": win_rate, "calmar": calmar, "elapsed": elapsed
            })
            print(f"  [{idx+1}/{len(SIP_EXPERIMENTS)}] {label:<65} | XIRR: {xirr:5.2f}% | Corpus: ₹{corpus:,.0f} | PF: {pf:4.2f} | Payoff: {payoff:5.2f}x | DD: {dd:4.1f}% | Calmar: {calmar:4.2f} ({elapsed:.1f}s)")
    finally:
        session.close()
    return sip_results


# ==============================================================================
# 2. SWING ENGINE BACKTESTING
# ==============================================================================
def run_swing_variant(
    trading_dates, stock_dfs, mkt_map,
    initial_capital=500000.0,
    start_date=date(2021, 9, 27),
    end_date=date(2026, 9, 25),
    close_confirmed_sl=False,
    enable_stagnation_exit=True,
    sl_cap_pct=None
):
    filtered_dates = [d for d in trading_dates if start_date <= d <= end_date]
    if not filtered_dates:
        return {}

    cash = float(initial_capital)
    cash_liquidbees = 0.0
    open_positions = {}
    closed_trades = []
    equity_curve = []

    tiers = [(1.5, 0.33), (3.0, 0.33), (8.5, 0.34)]

    for curr_d in filtered_dates:
        mkt_row = mkt_map.get(curr_d)
        is_bull = mkt_row.is_bull if mkt_row else True
        active_allowed_slots = 3 if is_bull else 1

        # LiquidBees Yield Sweep (6.5% APY daily)
        if cash_liquidbees > 0:
            cash_liquidbees += cash_liquidbees * (0.065 / 365.0)

        # 1. Process Open Positions
        for sym in list(open_positions.keys()):
            pos = open_positions[sym]
            df_s = stock_dfs.get(sym)
            if df_s is None or curr_d not in df_s.index:
                continue

            row = df_s.loc[curr_d]
            h = float(row['high'])
            l = float(row['low'])
            c = float(row['close'])
            atr = pos['atr']

            # Stop Loss Trigger: Close-Confirmed vs Intraday Low
            sl_hit = (c <= pos['stop_loss']) if close_confirmed_sl else (l <= pos['stop_loss'])
            if sl_hit:
                exit_price = min(pos['stop_loss'], float(row['open'])) if not close_confirmed_sl else c
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

            # 15-Day Stagnation Exit
            if enable_stagnation_exit:
                holding_days = (curr_d - pos['entry_date']).days
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
                # Final Runner Tier (Trail Chandelier Stop)
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

        # 2. Portfolio Equity Check
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

            # Rolling Half-Kelly Sizing
            recent_closed = closed_trades[-30:] if len(closed_trades) >= 10 else []
            if len(recent_closed) >= 10:
                w_trades = [t['pnl'] for t in recent_closed if t['pnl'] > 0]
                l_trades = [abs(t['pnl']) for t in recent_closed if t['pnl'] <= 0]
                p_win = len(w_trades) / len(recent_closed)
                b_payoff = (np.mean(w_trades) / max(1.0, np.mean(l_trades))) if (w_trades and l_trades) else 3.0
            else:
                p_win = 0.30
                b_payoff = 3.0

            kelly_f = max(0.0, (p_win * b_payoff - (1.0 - p_win)) / max(0.1, b_payoff))
            half_kelly = 0.5 * kelly_f
            bounded_kelly_pct = min(0.333, max(0.220, half_kelly))
            slot_capital = total_equity * bounded_kelly_pct

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

                    # SL Distance Cap Check
                    if sl_cap_pct is not None:
                        sl_dist = (2.0 * atr) / cp * 100.0
                        if sl_dist > sl_cap_pct:
                            continue

                    # Multi-Lookback Momentum Screen
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

        # 4. Fortress Cash Sweep
        if not is_bull and len(open_positions) <= 1 and cash > 50000:
            sweep_amt = cash * 0.70
            cash -= sweep_amt
            cash_liquidbees += sweep_amt

    # Liquidate remaining positions
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
    payoff = (np.mean([t['pnl'] for t in wins]) / max(1.0, np.mean([abs(t['pnl']) for t in losses]))) if (wins and losses) else 0.0
    calmar = round(cagr / max(1.0, max_dd), 2)

    return {
        "final_val": round(final_val, 2),
        "cagr": round(cagr, 2),
        "multiple": round(final_val / initial_capital, 2),
        "max_dd": round(max_dd, 2),
        "trades": len(closed_trades),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(pf, 2),
        "payoff_ratio": round(payoff, 2),
        "calmar": calmar
    }


def run_swing_comparisons():
    print("\n" + "=" * 115)
    print("  2. SYSTEMATIC SWING ENGINE: CURRENT CHAMPION VS CHALLENGERS (5-YEAR FULL-CYCLE / 1,298 SESSIONS)")
    print("=" * 115)
    mkt_map, trading_dates, stock_dfs = load_fast_5year_market_and_stocks(DB_PATH)

    SWING_EXPERIMENTS = [
        ("👑 Current Champion (Intraday SL + 15D Rotation)", dict(close_confirmed_sl=False, enable_stagnation_exit=True, sl_cap_pct=None)),
        ("⚡ Challenger 1: Close-Confirmed Stop Loss (Daily Close <= SL)", dict(close_confirmed_sl=True, enable_stagnation_exit=True, sl_cap_pct=None)),
        ("⚡ Challenger 2: Close-Confirmed SL + SL Cap <= 6.5%", dict(close_confirmed_sl=True, enable_stagnation_exit=True, sl_cap_pct=6.5)),
        ("💎 Challenger 3: Pure Baseline Without 15D Stagnation (Intraday SL)", dict(close_confirmed_sl=False, enable_stagnation_exit=False, sl_cap_pct=None)),
        ("🏆 Challenger 4: The Apex Hardened Swing Champion (Close SL + 15D Rotation + SL Cap 6.5%)", dict(close_confirmed_sl=True, enable_stagnation_exit=True, sl_cap_pct=6.5))
    ]

    swing_results = []
    for idx, (label, kwargs) in enumerate(SWING_EXPERIMENTS):
        t0 = time.time()
        res = run_swing_variant(trading_dates, stock_dfs, mkt_map, **kwargs)
        elapsed = time.time() - t0
        res["label"] = label
        res["elapsed"] = elapsed
        swing_results.append(res)
        print(f"  [{idx+1}/{len(SWING_EXPERIMENTS)}] {label:<68} | Equity: ₹{res['final_val']:,.0f} ({res['multiple']}x) | CAGR: {res['cagr']:+5.2f}% | Max DD: {res['max_dd']:4.1f}% | PF: {res['profit_factor']:4.2f} | Win%: {res['win_rate']:4.1f}% | Calmar: {res['calmar']:4.2f} ({elapsed:.1f}s)")

    return swing_results


if __name__ == "__main__":
    t_start = time.time()
    sip_res = run_sip_comparisons()
    sw_res = run_swing_comparisons()
    
    # Save combined report
    combined = {
        "timestamp": datetime.now().isoformat(),
        "audit_window": "2021-09-27 to 2026-09-25 (5.0 Years)",
        "sip_comparisons": sip_res,
        "swing_comparisons": sw_res
    }
    out_file = ROOT_DIR / "data" / "challengers_vs_champions_audit.json"
    with open(out_file, "w") as f:
        json.dump(combined, f, indent=2)
    print(f"\nSaved comparison results to {out_file} (Total execution time: {time.time()-t_start:.1f}s)")
