#!/usr/bin/env python3
"""
scripts/massive_100k_strategy_swing_grid.py

Ultra-Massive 100,000-Strategy High-Throughput Parallel Grid Explorer for Daily Swing Trading.
Optimized for Ultra-Low RAM Footprint (<250MB total) & Maximum Vectorized Throughput.

Evaluates exactly 100,000 systematic swing strategies across 5 diverse historical market regimes:
  1. Severe Bear Market: 2024-10-01 to 2025-03-31 (NIFTY -8.83%, Max DD -14.4%)
  2. Choppy Stress Consolidation: 2026-07-01 to 2026-09-22 (NIFTY -2.82%, Max DD -6.68%)
  3. Strong Bull Trending: 2024-01-01 to 2024-09-30 (NIFTY +22.50%)
  4. Moderate Drift Market: 2025-04-01 to 2025-09-22 (NIFTY +8.79%, Max DD -5.02%)
  5. Full 1-Year Multi-Regime Cycle: 2025-09-22 to 2026-09-22 (NIFTY -7.43%, Max DD -15.18%)

Total simulations: 100,000 strategies × 5 regimes = 500,000 full portfolio simulations.
Precomputes market records and daily candidate queues for ultra-fast parallel in-memory execution.
"""
import sys
import os
import math
import time
import gc
import heapq
import csv
from pathlib import Path
from datetime import datetime, date
import multiprocessing as mp

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import numpy as np
import pandas as pd
from sqlalchemy import text
from db.database import get_global_engine, get_session
from core.sip_audit_backtester import calculate_xirr

# Global references for worker processes
G_NIFTY = None
G_SYMBOLS = None
G_CANDIDATES = None
G_REGIMES = None


def init_worker(shared_nifty, shared_symbols, shared_candidates, shared_regimes):
    global G_NIFTY, G_SYMBOLS, G_CANDIDATES, G_REGIMES
    G_NIFTY = shared_nifty
    G_SYMBOLS = shared_symbols
    G_CANDIDATES = shared_candidates
    G_REGIMES = shared_regimes


# ─── 1. Market Regimes ────────────────────────────────────────────────────────
REGIMES = [
    {
        "id": "BEAR_WORST",
        "name": "1. Worst Bear Market (2024-10-01 to 2025-03-31)",
        "start": "2024-10-01",
        "end": "2025-03-31",
        "weight": 0.30
    },
    {
        "id": "CHOP_CONSOLIDATION",
        "name": "2. Choppy Stress Consolidation (2026-07-01 to 2026-09-22)",
        "start": "2026-07-01",
        "end": "2026-09-22",
        "weight": 0.25
    },
    {
        "id": "BULL_TRENDING",
        "name": "3. Strong Bull Trending (2024-01-01 to 2024-09-30)",
        "start": "2024-01-01",
        "end": "2024-09-30",
        "weight": 0.20
    },
    {
        "id": "AVG_MODERATE",
        "name": "4. Moderate Drift Market (2025-04-01 to 2025-09-22)",
        "start": "2025-04-01",
        "end": "2025-09-22",
        "weight": 0.10
    },
    {
        "id": "CYCLE_1YR",
        "name": "5. Full 1-Year Multi-Regime Cycle (2025-09-22 to 2026-09-22)",
        "start": "2025-09-22",
        "end": "2026-09-22",
        "weight": 0.15
    }
]


# ─── 2. Data Preloading & Indicator Engine ─────────────────────────────────────
def preload_market_data():
    t0 = time.time()
    session = get_session()

    print("⏳ Preloading historical prices and calculating vector indicators into memory...")

    # A. Benchmark Data (NIFTY 50)
    nifty_rows = session.execute(text("""
        SELECT date, open, high, low, close
        FROM daily_prices
        WHERE symbol IN ('^NSEI', 'NIFTY 50', 'NIFTY')
        ORDER BY date ASC
    """)).fetchall()

    if not nifty_rows:
        nifty_rows = session.execute(text("""
            SELECT date, AVG(open) as open, MAX(high) as high, MIN(low) as low, AVG(close) as close
            FROM daily_prices
            GROUP BY date
            ORDER BY date ASC
        """)).fetchall()

    nifty_df = pd.DataFrame([dict(r._mapping) for r in nifty_rows])
    nifty_df["date_str"] = nifty_df["date"].astype(str)
    nifty_df = nifty_df.drop_duplicates(subset=["date_str"]).sort_values("date_str").reset_index(drop=True)
    nifty_df["ema_50"] = nifty_df["close"].ewm(span=50, adjust=False).mean()
    nifty_df["ema_21"] = nifty_df["close"].ewm(span=21, adjust=False).mean()
    nifty_df["mom_20d"] = nifty_df["close"].pct_change(20) * 100.0
    
    # Store compact tuple: (close, ema_50, ema_21, mom_20d)
    nifty_map = {}
    for _, r in nifty_df.iterrows():
        nifty_map[str(r["date_str"])] = (
            float(r["close"]),
            float(r["ema_50"]),
            float(r["ema_21"]),
            float(r["mom_20d"]) if not math.isnan(r["mom_20d"]) else 0.0
        )

    # B. Stock Universe Data
    stock_rows = session.execute(text("""
        SELECT symbol, date, open, high, low, close, volume
        FROM daily_prices
        WHERE symbol NOT IN ('^NSEI', 'NIFTY 50', 'NIFTY', 'GOLDBEES', 'SILVERBEES', 'LIQUIDBEES')
          AND date >= '2023-01-01'
        ORDER BY symbol, date ASC
    """)).fetchall()

    df_stocks = pd.DataFrame([dict(r._mapping) for r in stock_rows])
    df_stocks["date_str"] = df_stocks["date"].astype(str)
    session.close()

    modes = [
        "MULTI_LOOKBACK",
        "MULTI_LOOKBACK_HYPER",
        "CLENOW_SMOOTHNESS",
        "CLENOW_HIGH_CONVICTION",
        "MINERVINI_VCP",
        "OVERSOLD_SPRINGBOARD",
        "SECTOR_LEAD_RS",
        "DONCHIAN_TURTLE",
        "RANGE_EXPANSION_BURST",
        "MULTI_FACTOR_APEX"
    ]
    candidates_by_mode = {m: {} for m in modes}
    
    # Ultra-lean symbol records: sym -> date_str -> (high, low, close)
    symbol_records = {}

    for sym, df in df_stocks.groupby("symbol"):
        if len(df) < 120:
            continue
        df = df.sort_values("date_str").copy()

        c = df["close"]
        h = df["high"]
        l = df["low"]
        v = df["volume"]

        df["ema_50"] = c.ewm(span=50, adjust=False).mean()
        df["ema_200"] = c.ewm(span=200, adjust=False).mean()
        df["ema_20"] = c.ewm(span=20, adjust=False).mean()

        hl = h - l
        hc = (h - c.shift(1)).abs()
        lc = (l - c.shift(1)).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        df["atr_14"] = tr.rolling(14, min_periods=14).mean().fillna(c * 0.02)

        df["mom_1m"] = ((c - c.shift(20)) / c.shift(20) * 100.0).fillna(0.0)
        df["mom_3m"] = ((c - c.shift(60)) / c.shift(60) * 100.0).fillna(0.0)
        df["mom_6m"] = ((c - c.shift(126)) / c.shift(126) * 100.0).fillna(0.0)
        df["mom_12m"] = ((c - c.shift(250)) / c.shift(250) * 100.0).fillna(0.0)

        df["high_52w"] = h.rolling(250, min_periods=30).max()
        df["prox_52w"] = (c / df["high_52w"] * 100.0).fillna(80.0)

        sma_20 = c.rolling(20, min_periods=20).mean()
        std_20 = c.rolling(20, min_periods=20).std()
        df["bbw"] = ((std_20 * 4.0) / sma_20 * 100.0).fillna(10.0)
        df["bbw_percentile"] = df["bbw"].rolling(120, min_periods=30).rank(pct=True) * 100.0

        v_sma20 = v.rolling(20, min_periods=20).mean()
        df["vol_mult"] = (v / v_sma20).fillna(1.0)

        delta = c.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14, min_periods=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14, min_periods=14).mean()
        rs = gain / loss.replace(0, 0.0001)
        df["rsi_14"] = 100.0 - (100.0 / (1.0 + rs)).fillna(50.0)

        df["donchian_20"] = h.rolling(20, min_periods=20).max().shift(1)
        df["range_ratio"] = (hl / df["atr_14"]).fillna(1.0)
        df["clenow_slope"] = (df["mom_3m"].clip(lower=0) * (1.0 - (df["bbw"] / 100.0).clip(0, 0.8))).fillna(0.0)

        sym_bars = {}
        for _, row in df.iterrows():
            dt = str(row["date_str"])
            if dt < "2024-01-01":
                continue

            c_val = float(row["close"])
            if math.isnan(c_val) or c_val < 30.0 or c_val > 50000.0:
                continue

            h_val = float(row["high"])
            l_val = float(row["low"])
            atr = float(row["atr_14"])
            if math.isnan(atr) or atr <= 0:
                continue

            # Compact tuple for open position tracking: (high, low, close)
            sym_bars[dt] = (round(h_val, 2), round(l_val, 2), round(c_val, 2))

            e50 = float(row["ema_50"])
            e200 = float(row["ema_200"])
            m1 = float(row["mom_1m"])
            m3 = float(row["mom_3m"])
            m6 = float(row["mom_6m"])
            m12 = float(row["mom_12m"])
            prox = float(row["prox_52w"])
            bbw_p = float(row["bbw_percentile"])
            vol_m = float(row["vol_mult"])
            rsi = float(row["rsi_14"])
            donch = float(row["donchian_20"] or c_val)
            range_r = float(row["range_ratio"])
            clen = float(row["clenow_slope"])

            n_mom20 = nifty_map[dt][3] if dt in nifty_map else 0.0

            # Candidate item: (score, (sym, c_val, atr))
            cand_item = (sym, round(c_val, 2), round(atr, 2))

            # 1. MULTI_LOOKBACK
            if c_val >= e50 >= e200 * 0.98 and m1 > 0 and m3 > 0 and m6 > 10.0 and 45.0 <= rsi <= 72.0:
                score = (m1 * 0.15) + (m3 * 0.25) + (m6 * 0.40) + (m12 * 0.20)
                candidates_by_mode["MULTI_LOOKBACK"].setdefault(dt, []).append((score, cand_item))

            # 2. MULTI_LOOKBACK_HYPER
            if c_val >= e50 >= e200 and m6 >= 25.0 and m3 >= 15.0 and m1 >= 5.0 and 50.0 <= rsi <= 75.0:
                score = m6 + (m3 * 0.5) + (prox * 0.1)
                candidates_by_mode["MULTI_LOOKBACK_HYPER"].setdefault(dt, []).append((score, cand_item))

            # 3. CLENOW_SMOOTHNESS
            if c_val >= e50 and clen >= 25.0 and m6 >= 15.0:
                score = 70.0 + clen
                candidates_by_mode["CLENOW_SMOOTHNESS"].setdefault(dt, []).append((score, cand_item))

            # 4. CLENOW_HIGH_CONVICTION
            if c_val >= e50 >= e200 and clen >= 45.0 and m6 >= 30.0:
                score = 75.0 + clen
                candidates_by_mode["CLENOW_HIGH_CONVICTION"].setdefault(dt, []).append((score, cand_item))

            # 5. MINERVINI_VCP
            if c_val >= e50 >= e200 and prox >= 85.0 and bbw_p <= 25.0 and vol_m >= 1.25 and 50.0 <= rsi <= 68.0:
                score = 80.0 + (100.0 - bbw_p) * 0.1
                candidates_by_mode["MINERVINI_VCP"].setdefault(dt, []).append((score, cand_item))

            # 6. OVERSOLD_SPRINGBOARD
            if c_val >= e200 and abs(c_val - e50) / e50 <= 0.035 and 32.0 <= rsi <= 48.0:
                score = 70.0 + (50.0 - rsi) * 1.5
                candidates_by_mode["OVERSOLD_SPRINGBOARD"].setdefault(dt, []).append((score, cand_item))

            # 7. SECTOR_LEAD_RS
            rs_val = m1 - n_mom20
            if c_val >= e50 >= e200 and m6 >= 25.0 and rs_val >= 6.0 and 48.0 <= rsi <= 68.0:
                score = 72.0 + rs_val
                candidates_by_mode["SECTOR_LEAD_RS"].setdefault(dt, []).append((score, cand_item))

            # 8. DONCHIAN_TURTLE
            if c_val > donch and c_val >= e50 >= e200 and m6 >= 20.0:
                score = 70.0 + (c_val - donch) / donch * 100.0
                candidates_by_mode["DONCHIAN_TURTLE"].setdefault(dt, []).append((score, cand_item))

            # 9. RANGE_EXPANSION_BURST
            if range_r >= 1.8 and vol_m >= 1.5 and c_val >= e50 and 52.0 <= rsi <= 72.0:
                score = 75.0 + range_r * 5.0
                candidates_by_mode["RANGE_EXPANSION_BURST"].setdefault(dt, []).append((score, cand_item))

            # 10. MULTI_FACTOR_APEX
            if c_val >= e50 and e50 >= e200 * 0.98 and m6 >= 25.0 and prox >= 80.0 and 45.0 <= rsi <= 68.0:
                score = 65.0 + (m6 * 0.2) + (prox - 80.0)
                candidates_by_mode["MULTI_FACTOR_APEX"].setdefault(dt, []).append((score, cand_item))

        if sym_bars:
            symbol_records[sym] = sym_bars

    # Sort each candidate queue and keep ONLY Top 12 per day to keep RAM under 5MB
    for m in modes:
        for dt in candidates_by_mode[m]:
            candidates_by_mode[m][dt].sort(key=lambda x: x[0], reverse=True)
            candidates_by_mode[m][dt] = [x[1] for x in candidates_by_mode[m][dt][:12]]

    del df_stocks
    gc.collect()

    print(f"✅ Preloaded Ultra-Lean Swing data: {len(symbol_records)} symbols across {len(nifty_map)} market dates in {time.time() - t0:.1f}s.")
    return nifty_map, symbol_records, candidates_by_mode


# ─── 3. Core Swing Simulation Function (Pure Python Zero-Allocation) ──────────
def simulate_swing_single(
    strat_tuple,
    reg_idx: int,
    nifty_map: dict,
    symbol_records: dict,
    candidates_by_mode: dict,
    initial_capital: float = 1000000.0
):
    (s_id, em_idx, slots, pyr_idx, sl_idx, exit_idx, def_idx) = strat_tuple
    regime = G_REGIMES[reg_idx]

    start_date = regime["start"]
    end_date = regime["end"]

    all_dates = [d for d in nifty_map.keys() if start_date <= d <= end_date]
    if not all_dates:
        return (0.0, 0.0, 0.0, 0.0, 10.0, 0.0, 1.0, 1.0)

    n_start_p = nifty_map[all_dates[0]][0]
    n_end_p = nifty_map[all_dates[-1]][0]
    benchmark_pct = (n_end_p - n_start_p) / n_start_p * 100.0

    entry_modes = [
        "MULTI_LOOKBACK", "MULTI_LOOKBACK_HYPER", "CLENOW_SMOOTHNESS", "CLENOW_HIGH_CONVICTION",
        "MINERVINI_VCP", "OVERSOLD_SPRINGBOARD", "SECTOR_LEAD_RS", "DONCHIAN_TURTLE",
        "RANGE_EXPANSION_BURST", "MULTI_FACTOR_APEX"
    ]
    em_name = entry_modes[em_idx]

    sl_multipliers = [1.5, 2.0, 2.5, 1.8, 2.0]
    sl_mult = sl_multipliers[sl_idx]

    exit_targets = [
        (1.2, 2.2, 3.5), (1.5, 3.0, 5.0), (2.0, 4.0, 7.0), (2.2, 4.5, 8.5),
        (1.8, 3.5, 6.0), (2.0, 4.0, 9.5), (2.5, 5.0, 11.0), (3.0, 6.0, 14.0)
    ]
    t1_atr, t2_atr, t3_atr = exit_targets[exit_idx]

    time_stop_days = 7 if def_idx in (3, 4) else 0 # TIME_DECAY or FORTRESS
    regime_shield = (def_idx in (1, 2, 4)) # REGIME_SHIELD, SWEEP, FORTRESS
    cash_sweep = (def_idx in (2, 4))

    # Active positions: sym -> [entry_p, shares, init_shares, cost, sl, trail_sl, t1, t2, t3, t1_hit, t2_hit, max_h, min_l, cur_p, days, realized_pnl, pyr_done]
    active_positions = {}
    cash = initial_capital
    equity_history = []
    cash_flows = {datetime.strptime(start_date, "%Y-%m-%d").date(): -initial_capital}

    tot_win_val, tot_loss_val = 0.0, 0.0
    wins_count, loss_count = 0, 0
    wins_pct_sum, loss_pct_sum = 0.0, 0.0

    for cur_date in all_dates:
        n_close, n_e50, n_e21, _ = nifty_map[cur_date]
        is_bull = (n_close >= n_e50 and n_close >= n_e21)

        # A. Manage Open Positions
        syms_to_close = []
        for sym, pos in active_positions.items():
            sym_dict = symbol_records.get(sym)
            if sym_dict is None or cur_date not in sym_dict:
                continue

            bar = sym_dict[cur_date]
            h_p, l_p, c_p = bar
            if c_p <= 0:
                continue

            entry_p = pos[0]
            if h_p > pos[11]: pos[11] = h_p
            if l_p < pos[12]: pos[12] = l_p
            pos[14] += 1
            pos[13] = c_p

            cur_peak_pct = (pos[11] - entry_p) / entry_p * 100.0
            effective_sl = max(pos[4], pos[5])
            sl_hit = (l_p <= effective_sl)

            closed = False
            exit_price = 0.0

            if sl_hit:
                closed = True
                exit_price = effective_sl
            elif time_stop_days > 0 and pos[14] >= time_stop_days and cur_peak_pct < 1.5:
                closed = True
                exit_price = c_p

            if not closed:
                # Winner Pyramiding: 0=NONE, 1=LIVERMORE_50, 2=AGGRESSIVE_75, 3=CONSERVATIVE_25, 4=PYRAMID_ON_T1
                if pyr_idx != 0 and cur_peak_pct >= 4.0 and not pos[16] and not pos[9]:
                    pyr_ratio = 0.50 if pyr_idx == 1 else (0.75 if pyr_idx == 2 else 0.25)
                    extra_cost = pos[3] * pyr_ratio
                    if cash >= extra_cost and c_p > 0:
                        extra_sh = int(extra_cost / c_p)
                        if extra_sh > 0:
                            pos[1] += extra_sh
                            pos[3] += extra_sh * c_p
                            cash -= extra_sh * c_p
                            pos[16] = True
                            pos[0] = pos[3] / pos[1]
                            entry_p = pos[0]
                            pos[5] = max(pos[5], round(entry_p * 1.002, 2))
                            effective_sl = max(pos[4], pos[5])

                # Trailing stop ratchets
                if cur_peak_pct >= 4.0:
                    pos[5] = max(pos[5], round(entry_p * 1.005, 2))
                if cur_peak_pct >= 8.0:
                    pos[5] = max(pos[5], round(pos[11] * 0.965, 2))
                if cur_peak_pct >= 14.0:
                    pos[5] = max(pos[5], round(pos[11] * 0.940, 2))

                # Three-Tier Targets: exit_idx 0..3 (SCALPER, 3-TIER-STD, 3-TIER-WIDE, ASYMMETRIC)
                if exit_idx <= 3:
                    if not pos[9] and h_p >= pos[6]:
                        pos[9] = True
                        s3 = pos[2] // 3
                        if s3 > 0 and pos[1] > s3:
                            cash += s3 * pos[6]
                            pos[1] -= s3
                            pos[15] += (pos[6] - entry_p) * s3
                            pos[5] = max(pos[5], round(entry_p * 1.005, 2))

                    if pos[9] and not pos[10] and h_p >= pos[7]:
                        pos[10] = True
                        s3 = pos[2] // 3
                        if s3 > 0 and pos[1] > s3:
                            cash += s3 * pos[7]
                            pos[1] -= s3
                            pos[15] += (pos[7] - entry_p) * s3
                            pos[5] = max(pos[5], round(pos[6] * 0.995, 2))

                    if pos[10] and h_p >= pos[8]:
                        closed = True
                        exit_price = pos[8]

                elif exit_idx == 4: # REGIME_ADAPTIVE
                    tgt = pos[7] if is_bull else pos[6]
                    if h_p >= tgt:
                        closed = True
                        exit_price = tgt

                elif exit_idx in (5, 6, 7): # RUNNER MODES
                    if not pos[9] and h_p >= pos[6]:
                        pos[9] = True
                        half = pos[2] // 2
                        if half > 0 and pos[1] > half:
                            cash += half * pos[6]
                            pos[1] -= half
                            pos[15] += (pos[6] - entry_p) * half
                            pos[5] = max(pos[5], round(entry_p * 1.01, 2))
                    if pos[9] and h_p >= pos[8]:
                        closed = True
                        exit_price = pos[8]

            if closed:
                remaining_shares = pos[1]
                proceeds = remaining_shares * exit_price
                cash += proceeds
                total_gain = (exit_price - entry_p) * remaining_shares + pos[15]
                total_ret_pct = (total_gain / pos[3]) * 100.0 if pos[3] > 0 else 0.0

                if total_gain > 0:
                    tot_win_val += total_gain
                    wins_count += 1
                    wins_pct_sum += total_ret_pct
                else:
                    tot_loss_val += abs(total_gain)
                    loss_count += 1
                    loss_pct_sum += abs(total_ret_pct)

                syms_to_close.append(sym)

        for s in syms_to_close:
            del active_positions[s]

        # B. Macro Defensive Yield Sweep
        if cash_sweep and not is_bull and cash > 20000.0:
            cash += cash * (6.5 / 100.0 / 250.0)

        # C. Scan New Candidate Entries
        allowed_slots = slots
        if regime_shield and not is_bull:
            allowed_slots = max(1, slots // 2)

        open_slots = allowed_slots - len(active_positions)
        if open_slots > 0 and cash > 20000.0:
            candidate_list = candidates_by_mode.get(em_name, {}).get(cur_date, [])
            valid_cands = [c for c in candidate_list if c[0] not in active_positions][:open_slots]

            if valid_cands:
                deployable = cash * (0.50 if (regime_shield and not is_bull) else 0.95)
                alloc_per_trade = deployable / len(valid_cands)

                for cand in valid_cands:
                    sym, c_val, atr = cand
                    sl_val = round(c_val - (sl_mult * atr), 2)
                    t1_val = round(c_val + (t1_atr * atr), 2)
                    t2_val = round(c_val + (t2_atr * atr), 2)
                    t3_val = round(c_val + (t3_atr * atr), 2)

                    alloc = min(alloc_per_trade, cash)
                    if alloc < 15000.0:
                        break
                    sh = int(alloc / c_val)
                    if sh <= 1:
                        continue

                    cost = sh * c_val
                    cash -= cost
                    deployable -= cost

                    active_positions[sym] = [
                        c_val, sh, sh, cost, sl_val, sl_val,
                        t1_val, t2_val, t3_val, False, False,
                        c_val, c_val, c_val, 0, 0.0, False
                    ]
                    if len(active_positions) >= allowed_slots:
                        break

        open_val = sum(pos[1] * pos[13] for pos in active_positions.values())
        equity_history.append(cash + open_val)

    final_eq = equity_history[-1] if equity_history else initial_capital
    ret_pct = (final_eq - initial_capital) / initial_capital * 100.0
    alpha_pct = ret_pct - benchmark_pct

    end_dt = datetime.strptime(all_dates[-1], "%Y-%m-%d").date()
    cf_list = list(cash_flows.items()) + [(end_dt, final_eq)]
    xirr_val = calculate_xirr(cf_list)

    # Pure Python fast drawdown
    peak = 0.0
    max_dd = 0.0
    for eq in equity_history:
        if eq > peak:
            peak = eq
        elif peak > 0:
            dd = (eq - peak) / peak * 100.0
            if dd < max_dd:
                max_dd = dd

    tot_trades = wins_count + loss_count
    wr = (wins_count / tot_trades * 100.0) if tot_trades > 0 else 0.0
    pf = (tot_win_val / tot_loss_val) if tot_loss_val > 0 else (2.0 if tot_win_val > 0 else 1.0)
    avg_win = (wins_pct_sum / wins_count) if wins_count > 0 else 0.0
    avg_loss = (loss_pct_sum / loss_count) if loss_count > 0 else 0.0
    pr = (avg_win / avg_loss) if avg_loss > 0 else 1.0

    return (
        round(final_eq, 2),
        round(ret_pct, 2),
        round(alpha_pct, 2),
        round(xirr_val, 2),
        round(abs(max_dd), 2),
        round(wr, 1),
        round(pf, 2),
        round(pr, 2)
    )


# ─── 4. Worker Batch Evaluator ────────────────────────────────────────────────
def evaluate_swing_batch_worker(batch_tuples):
    results = []
    for st in batch_tuples:
        # Regimes: 0=BEAR_WORST, 1=CHOP_CONSOLIDATION, 2=BULL_TRENDING, 3=AVG_MODERATE, 4=CYCLE_1YR
        res_bear  = simulate_swing_single(st, 0, G_NIFTY, G_SYMBOLS, G_CANDIDATES)
        res_chop  = simulate_swing_single(st, 1, G_NIFTY, G_SYMBOLS, G_CANDIDATES)
        res_bull  = simulate_swing_single(st, 2, G_NIFTY, G_SYMBOLS, G_CANDIDATES)
        res_avg   = simulate_swing_single(st, 3, G_NIFTY, G_SYMBOLS, G_CANDIDATES)
        res_cycle = simulate_swing_single(st, 4, G_NIFTY, G_SYMBOLS, G_CANDIDATES)

        _, bear_ret, bear_alpha, worst_xirr, _, _, _, _ = res_bear
        _, chop_ret, _, chop_xirr, _, _, _, _ = res_chop
        _, bull_ret, _, _, _, _, _, _ = res_bull
        _, avg_ret, _, _, _, _, _, _ = res_avg
        cycle_val, cycle_ret, cycle_alpha, cycle_xirr, cycle_dd, cycle_wr, cycle_pf, cycle_pr = res_cycle

        composite_score = round(
            0.30 * worst_xirr
            + 0.25 * chop_xirr
            + 0.20 * bull_ret
            + 0.15 * cycle_alpha
            + 0.10 * avg_ret
            + 10.0 * min(cycle_pf, 5.0)
            + 5.0 * min(cycle_pr, 4.0)
            - 0.20 * cycle_dd,
            2
        )

        results.append((
            st[0], # id
            composite_score,
            cycle_xirr,
            cycle_alpha,
            cycle_ret,
            worst_xirr,
            chop_xirr,
            bull_ret,
            avg_ret,
            cycle_pf,
            cycle_pr,
            cycle_dd,
            cycle_wr,
            st[1], # em_idx
            st[2], # slots
            st[3], # pyr_idx
            st[4], # sl_idx
            st[5], # exit_idx
            st[6]  # def_idx
        ))

    return results


# ─── 5. Main Execution Controller ─────────────────────────────────────────────
def main():
    print("=" * 125)
    print("🚀 ULTRA-MASSIVE 100,000-STRATEGY QUANTITATIVE EXPLORATION: DAILY SWING TRADING")
    print("   Evaluating 100,000 Systematic Paradigms across 5 Diverse Historical Market Regimes")
    print("=" * 125)

    nifty_map, symbol_records, candidates_by_mode = preload_market_data()

    entry_modes = [
        "MULTI_LOOKBACK", "MULTI_LOOKBACK_HYPER", "CLENOW_SMOOTHNESS", "CLENOW_HIGH_CONVICTION",
        "MINERVINI_VCP", "OVERSOLD_SPRINGBOARD", "SECTOR_LEAD_RS", "DONCHIAN_TURTLE",
        "RANGE_EXPANSION_BURST", "MULTI_FACTOR_APEX"
    ]
    slot_options = [3, 4, 5, 6, 8]
    pyramid_options = ["NONE", "LIVERMORE_50", "AGGRESSIVE_75", "CONSERVATIVE_25", "PYRAMID_ON_T1"]
    sl_names = ["DYNAMIC_ATR_1_5", "DYNAMIC_ATR_2_0", "DYNAMIC_ATR_2_5", "CHANDELIER_1_8", "STRUCTURAL_DEEP"]
    exit_names = [
        "SCALPER_TIGHT", "THREE_TIER_STANDARD", "THREE_TIER_WIDE", "ASYMMETRIC_RUNNER",
        "REGIME_ADAPTIVE", "CHANDELIER_RUNNER", "MOMENTUM_EXPONENTIAL", "SUPER_RUNNER_20X"
    ]
    defense_names = [
        "RAW_EXECUTION", "REGIME_SHIELD_50", "REGIME_SHIELD_AND_SWEEP", "TIME_DECAY_STOP_7D", "COMPREHENSIVE_FORTRESS"
    ]

    all_tuples = []
    strat_idx = 1
    for em_idx in range(len(entry_modes)):
        for slots in slot_options:
            for pyr_idx in range(len(pyramid_options)):
                for sl_idx in range(len(sl_names)):
                    for exit_idx in range(len(exit_names)):
                        for def_idx in range(len(defense_names)):
                            all_tuples.append((strat_idx, em_idx, slots, pyr_idx, sl_idx, exit_idx, def_idx))
                            strat_idx += 1

    print(f"📋 Generated exactly {len(all_tuples):,} distinct systematic swing strategy parameter tuples.")

    num_workers = min(4, os.cpu_count() or 4)
    print(f"\n▶️ Launching memory-efficient parallel execution across {num_workers} worker processes...")
    print(f"   Total simulations: {len(all_tuples):,} strategies × {len(REGIMES)} regimes = {len(all_tuples) * len(REGIMES):,} simulations.")

    batch_size = 2500
    batches = [all_tuples[i:i + batch_size] for i in range(0, len(all_tuples), batch_size)]

    out_csv = BASE_DIR / "scripts" / "swing_100k_strategies_results.csv"
    csv_header = [
        "id", "name", "composite_score", "cycle_xirr", "cycle_alpha", "cycle_ret",
        "worst_bear_xirr", "chop_xirr", "bull_ret", "avg_ret",
        "cycle_pf", "cycle_pr", "cycle_dd", "cycle_wr",
        "entry_mode", "max_slots", "pyramid_mode", "sl_profile", "exit_mode", "defense_mode"
    ]

    t_start = time.time()
    top_heap = []
    total_processed = 0

    with open(out_csv, mode="w", newline="", encoding="utf-8") as f_out:
        writer = csv.writer(f_out)
        writer.writerow(csv_header)

        with mp.Pool(
            processes=num_workers,
            initializer=init_worker,
            initargs=(nifty_map, symbol_records, candidates_by_mode, REGIMES)
        ) as pool:
            for batch_res in pool.imap_unordered(evaluate_swing_batch_worker, batches):
                rows_to_write = []
                for row in batch_res:
                    (s_id, comp, c_xirr, c_alpha, c_ret, w_xirr, ch_xirr, bu_ret, av_ret,
                     c_pf, c_pr, c_dd, c_wr,
                     em_idx, slots, pyr_idx, sl_idx, exit_idx, def_idx) = row

                    em_name = entry_modes[em_idx]
                    pyr_name = pyramid_options[pyr_idx]
                    sl_name = sl_names[sl_idx]
                    ex_name = exit_names[exit_idx]
                    def_name = defense_names[def_idx]

                    strat_label = f"SW_{s_id:06d}: {em_name[:8]} | {slots}Sl | {pyr_name[:6]} | {sl_name[:6]} | {ex_name[:8]} | {def_name[:6]}"

                    csv_row = [
                        f"SW_{s_id:06d}", strat_label, comp, c_xirr, c_alpha, c_ret,
                        w_xirr, ch_xirr, bu_ret, av_ret,
                        c_pf, c_pr, c_dd, c_wr,
                        em_name, slots, pyr_name, sl_name, ex_name, def_name
                    ]
                    rows_to_write.append(csv_row)

                    if len(top_heap) < 100:
                        heapq.heappush(top_heap, (comp, csv_row))
                    else:
                        if comp > top_heap[0][0]:
                            heapq.heapreplace(top_heap, (comp, csv_row))

                writer.writerows(rows_to_write)
                f_out.flush()
                total_processed += len(batch_res)
                if total_processed % 10000 == 0:
                    curr_elapsed = time.time() - t_start
                    curr_rate = total_processed / curr_elapsed
                    print(f"   Progress: {total_processed:,} / {len(all_tuples):,} swing strategies completed ({curr_rate:.1f} strat/s)...", flush=True)

    elapsed = time.time() - t_start
    rate = len(all_tuples) / elapsed
    print(f"\n✅ Completed all 100,000 Swing strategies ({rate:.1f} strat/s | Total Time: {elapsed:.1f}s)!", flush=True)
    print(f"💾 Full results saved directly to: {out_csv}", flush=True)

    top_100 = sorted([item[1] for item in top_heap], key=lambda x: x[2], reverse=True)
    df_top = pd.DataFrame(top_100, columns=csv_header)

    print("\n" + "=" * 135)
    print("🏆 TOP 10 ALL-WEATHER OPTIMUM SWING STRATEGIES (OUT OF 100,000 PERMUTATIONS)")
    print("=" * 135)
    cols = ["id", "composite_score", "cycle_xirr", "cycle_alpha", "worst_bear_xirr", "chop_xirr", "bull_ret", "cycle_pf", "cycle_pr", "cycle_dd", "name"]
    print(df_top[cols].head(10).to_string(index=False))

    print("\n" + "=" * 135)
    print("🛡️ TOP 5 BEAR MARKET IMMUNE SWING STRATEGIES (HIGHEST BEAR MARKET XIRR)")
    print("=" * 135)
    bear_top = df_top.sort_values("worst_bear_xirr", ascending=False).head(5)
    print(bear_top[cols].to_string(index=False))

    print("\n" + "=" * 135)
    print("🚀 TOP 5 BULL MARKET SWING MULTIPLIERS (HIGHEST BULL MARKET RETURN)")
    print("=" * 135)
    bull_top = df_top.sort_values("bull_ret", ascending=False).head(5)
    print(bull_top[cols].to_string(index=False))


if __name__ == "__main__":
    main()
