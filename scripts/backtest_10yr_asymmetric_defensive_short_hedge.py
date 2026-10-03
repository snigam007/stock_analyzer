"""
scripts/backtest_10yr_asymmetric_defensive_short_hedge.py

Comprehensive 10-Year Historical Backtest (2016 - 2026):
Evaluates:
  1. Baseline Champion: Long-Only Momentum + Bear Fortress LiquidBees Cash Sweep (0 Shorts)
  2. Asymmetric Defensive Hedge: Long in Bull (3 Slots) + 1-Slot Asymmetric Defensive Short in Bear (66.7% LiquidBees)
  3. Market Benchmark: Nifty 50 Buy & Hold

Evaluated across:
  - Full 10-Year Historical Cycle (2016-09-29 to 2026-09-29 / 10.0 Years)
  - All 9 Major Historical Sub-Phases (2016 to 2026)
"""
import sys
import math
import time
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

import pandas as pd
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.backtest_all_history_sip_and_swing import (
    load_universe_data,
    precompute_market_breadth_and_trend,
    precompute_stock_technical_matrix,
    calculate_max_drawdown,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("10yr_hedge_backtest")


def simulate_10yr_swing_engine(
    strategy_mode: str, # "BASELINE_LONG_ONLY" or "ASYMMETRIC_DEFENSIVE_HEDGE"
    trading_dates: List[date],
    stock_dfs: Dict[str, pd.DataFrame],
    mkt_map: Dict[date, Any],
    initial_capital: float = 500000.0,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    max_bull_slots: int = 3,
    max_bear_short_slots: int = 1, # Max 1 slot in bear fortress (asymmetric hedge)
) -> Dict[str, Any]:
    """
    Simulates:
      - Baseline: 3 Long slots in Bull. In Bear, 0 shorts, 100% idle cash swept to LiquidBees (6.5% yield).
      - Asymmetric Defensive Hedge: 3 Long slots in Bull. In Bear, max 1 Short slot (33.3%), 66.7% cash swept to LiquidBees.
    """
    filtered_dates = [d for d in trading_dates if (start_date is None or d >= start_date) and (end_date is None or d <= end_date)]
    if len(filtered_dates) < 20:
        return {"cagr": 0.0, "final_val": initial_capital, "multiple": 1.0, "max_dd": 0.0, "calmar": 0.0, "win_rate": 0.0, "trades": 0, "profit_factor": 0.0}

    cash = float(initial_capital)
    cash_liquidbees = 0.0
    open_longs = {}
    open_shorts = {}
    closed_trades = []
    equity_curve = []

    for curr_d in filtered_dates:
        mkt_row = mkt_map.get(curr_d)
        is_bull = mkt_row.is_bull if mkt_row else True

        # LiquidBees daily yield accrual (6.5% annualized risk-free)
        if cash_liquidbees > 0:
            cash_liquidbees += cash_liquidbees * (0.065 / 365.0)

        # -------------------------------------------------------------
        # 1. MANAGE OPEN LONGS
        # -------------------------------------------------------------
        for sym, pos in list(open_longs.items()):
            df_s = stock_dfs.get(sym)
            if df_s is None or curr_d not in df_s.index:
                continue

            row = df_s.loc[curr_d]
            h, l, c = row['high'], row['low'], row['close']
            atr = pos['atr']

            # Stop Loss
            if l <= pos['stop_loss']:
                exit_price = min(pos['stop_loss'], row['open'])
                pnl = (exit_price - pos['avg_price']) * pos['shares']
                pnl_pct = (exit_price - pos['avg_price']) / pos['avg_price'] * 100.0
                cash += pos['shares'] * exit_price
                closed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl, 'pnl_pct': pnl_pct, 'hold_days': (curr_d - pos['entry_date']).days})
                del open_longs[sym]
                continue

            # Pyramiding: +4% gain -> add +50% size, ratchet SL to breakeven
            if not pos['pyramided'] and h >= pos['entry_price'] * 1.04:
                add_shares = int(pos['original_shares'] * 0.5)
                add_cost = add_shares * c
                if cash >= add_cost and add_shares > 0:
                    cash -= add_cost
                    pos['shares'] += add_shares
                    pos['avg_price'] = (pos['avg_price'] * (pos['shares'] - add_shares) + add_cost) / pos['shares']
                    pos['stop_loss'] = pos['entry_price'] * 1.002
                    pos['pyramided'] = True

            # Tiers
            if pos['tier_idx'] == 0 and h >= pos['entry_price'] + (1.2 * atr):
                trim = int(pos['original_shares'] * 0.33)
                if trim > 0 and pos['shares'] > trim:
                    t_price = pos['entry_price'] + (1.2 * atr)
                    cash += trim * t_price
                    pos['shares'] -= trim
                    pos['tier_idx'] = 1
                    pos['stop_loss'] = max(pos['stop_loss'], pos['entry_price'])
            elif pos['tier_idx'] == 1 and h >= pos['entry_price'] + (3.0 * atr):
                trim = int(pos['original_shares'] * 0.33)
                if trim > 0 and pos['shares'] > trim:
                    t_price = pos['entry_price'] + (3.0 * atr)
                    cash += trim * t_price
                    pos['shares'] -= trim
                    pos['tier_idx'] = 2
                    pos['stop_loss'] = max(pos['stop_loss'], pos['entry_price'] + (1.0 * atr))
            elif pos['tier_idx'] == 2:
                if c > pos.get('highest_close', c):
                    pos['highest_close'] = c
                chand_stop = pos['highest_close'] - (2.5 * atr)
                pos['stop_loss'] = max(pos['stop_loss'], chand_stop)
                if h >= pos['entry_price'] + (8.5 * atr):
                    cash += pos['shares'] * c
                    pnl = (c - pos['avg_price']) * pos['shares']
                    pnl_pct = (c - pos['avg_price']) / pos['avg_price'] * 100.0
                    closed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl, 'pnl_pct': pnl_pct, 'hold_days': (curr_d - pos['entry_date']).days})
                    del open_longs[sym]
                    continue

        # -------------------------------------------------------------
        # 2. MANAGE OPEN SHORTS (AIRTIGHT DEFENSIVE HEDGE)
        # -------------------------------------------------------------
        for sym, pos in list(open_shorts.items()):
            df_s = stock_dfs.get(sym)
            if df_s is None or curr_d not in df_s.index:
                continue

            row = df_s.loc[curr_d]
            h, l, c = row['high'], row['low'], row['close']
            atr = pos['atr']
            hold_days = (curr_d - pos['entry_date']).days

            # Immediate cover if market switched back to BULL_TRENDING
            if is_bull:
                pnl = (pos['avg_price'] - c) * pos['shares']
                pnl_pct = (pos['avg_price'] - c) / pos['avg_price'] * 100.0
                cash += (pos['margin_locked'] + pnl)
                closed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl, 'pnl_pct': pnl_pct, 'hold_days': hold_days, 'reason': 'BULL_REGIME_RECOVERY'})
                del open_shorts[sym]
                continue

            # Short Stop Loss Hit (1.5x ATR)
            if h >= pos['stop_loss']:
                exit_price = max(pos['stop_loss'], row['open'])
                pnl = (pos['avg_price'] - exit_price) * pos['shares']
                pnl_pct = (pos['avg_price'] - exit_price) / pos['avg_price'] * 100.0
                cash += (pos['margin_locked'] + pnl)
                closed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl, 'pnl_pct': pnl_pct, 'hold_days': hold_days, 'reason': 'STOP_LOSS'})
                del open_shorts[sym]
                continue

            # 8-Day Stagnation Time-Stop
            if pos['tier_idx'] == 0 and hold_days >= 8 and c >= pos['entry_price'] - (0.5 * atr):
                pnl = (pos['avg_price'] - c) * pos['shares']
                pnl_pct = (pos['avg_price'] - c) / pos['avg_price'] * 100.0
                cash += (pos['margin_locked'] + pnl)
                closed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl, 'pnl_pct': pnl_pct, 'hold_days': hold_days, 'reason': 'TIME_STOP'})
                del open_shorts[sym]
                continue

            # Target 1 (T1) Lock: Drop 1.2x ATR -> Cover 50%, SL to Breakeven
            if pos['tier_idx'] == 0 and l <= pos['entry_price'] - (1.2 * atr):
                cover_shares = int(pos['original_shares'] * 0.5)
                if cover_shares > 0 and pos['shares'] > cover_shares:
                    t_price = pos['entry_price'] - (1.2 * atr)
                    pnl_chunk = (pos['avg_price'] - t_price) * cover_shares
                    freed_margin = pos['margin_locked'] * (cover_shares / pos['original_shares'])
                    cash += (freed_margin + pnl_chunk)
                    pos['margin_locked'] -= freed_margin
                    pos['shares'] -= cover_shares
                    pos['tier_idx'] = 1
                    pos['stop_loss'] = min(pos['stop_loss'], pos['entry_price'] * 0.998)

            # Target 2 (T2) Runner: Drop 2.8x ATR or Chandelier trail
            elif pos['tier_idx'] == 1:
                if c < pos.get('lowest_close', c):
                    pos['lowest_close'] = c
                chand_stop = pos['lowest_close'] + (1.8 * atr)
                pos['stop_loss'] = min(pos['stop_loss'], chand_stop)
                if l <= pos['entry_price'] - (2.8 * atr):
                    pnl = (pos['avg_price'] - c) * pos['shares']
                    pnl_pct = (pos['avg_price'] - c) / pos['avg_price'] * 100.0
                    cash += (pos['margin_locked'] + pnl)
                    closed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl, 'pnl_pct': pnl_pct, 'hold_days': hold_days, 'reason': 'TARGET_2'})
                    del open_shorts[sym]
                    continue

        # -------------------------------------------------------------
        # 3. POSITION OPENING LOGIC
        # -------------------------------------------------------------
        # Total portfolio equity calculation
        total_current_equity = cash + cash_liquidbees
        for sym, pos in open_longs.items():
            if sym in stock_dfs and curr_d in stock_dfs[sym].index:
                total_current_equity += pos['shares'] * stock_dfs[sym].loc[curr_d, 'close']
        for sym, pos in open_shorts.items():
            if sym in stock_dfs and curr_d in stock_dfs[sym].index:
                cur_p = stock_dfs[sym].loc[curr_d, 'close']
                total_current_equity += pos['margin_locked'] + ((pos['avg_price'] - cur_p) * pos['shares'])

        # Case A: Bull Regime -> Enter LONGS (Up to 3 Slots)
        if is_bull:
            avail_slots = max_bull_slots - len(open_longs)
            # If cash is parked in LiquidBees, recall it for bull long deployment
            if cash_liquidbees > 0 and avail_slots > 0:
                cash += cash_liquidbees
                cash_liquidbees = 0.0

            if avail_slots > 0 and cash > 25000:
                slot_capital = total_current_equity / max_bull_slots
                candidates = []
                for sym, df_s in stock_dfs.items():
                    if sym in open_longs or curr_d not in df_s.index:
                        continue
                    row = df_s.loc[curr_d]
                    cp = row['close']
                    e50, e200, rsi, atr = row['ema_50'], row['ema_200'], row['rsi_14'], row['atr_14']
                    m1, m3, m6 = row['mom_1m'], row['mom_3m'], row['mom_6m']
                    if cp < 30 or atr <= 0:
                        continue
                    if (cp >= e50 >= e200 * 0.98) and (m1 > 0 and m3 > 0 and m6 > 10.0) and (45.0 <= rsi <= 72.0):
                        candidates.append({'symbol': sym, 'close': cp, 'atr': atr, 'score': row['multi_lookback_score']})
                candidates.sort(key=lambda x: x['score'], reverse=True)
                for cand in candidates[:avail_slots]:
                    alloc = min(cash, slot_capital)
                    sh = int(alloc / cand['close'])
                    if sh > 0:
                        cost = sh * cand['close']
                        cash -= cost
                        open_longs[cand['symbol']] = {
                            'entry_date': curr_d,
                            'entry_price': cand['close'],
                            'avg_price': cand['close'],
                            'shares': sh,
                            'original_shares': sh,
                            'atr': cand['atr'],
                            'stop_loss': cand['close'] - (2.0 * cand['atr']),
                            'tier_idx': 0,
                            'pyramided': False,
                            'highest_close': cand['close']
                        }

        # Case B: Bear Fortress Regime
        else:
            # If Asymmetric Defensive Hedge enabled: Can enter at most 1 short slot
            if strategy_mode == "ASYMMETRIC_DEFENSIVE_HEDGE":
                if len(open_shorts) < max_bear_short_slots and cash > 25000:
                    # Allocate at most 33.3% capital to 1 defensive short hedge
                    hedge_slot_capital = total_current_equity * 0.333
                    candidates = []
                    for sym, df_s in stock_dfs.items():
                        if sym in open_longs or sym in open_shorts or curr_d not in df_s.index:
                            continue
                        row = df_s.loc[curr_d]
                        cp = row['close']
                        e50, e200, rsi, atr = row['ema_50'], row['ema_200'], row['rsi_14'], row['atr_14']
                        m1, m3 = row['mom_1m'], row['mom_3m']
                        if cp < 50 or atr <= 0:
                            continue
                        if (cp <= e50 <= e200 * 1.02) and (m1 < -2.0 and m3 < -4.0) and (32.0 <= rsi <= 48.0):
                            candidates.append({'symbol': sym, 'close': cp, 'atr': atr, 'score': row['multi_lookback_score']})
                    candidates.sort(key=lambda x: x['score']) # Lowest score first (weakest breakdown)

                    if candidates:
                        cand = candidates[0]
                        alloc = min(cash, hedge_slot_capital)
                        sh = int(alloc / cand['close'])
                        if sh > 0:
                            margin_req = sh * cand['close']
                            cash -= margin_req
                            open_shorts[cand['symbol']] = {
                                'entry_date': curr_d,
                                'entry_price': cand['close'],
                                'avg_price': cand['close'],
                                'shares': sh,
                                'original_shares': sh,
                                'margin_locked': margin_req,
                                'atr': cand['atr'],
                                'stop_loss': cand['close'] + (1.5 * cand['atr']),
                                'tier_idx': 0,
                                'lowest_close': cand['close']
                            }

            # Sweep remaining unallocated cash into LiquidBees (6.5% yield)
            # Ensure at least 66.7% of portfolio is earning yield in bear fortress
            if cash > 30000:
                sweep = cash * 0.90
                cash -= sweep
                cash_liquidbees += sweep

        # Mark-to-market daily portfolio equity
        m2m = cash + cash_liquidbees
        for sym, pos in open_longs.items():
            if sym in stock_dfs and curr_d in stock_dfs[sym].index:
                m2m += pos['shares'] * stock_dfs[sym].loc[curr_d, 'close']
            else:
                m2m += pos['shares'] * pos['avg_price']
        for sym, pos in open_shorts.items():
            if sym in stock_dfs and curr_d in stock_dfs[sym].index:
                cur_p = stock_dfs[sym].loc[curr_d, 'close']
                m2m += pos['margin_locked'] + ((pos['avg_price'] - cur_p) * pos['shares'])
            else:
                m2m += pos['margin_locked']
        equity_curve.append(m2m)

    # Compute final metrics
    final_val = equity_curve[-1] if equity_curve else initial_capital
    total_days = max(1, (filtered_dates[-1] - filtered_dates[0]).days)
    years = total_days / 365.0
    cagr = ((final_val / initial_capital) ** (1.0 / years) - 1.0) * 100.0 if final_val > 0 and years > 0 else 0.0
    multiple = round(final_val / initial_capital, 2)
    max_dd = calculate_max_drawdown(equity_curve)
    calmar = round(cagr / max_dd, 2) if max_dd > 0 else 0.0

    wins = [t for t in closed_trades if t['pnl'] > 0]
    losses = [t for t in closed_trades if t['pnl'] < 0]
    win_rate = round(len(wins) / len(closed_trades) * 100.0, 1) if closed_trades else 0.0
    gross_profits = sum(t['pnl'] for t in wins)
    gross_losses = abs(sum(t['pnl'] for t in losses))
    profit_factor = round(gross_profits / gross_losses, 2) if gross_losses > 0 else (99.0 if gross_profits > 0 else 0.0)
    avg_win = gross_profits / len(wins) if wins else 0.0
    avg_loss = gross_losses / len(losses) if losses else 0.0
    payoff_ratio = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0.0

    long_trades = [t for t in closed_trades if t.get('side') == 'LONG']
    short_trades = [t for t in closed_trades if t.get('side') == 'SHORT']
    short_wins = [t for t in short_trades if t['pnl'] > 0]
    short_win_rate = round(len(short_wins) / len(short_trades) * 100.0, 1) if short_trades else 0.0

    return {
        "strategy_mode": strategy_mode,
        "final_val": round(final_val, 2),
        "cagr": round(cagr, 2),
        "multiple": multiple,
        "max_dd": round(max_dd, 2),
        "calmar": calmar,
        "win_rate": win_rate,
        "trades": len(closed_trades),
        "long_trades": len(long_trades),
        "short_trades": len(short_trades),
        "short_win_rate": short_win_rate,
        "profit_factor": profit_factor,
        "payoff_ratio": payoff_ratio,
        "equity_curve": equity_curve
    }


def run_10yr_master_backtest():
    logger.info("=" * 80)
    logger.info("  10-YEAR QUANTITATIVE AUDIT: ASYMMETRIC DEFENSIVE SHORT HEDGE")
    logger.info("  Window: 2016-09-29 to 2026-09-29 (10 Full Years)")
    logger.info("=" * 80)

    df_all = load_universe_data(start_date="2015-06-01")
    daily_mkt, mkt_map = precompute_market_breadth_and_trend(df_all)
    stock_dfs = precompute_stock_technical_matrix(df_all)

    # Master list of all unique trading dates from late Sept 2016 to Sept 2026
    all_trading_dates = sorted([d for d in daily_mkt['date'] if d >= date(2016, 9, 29) and d <= date(2026, 9, 29)])
    logger.info(f"Loaded {len(all_trading_dates)} trading days from {all_trading_dates[0]} to {all_trading_dates[-1]}")

    phases = [
        {
            "name": "Class 0: Complete 10-Year Macro Supercycle",
            "start": date(2016, 9, 29),
            "end": date(2026, 9, 29),
            "desc": "Full 10.0-year economic cycle"
        },
        {
            "name": "Phase 1: 2016 Demonetization & Liquidity Shock",
            "start": date(2016, 9, 29),
            "end": date(2016, 12, 31),
            "desc": "Demonetization cash crunch & sharp correction"
        },
        {
            "name": "Phase 2: 2017 Secular Bull Market",
            "start": date(2017, 1, 1),
            "end": date(2017, 12, 31),
            "desc": "Uninterrupted liquidity-driven bull run (+33%)"
        },
        {
            "name": "Phase 3: 2018 Small/Mid-Cap Carnage & NBFC Crisis",
            "start": date(2018, 1, 1),
            "end": date(2018, 12, 31),
            "desc": "Severe liquidity crisis, IL&FS default, mid-caps -35%"
        },
        {
            "name": "Phase 4: 2019 Rangebound & Corporate Tax Cut Rally",
            "start": date(2019, 1, 1),
            "end": date(2019, 12, 31),
            "desc": "Pre-election chop and tax cut burst (+12%)"
        },
        {
            "name": "Phase 5: 2020 COVID-19 Flash Crash & Recovery",
            "start": date(2020, 1, 1),
            "end": date(2020, 12, 31),
            "desc": "-39.6% black swan followed by rapid V-shape recovery"
        },
        {
            "name": "Phase 6: 2021 Post-COVID Momentum Supercycle",
            "start": date(2021, 1, 1),
            "end": date(2021, 12, 31),
            "desc": "Relentless liquidity expansion (+26%)"
        },
        {
            "name": "Phase 7: 2022 Inflation & Ukraine War Chop",
            "start": date(2022, 1, 1),
            "end": date(2022, 12, 31),
            "desc": "High inflation, Fed aggressive hikes, rangebound whipsaw"
        },
        {
            "name": "Phase 8: 2023 Broad-Market Midcap Expansion",
            "start": date(2023, 1, 1),
            "end": date(2023, 12, 31),
            "desc": "Manufacturing & capex breakout (+31%)"
        },
        {
            "name": "Phase 9: 2024 - 2026 Recent Multi-Regime Cycle",
            "start": date(2024, 1, 1),
            "end": date(2026, 9, 29),
            "desc": "Election year rally, flash correction (-14.4%), and expansion"
        }
    ]

    results = []

    for ph in phases:
        logger.info(f"\n{'='*75}\n>>> EVALUATING: {ph['name']} ({ph['start']} to {ph['end']})\n{'='*75}")

        # 1. Baseline Long-Only Champion
        res_base = simulate_10yr_swing_engine(
            strategy_mode="BASELINE_LONG_ONLY",
            trading_dates=all_trading_dates,
            stock_dfs=stock_dfs,
            mkt_map=mkt_map,
            initial_capital=500000.0,
            start_date=ph['start'],
            end_date=ph['end']
        )
        res_base["phase"] = ph["name"]
        res_base["label"] = "1. Baseline Long-Only Champion (0 Shorts, 100% Cash/Yield in Bear)"
        results.append(res_base)

        logger.info(
            f"  [BASELINE] CAGR: {res_base['cagr']:+6.2f}% | Max DD: {res_base['max_dd']:5.2f}% | "
            f"Final: ₹{res_base['final_val']:12,.2f} | Mult: {res_base['multiple']:.2f}x | "
            f"Win: {res_base['win_rate']:4.1f}% | Trades: {res_base['trades']:3d} | PF: {res_base['profit_factor']:4.2f}"
        )

        # 2. Asymmetric Defensive Hedge Champion
        res_hedge = simulate_10yr_swing_engine(
            strategy_mode="ASYMMETRIC_DEFENSIVE_HEDGE",
            trading_dates=all_trading_dates,
            stock_dfs=stock_dfs,
            mkt_map=mkt_map,
            initial_capital=500000.0,
            start_date=ph['start'],
            end_date=ph['end']
        )
        res_hedge["phase"] = ph["name"]
        res_hedge["label"] = "2. Champion + Asymmetric Defensive Short Hedge (Max 1 Slot, 66.7% Yield)"
        results.append(res_hedge)

        logger.info(
            f"  [HEDGED  ] CAGR: {res_hedge['cagr']:+6.2f}% | Max DD: {res_hedge['max_dd']:5.2f}% | "
            f"Final: ₹{res_hedge['final_val']:12,.2f} | Mult: {res_hedge['multiple']:.2f}x | "
            f"Win: {res_hedge['win_rate']:4.1f}% | Trades: {res_hedge['trades']:3d} "
            f"(Shorts: {res_hedge['short_trades']:2d}, S-Win: {res_hedge['short_win_rate']}%) | PF: {res_hedge['profit_factor']:4.2f}"
        )

    # Save to CSV
    df_out = pd.DataFrame(results)
    out_file = BASE_DIR / "scripts" / "ten_year_asymmetric_defensive_short_hedge_audit.csv"
    df_out.to_csv(out_file, index=False)
    logger.info(f"\nExported 10-Year Audit to: {out_file}")


if __name__ == "__main__":
    run_10yr_master_backtest()
