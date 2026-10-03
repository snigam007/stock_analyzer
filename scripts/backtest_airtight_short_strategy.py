"""
scripts/backtest_airtight_short_strategy.py

Quantitative Verification & Backtest:
  1. Pure Short-Only Airtight Strategy
  2. Long-Only Champion Strategy (SW_005479 + SW_000640)
  3. Bi-Directional Fusion Strategy (Long in Bull + Short in Bear)

Evaluated across:
  - 2018 Small/Mid-cap Crash & NBFC Crisis
  - 2020 COVID-19 Flash Crash
  - 2022 Inflation & Geopolitical Chop
  - 2023 Bull Expansion
  - Multi-Year Comprehensive Cycle (2018 - 2026)
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
logger = logging.getLogger("short_backtest")


def simulate_bidirectional_swing_engine(
    mode: str, # "LONG_ONLY", "SHORT_ONLY", "BI_DIRECTIONAL"
    trading_dates: List[date],
    stock_dfs: Dict[str, pd.DataFrame],
    mkt_map: Dict[date, Any],
    initial_capital: float = 500000.0,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    max_slots: int = 3,
) -> Dict[str, Any]:
    """
    Simulates Systematic Swing Trading:
      - Long: MULTI_LOOKBACK Champion (Close >= 50 EMA >= 200 EMA, 1M/3M/6M Mom, 45<=RSI<=72)
      - Short: Airtight Bear Breakdown (Close <= 50 EMA <= 200 EMA, Mom < 0, 32<=RSI<=48, 1.5x ATR SL, 8D Stagnation)
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

        # LiquidBees daily sweep yield (6.5% annualized)
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

            # Stop Loss hit
            if l <= pos['stop_loss']:
                exit_price = min(pos['stop_loss'], row['open'])
                pnl = (exit_price - pos['avg_price']) * pos['shares']
                pnl_pct = (exit_price - pos['avg_price']) / pos['avg_price'] * 100.0
                cash += pos['shares'] * exit_price
                closed_trades.append({'symbol': sym, 'side': 'LONG', 'pnl': pnl, 'pnl_pct': pnl_pct, 'hold_days': (curr_d - pos['entry_date']).days})
                del open_longs[sym]
                continue

            # Pyramiding: +4% gain -> add +50% size, SL to breakeven
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
                # Runner tier
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
        # 2. MANAGE OPEN SHORTS (AIRTIGHT SHORT ENGINE)
        # -------------------------------------------------------------
        for sym, pos in list(open_shorts.items()):
            df_s = stock_dfs.get(sym)
            if df_s is None or curr_d not in df_s.index:
                continue

            row = df_s.loc[curr_d]
            h, l, c = row['high'], row['low'], row['close']
            atr = pos['atr']
            hold_days = (curr_d - pos['entry_date']).days

            # Short Stop Loss Hit (Price rallied above SL)
            if h >= pos['stop_loss']:
                exit_price = max(pos['stop_loss'], row['open'])
                pnl = (pos['avg_price'] - exit_price) * pos['shares']
                pnl_pct = (pos['avg_price'] - exit_price) / pos['avg_price'] * 100.0
                cash += (pos['margin_locked'] + pnl)
                closed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl, 'pnl_pct': pnl_pct, 'hold_days': hold_days})
                del open_shorts[sym]
                continue

            # Stagnation / Time-Stop: Shorts that don't drop in 8 trading sessions are vulnerable to short squeezes
            if pos['tier_idx'] == 0 and hold_days >= 8 and c >= pos['entry_price'] - (0.5 * atr):
                pnl = (pos['avg_price'] - c) * pos['shares']
                pnl_pct = (pos['avg_price'] - c) / pos['avg_price'] * 100.0
                cash += (pos['margin_locked'] + pnl)
                closed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl, 'pnl_pct': pnl_pct, 'hold_days': hold_days, 'reason': 'TIME_STOP'})
                del open_shorts[sym]
                continue

            # Target 1 (T1) Lock: Drop by 1.2x ATR -> Cover 50%, ratchet SL to breakeven
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
                    pos['stop_loss'] = min(pos['stop_loss'], pos['entry_price'] * 0.998) # Ratchet to Breakeven

            # Target 2 (T2) Runner: Drop by 2.8x ATR or Chandelier trail down
            elif pos['tier_idx'] == 1:
                if c < pos.get('lowest_close', c):
                    pos['lowest_close'] = c
                chand_stop = pos['lowest_close'] + (1.8 * atr)
                pos['stop_loss'] = min(pos['stop_loss'], chand_stop)
                if l <= pos['entry_price'] - (2.8 * atr):
                    pnl = (pos['avg_price'] - c) * pos['shares']
                    pnl_pct = (pos['avg_price'] - c) / pos['avg_price'] * 100.0
                    cash += (pos['margin_locked'] + pnl)
                    closed_trades.append({'symbol': sym, 'side': 'SHORT', 'pnl': pnl, 'pnl_pct': pnl_pct, 'hold_days': hold_days})
                    del open_shorts[sym]
                    continue

        # -------------------------------------------------------------
        # 3. POSITION OPENING RULES
        # -------------------------------------------------------------
        total_open = len(open_longs) + len(open_shorts)
        avail_slots = max_slots - total_open

        if avail_slots > 0 and cash > 25000:
            total_current_equity = cash + cash_liquidbees
            for sym, pos in open_longs.items():
                if sym in stock_dfs and curr_d in stock_dfs[sym].index:
                    total_current_equity += pos['shares'] * stock_dfs[sym].loc[curr_d, 'close']
            for sym, pos in open_shorts.items():
                if sym in stock_dfs and curr_d in stock_dfs[sym].index:
                    cur_p = stock_dfs[sym].loc[curr_d, 'close']
                    total_current_equity += pos['margin_locked'] + ((pos['avg_price'] - cur_p) * pos['shares'])

            slot_capital = total_current_equity / max_slots

            # Case A: Bull Regime -> Look for LONGS (if mode is LONG_ONLY or BI_DIRECTIONAL)
            if is_bull and mode in ("LONG_ONLY", "BI_DIRECTIONAL"):
                candidates = []
                for sym, df_s in stock_dfs.items():
                    if sym in open_longs or sym in open_shorts or curr_d not in df_s.index:
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

            # Case B: Bear Regime -> Look for SHORTS (if mode is SHORT_ONLY or BI_DIRECTIONAL)
            elif (not is_bull) and mode in ("SHORT_ONLY", "BI_DIRECTIONAL"):
                # Airtight Short Screener:
                # 1. Close <= 50 EMA <= 200 EMA * 1.02
                # 2. mom_1m < -2.0, mom_3m < -4.0
                # 3. 32.0 <= RSI <= 48.0 (Bearish expansion without deep oversold exhaustion)
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
                        # Sort by breakdown intensity (most negative multi-lookback score)
                        candidates.append({'symbol': sym, 'close': cp, 'atr': atr, 'score': row['multi_lookback_score']})
                candidates.sort(key=lambda x: x['score']) # Lowest score first (weakest stocks)

                for cand in candidates[:avail_slots]:
                    alloc = min(cash, slot_capital)
                    sh = int(alloc / cand['close'])
                    if sh > 0:
                        margin_req = sh * cand['close'] # 100% cash-covered margin for short swing
                        cash -= margin_req
                        open_shorts[cand['symbol']] = {
                            'entry_date': curr_d,
                            'entry_price': cand['close'],
                            'avg_price': cand['close'],
                            'shares': sh,
                            'original_shares': sh,
                            'margin_locked': margin_req,
                            'atr': cand['atr'],
                            'stop_loss': cand['close'] + (1.5 * cand['atr']), # Airtight 1.5x ATR SL
                            'tier_idx': 0,
                            'lowest_close': cand['close']
                        }

        # -------------------------------------------------------------
        # 4. SWEEP UNALLOCATED CASH TO LIQUIDBEES
        # -------------------------------------------------------------
        # If in bear fortress with no shorts or longs, sweep idle cash to LiquidBees
        if not is_bull and len(open_longs) == 0 and len(open_shorts) == 0 and cash > 50000:
            sweep = cash * 0.70
            cash -= sweep
            cash_liquidbees += sweep
        elif is_bull and cash_liquidbees > 0 and cash < 50000:
            # Recall cash for long entries
            cash += cash_liquidbees
            cash_liquidbees = 0.0

        # Compute Total Mark-to-Market Portfolio Equity
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

    # Calculate final metrics
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

    return {
        "mode": mode,
        "final_val": round(final_val, 2),
        "cagr": round(cagr, 2),
        "multiple": multiple,
        "max_dd": round(max_dd, 2),
        "calmar": calmar,
        "win_rate": win_rate,
        "trades": len(closed_trades),
        "long_trades": len([t for t in closed_trades if t.get('side') == 'LONG']),
        "short_trades": len([t for t in closed_trades if t.get('side') == 'SHORT']),
        "short_win_rate": round(len([t for t in wins if t.get('side') == 'SHORT']) / max(1, len([t for t in closed_trades if t.get('side') == 'SHORT'])) * 100.0, 1),
        "profit_factor": profit_factor,
        "payoff_ratio": payoff_ratio
    }


def run_comparative_backtest():
    logger.info("=" * 80)
    logger.info("  STARTING AIRTIGHT SHORT STRATEGY & BI-DIRECTIONAL FUSION BACKTEST")
    logger.info("=" * 80)

    df_all = load_universe_data(start_date="2017-01-01")
    daily_mkt, mkt_map = precompute_market_breadth_and_trend(df_all)
    stock_dfs = precompute_stock_technical_matrix(df_all)

    all_trading_dates = sorted([d for d in daily_mkt['date'] if d >= date(2018, 1, 1)])
    logger.info(f"Loaded {len(all_trading_dates)} trading sessions from {all_trading_dates[0]} to {all_trading_dates[-1]}")

    regimes = [
        {
            "name": "Phase 1: Full Multi-Regime Cycle (2018 - 2026)",
            "start": date(2018, 1, 1),
            "end": date(2026, 9, 22),
            "desc": "Complete 8.75-year economic & market cycle"
        },
        {
            "name": "Phase 2: 2018 Small/Mid-Cap Carnage & NBFC Crisis",
            "start": date(2018, 1, 1),
            "end": date(2018, 12, 31),
            "desc": "Severe liquidity crisis, IL&FS default, mid-caps -35%"
        },
        {
            "name": "Phase 3: 2020 COVID-19 Flash Crash",
            "start": date(2020, 1, 1),
            "end": date(2020, 6, 30),
            "desc": "Fast black-swan liquidity shock (-39.6% drop)"
        },
        {
            "name": "Phase 4: 2022 Inflation & Geopolitical Chop",
            "start": date(2022, 1, 1),
            "end": date(2022, 12, 31),
            "desc": "Fed aggressive tightening, crude spike, rangebound chop"
        },
        {
            "name": "Phase 5: 2023 Secular Bull Expansion",
            "start": date(2023, 1, 1),
            "end": date(2023, 12, 31),
            "desc": "Broad-market momentum expansion (+31% market gain)"
        }
    ]

    results = []

    for reg in regimes:
        logger.info(f"\n{'='*70}\n>>> REGIME: {reg['name']} ({reg['start']} to {reg['end']})\n{'='*70}")

        for mode, label in [
            ("LONG_ONLY", "1. Long-Only Champion (Baseline)"),
            ("SHORT_ONLY", "2. Airtight Short-Only Strategy"),
            ("BI_DIRECTIONAL", "3. Bi-Directional Fusion (Long Bull + Short Bear)")
        ]:
            res = simulate_bidirectional_swing_engine(
                mode=mode,
                trading_dates=all_trading_dates,
                stock_dfs=stock_dfs,
                mkt_map=mkt_map,
                initial_capital=500000.0,
                start_date=reg['start'],
                end_date=reg['end'],
                max_slots=3
            )
            res["regime"] = reg["name"]
            res["strategy_label"] = label
            results.append(res)

            logger.info(
                f"  [{label:45}] "
                f"CAGR: {res['cagr']:+6.2f}% | "
                f"Max DD: {res['max_dd']:5.2f}% | "
                f"Final: ₹{res['final_val']:11,.2f} | "
                f"Win: {res['win_rate']:4.1f}% | "
                f"Trades: {res['trades']:3d} (Shorts: {res['short_trades']:2d}, S-Win: {res['short_win_rate']}%) | "
                f"PF: {res['profit_factor']:4.2f}"
            )

    df_res = pd.DataFrame(results)
    out_csv = BASE_DIR / "scripts" / "airtight_short_and_bidirectional_backtest.csv"
    df_res.to_csv(out_csv, index=False)
    logger.info(f"\nSaved full comparative results to {out_csv}")


if __name__ == "__main__":
    run_comparative_backtest()
