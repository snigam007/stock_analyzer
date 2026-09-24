#!/usr/bin/env python3
"""
scripts/massive_10000_strategy_swing_grid.py

Ultra-Massive 10,000-Strategy High-Throughput Quantitative Grid Explorer for Daily Swing Trading.
Evaluates exactly 10,000 systematic swing strategies across 5 diverse historical market regimes:
  1. Severe Bear Market: 2024-10-01 to 2025-03-31 (NIFTY -8.83%, Max DD -14.4%)
  2. Choppy Stress Consolidation: 2026-07-01 to 2026-09-22 (NIFTY -2.82%, Max DD -6.68%)
  3. Strong Bull Trending: 2024-01-01 to 2024-09-30 (NIFTY +22.50%)
  4. Moderate Drift Market: 2025-04-01 to 2025-09-22 (NIFTY +8.79%, Max DD -5.02%)
  5. Full 1-Year Multi-Regime Cycle: 2025-09-22 to 2026-09-22 (NIFTY -7.43%, Max DD -15.18%)

Total simulations: 10,000 strategies × 5 regimes = 50,000 full portfolio simulations.
Precomputes market records and daily candidate queues for ultra-fast in-memory execution.
"""
import sys
import os
import math
import time
import json
from pathlib import Path
from datetime import datetime, date

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
    nifty_map = nifty_df.set_index("date_str").to_dict(orient="index")

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

    prices_by_symbol = {}
    for sym, group in df_stocks.groupby("symbol"):
        if len(group) >= 120:
            prices_by_symbol[sym] = group.sort_values("date_str").reset_index(drop=True)

    session.close()
    print(f"✅ Loaded {len(prices_by_symbol)} symbols across {len(nifty_map)} market dates in {time.time() - t0:.1f}s.")
    return nifty_map, prices_by_symbol


def precompute_candidates_and_records(prices_by_symbol: dict, nifty_map: dict):
    t0 = time.time()
    print("⏳ Vector-computing indicators and candidate queues across all strategies...")

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
    symbol_records = {}

    for sym, df in prices_by_symbol.items():
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
        df["bbw_percentile"] = df["bbw"].rolling(60, min_periods=20).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1] * 100.0 if len(x) > 0 else 50.0, raw=False
        ).fillna(50.0)

        df["vol_ma20"] = v.rolling(20, min_periods=10).mean()
        df["vol_mult"] = (v / df["vol_ma20"]).fillna(1.0)
        df["donchian_20"] = h.rolling(20, min_periods=15).max().shift(1)
        df["range_ratio"] = ((h - l) / df["atr_14"]).fillna(1.0)

        delta = c.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14, min_periods=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14, min_periods=14).mean()
        rs = gain / loss.replace(0, np.nan)
        df["rsi_14"] = 100.0 - (100.0 / (1.0 + rs)).fillna(50.0)

        df["clenow_slope"] = (df["mom_3m"].clip(lower=0) * (1.0 - (df["bbw"] / 100.0).clip(0, 0.8))).fillna(0.0)

        records = df.set_index("date_str").to_dict(orient="index")
        symbol_records[sym] = records

        for dt, row in records.items():
            if dt not in nifty_map or dt < "2024-01-01":
                continue

            c_val = float(row["close"])
            if c_val < 30.0 or c_val > 50000.0:
                continue

            atr = float(row["atr_14"])
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

            n_mom20 = nifty_map[dt].get("mom_20d", 0.0)

            # 1. MULTI_LOOKBACK
            if c_val >= e50 >= e200 * 0.98 and m1 > 0 and m3 > 0 and m6 > 10.0 and 45.0 <= rsi <= 72.0:
                score = (m1 * 0.15) + (m3 * 0.25) + (m6 * 0.40) + (m12 * 0.20)
                candidates_by_mode["MULTI_LOOKBACK"].setdefault(dt, []).append({
                    "symbol": sym, "close": c_val, "atr": atr, "score": score
                })

            # 2. MULTI_LOOKBACK_HYPER
            if c_val >= e50 >= e200 and m6 >= 25.0 and m3 >= 15.0 and m1 >= 5.0 and 50.0 <= rsi <= 75.0:
                score = m6 + (m3 * 0.5) + (prox * 0.1)
                candidates_by_mode["MULTI_LOOKBACK_HYPER"].setdefault(dt, []).append({
                    "symbol": sym, "close": c_val, "atr": atr, "score": score
                })

            # 3. CLENOW_SMOOTHNESS
            if c_val >= e50 and clen >= 25.0 and m6 >= 15.0:
                score = 70.0 + clen
                candidates_by_mode["CLENOW_SMOOTHNESS"].setdefault(dt, []).append({
                    "symbol": sym, "close": c_val, "atr": atr, "score": score
                })

            # 4. CLENOW_HIGH_CONVICTION
            if c_val >= e50 >= e200 and clen >= 45.0 and m6 >= 30.0:
                score = 75.0 + clen
                candidates_by_mode["CLENOW_HIGH_CONVICTION"].setdefault(dt, []).append({
                    "symbol": sym, "close": c_val, "atr": atr, "score": score
                })

            # 5. MINERVINI_VCP
            if c_val >= e50 >= e200 and prox >= 85.0 and bbw_p <= 25.0 and vol_m >= 1.25 and 50.0 <= rsi <= 68.0:
                score = 80.0 + (100.0 - bbw_p) * 0.1
                candidates_by_mode["MINERVINI_VCP"].setdefault(dt, []).append({
                    "symbol": sym, "close": c_val, "atr": atr, "score": score
                })

            # 6. OVERSOLD_SPRINGBOARD
            if c_val >= e200 and abs(c_val - e50) / e50 <= 0.035 and 32.0 <= rsi <= 48.0:
                score = 70.0 + (50.0 - rsi) * 1.5
                candidates_by_mode["OVERSOLD_SPRINGBOARD"].setdefault(dt, []).append({
                    "symbol": sym, "close": c_val, "atr": atr, "score": score
                })

            # 7. SECTOR_LEAD_RS
            rs_val = m1 - n_mom20
            if c_val >= e50 >= e200 and m6 >= 25.0 and rs_val >= 6.0 and 48.0 <= rsi <= 68.0:
                score = 72.0 + rs_val
                candidates_by_mode["SECTOR_LEAD_RS"].setdefault(dt, []).append({
                    "symbol": sym, "close": c_val, "atr": atr, "score": score
                })

            # 8. DONCHIAN_TURTLE
            if c_val > donch and c_val >= e50 >= e200 and m6 >= 20.0:
                score = 70.0 + (c_val - donch) / donch * 100.0
                candidates_by_mode["DONCHIAN_TURTLE"].setdefault(dt, []).append({
                    "symbol": sym, "close": c_val, "atr": atr, "score": score
                })

            # 9. RANGE_EXPANSION_BURST
            if range_r >= 1.8 and vol_m >= 1.5 and c_val >= e50 and 52.0 <= rsi <= 72.0:
                score = 75.0 + range_r * 5.0
                candidates_by_mode["RANGE_EXPANSION_BURST"].setdefault(dt, []).append({
                    "symbol": sym, "close": c_val, "atr": atr, "score": score
                })

            # 10. MULTI_FACTOR_APEX
            if c_val >= e50 and e50 >= e200 * 0.98 and m6 >= 25.0 and prox >= 80.0 and 45.0 <= rsi <= 68.0:
                score = 65.0 + (m6 * 0.2) + (prox - 80.0)
                candidates_by_mode["MULTI_FACTOR_APEX"].setdefault(dt, []).append({
                    "symbol": sym, "close": c_val, "atr": atr, "score": score
                })

    for m in modes:
        for dt in candidates_by_mode[m]:
            candidates_by_mode[m][dt].sort(key=lambda x: x["score"], reverse=True)

    print(f"⚡ Precomputed candidates & records across {len(modes)} paradigms in {time.time() - t0:.1f}s.")
    return symbol_records, candidates_by_mode


# ─── 3. Core Simulation Function ──────────────────────────────────────────────
def simulate_swing_strategy(
    strategy: dict,
    regime: dict,
    nifty_map: dict,
    symbol_records: dict,
    candidates_by_mode: dict,
    initial_capital: float = 1000000.0
) -> dict:
    start_date = regime["start"]
    end_date = regime["end"]

    all_dates = [d for d in nifty_map.keys() if start_date <= d <= end_date]
    if not all_dates:
        return {}

    nifty_start = nifty_map[all_dates[0]]["close"]
    nifty_end = nifty_map[all_dates[-1]]["close"]
    benchmark_pct = (nifty_end - nifty_start) / nifty_start * 100.0

    entry_mode = strategy["entry_mode"]
    max_slots = strategy["max_slots"]
    pyramid_mode = strategy["pyramid_mode"]
    exit_mode = strategy["exit_mode"]
    defense_mode = strategy["defense_mode"]

    t1_atr = strategy["t1_atr"]
    t2_atr = strategy["t2_atr"]
    t3_atr = strategy["t3_atr"]
    sl_atr = strategy["sl_atr"]
    time_stop_days = strategy.get("time_stop_days", 0)

    # Decode defense mode
    regime_shield = ("REGIME_SHIELD" in defense_mode or "FORTRESS" in defense_mode)
    cash_sweep = ("SWEEP" in defense_mode or "FORTRESS" in defense_mode)
    if "TIME_DECAY" in defense_mode or "FORTRESS" in defense_mode:
        time_stop_days = max(time_stop_days, 7)

    active_positions = {}
    completed_trades = []
    cash = initial_capital
    equity_history = []
    cash_flows = {datetime.strptime(start_date, "%Y-%m-%d").date(): -initial_capital}

    for cur_date in all_dates:
        cur_nifty = nifty_map[cur_date]
        n_close = cur_nifty["close"]
        n_e50 = cur_nifty["ema_50"]
        n_e21 = cur_nifty["ema_21"]
        is_bull = (n_close >= n_e50 and n_close >= n_e21)

        # A. Manage Open Positions
        symbols_to_close = []
        for sym, pos in active_positions.items():
            sym_dict = symbol_records.get(sym)
            if sym_dict is None or cur_date not in sym_dict:
                continue

            bar = sym_dict[cur_date]
            h_p, l_p, c_p = float(bar["high"]), float(bar["low"]), float(bar["close"])
            if math.isnan(c_p) or c_p <= 0 or math.isnan(h_p) or math.isnan(l_p):
                continue

            entry_p = pos["entry_price"]
            pos["max_high"] = max(pos["max_high"], h_p)
            pos["min_low"] = min(pos["min_low"], l_p)
            pos["holding_days"] += 1
            pos["current_price"] = c_p

            cur_peak_pct = (pos["max_high"] - entry_p) / entry_p * 100.0

            effective_sl = max(pos["stop_loss"], pos["trailing_stop"])
            sl_hit = (l_p <= effective_sl)

            closed = False
            exit_price = 0.0
            exit_reason = ""

            if sl_hit:
                closed = True
                exit_price = effective_sl
                exit_reason = "BREAKEVEN_SL" if abs(effective_sl - entry_p)/entry_p < 0.008 else ("TRAILING_SL" if effective_sl > entry_p else "STOP_LOSS")
            else:
                if time_stop_days > 0 and pos["holding_days"] >= time_stop_days and cur_peak_pct < 1.5:
                    closed = True
                    exit_price = c_p
                    exit_reason = "TIME_STOP"

            if not closed:
                # Winner Pyramiding
                if pyramid_mode != "NONE" and cur_peak_pct >= 4.0 and not pos["pyramided"] and not pos["t1_hit"]:
                    pyr_ratio = 0.50 if pyramid_mode == "LIVERMORE_50" else (0.75 if pyramid_mode == "AGGRESSIVE_75" else 0.25)
                    extra_cost = pos["cost"] * pyr_ratio
                    if cash >= extra_cost and c_p > 0 and not math.isnan(c_p):
                        extra_sh = int(extra_cost / c_p)
                        if extra_sh > 0:
                            pos["shares"] += extra_sh
                            pos["cost"] += extra_sh * c_p
                            cash -= extra_sh * c_p
                            pos["pyramided"] = True
                            pos["entry_price"] = pos["cost"] / pos["shares"]
                            entry_p = pos["entry_price"]
                            pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.002, 2))
                            effective_sl = max(pos["stop_loss"], pos["trailing_stop"])

                # Trailing stop ratchets
                if cur_peak_pct >= 4.0:
                    pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.005, 2))
                if cur_peak_pct >= 8.0:
                    pos["trailing_stop"] = max(pos["trailing_stop"], round(pos["max_high"] * 0.965, 2))
                if cur_peak_pct >= 14.0:
                    pos["trailing_stop"] = max(pos["trailing_stop"], round(pos["max_high"] * 0.940, 2))
                effective_sl = max(pos["stop_loss"], pos["trailing_stop"])

                # Exits depending on mode
                if "THREE_TIER" in exit_mode or "SCALPER" in exit_mode:
                    if not pos["t1_hit"] and h_p >= pos["target_1"]:
                        pos["t1_hit"] = True
                        s3 = pos["initial_shares"] // 3
                        if s3 > 0 and pos["shares"] > s3:
                            proceeds = s3 * pos["target_1"]
                            cash += proceeds
                            pos["shares"] -= s3
                            pos["realized_pnl"] += (pos["target_1"] - entry_p) * s3
                            pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.005, 2))

                    if pos["t1_hit"] and not pos["t2_hit"] and h_p >= pos["target_2"]:
                        pos["t2_hit"] = True
                        s3 = pos["initial_shares"] // 3
                        if s3 > 0 and pos["shares"] > s3:
                            proceeds = s3 * pos["target_2"]
                            cash += proceeds
                            pos["shares"] -= s3
                            pos["realized_pnl"] += (pos["target_2"] - entry_p) * s3
                            pos["trailing_stop"] = max(pos["trailing_stop"], round(pos["target_1"] * 0.995, 2))

                    if pos["t2_hit"] and h_p >= pos["target_3"]:
                        closed = True
                        exit_price = pos["target_3"]
                        exit_reason = "TARGET_3_RUNNER"

                elif exit_mode == "REGIME_ADAPTIVE":
                    tgt = pos["target_2"] if is_bull else pos["target_1"]
                    if h_p >= tgt:
                        closed = True
                        exit_price = tgt
                        exit_reason = "REGIME_TARGET_HIT"

                elif exit_mode == "ASYMMETRIC_RUNNER" or exit_mode == "MOMENTUM_EXPONENTIAL":
                    if not pos["t1_hit"] and h_p >= pos["target_1"]:
                        pos["t1_hit"] = True
                        half_sh = pos["initial_shares"] // 2
                        if half_sh > 0 and pos["shares"] > half_sh:
                            proceeds = half_sh * pos["target_1"]
                            cash += proceeds
                            pos["shares"] -= half_sh
                            pos["realized_pnl"] += (pos["target_1"] - entry_p) * half_sh
                            pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.005, 2))

                    if pos["t1_hit"] and h_p >= pos["target_3"]:
                        closed = True
                        exit_price = pos["target_3"]
                        exit_reason = "ASYMMETRIC_RUNNER_EXIT"

                elif "CHANDELIER" in exit_mode or "SUPER_RUNNER" in exit_mode:
                    chandelier_sl = round(pos["max_high"] - (2.0 * pos["target_1"] * 0.05), 2)
                    if cur_peak_pct >= 6.0:
                        pos["trailing_stop"] = max(pos["trailing_stop"], chandelier_sl)
                    if h_p >= pos["target_3"]:
                        closed = True
                        exit_price = pos["target_3"]
                        exit_reason = "CHANDELIER_MAX_EXIT"

            if closed:
                proceeds = pos["shares"] * exit_price
                cash += proceeds
                tot_pnl = pos["realized_pnl"] + (proceeds - (pos["shares"] * entry_p))
                pct_return = (tot_pnl / pos["initial_cost"]) * 100.0
                completed_trades.append({
                    "symbol": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": cur_date,
                    "gain_pct": pct_return,
                    "gain_val": tot_pnl,
                    "holding_days": pos["holding_days"],
                    "exit_reason": exit_reason,
                    "pyramided": pos["pyramided"]
                })
                symbols_to_close.append(sym)

        for s in symbols_to_close:
            del active_positions[s]

        # B. Cash Sweeps
        if cash_sweep and cash > 5000.0:
            cash += cash * (6.5 / 100.0 / 365.0)

        # C. Deployable Capital & Slots
        deployable = cash
        if regime_shield and not is_bull:
            deployable = max(0.0, cash - initial_capital * 0.50)

        avail_slots = max_slots - len(active_positions)
        target_per_slot = initial_capital / max_slots

        if avail_slots > 0 and deployable >= (target_per_slot * 0.40):
            cand_pool = candidates_by_mode.get(entry_mode, {}).get(cur_date, [])
            for cand in cand_pool:
                if cand["symbol"] in active_positions:
                    continue

                c_val = cand["close"]
                atr = cand["atr"]
                if math.isnan(c_val) or c_val <= 0 or math.isnan(atr) or atr <= 0:
                    continue
                t1_val = round(c_val + t1_atr * atr, 2)
                t2_val = round(c_val + t2_atr * atr, 2)
                t3_val = round(c_val + t3_atr * atr, 2)
                sl_val = round(c_val - sl_atr * atr, 2)

                if pyramid_mode == "INVERSE_VOL_SIZING" and atr > 0:
                    slot_mult = min(1.5, max(0.6, (c_val * 0.02) / atr))
                    alloc = min(deployable * 0.95, target_per_slot * slot_mult)
                else:
                    alloc = min(deployable * 0.95, target_per_slot)

                if alloc < 15000.0:
                    break
                sh = int(alloc / c_val)
                if sh <= 1:
                    continue

                cost = sh * c_val
                cash -= cost
                deployable -= cost

                active_positions[cand["symbol"]] = {
                    "entry_date": cur_date,
                    "entry_price": c_val,
                    "shares": sh,
                    "initial_shares": sh,
                    "cost": cost,
                    "initial_cost": cost,
                    "stop_loss": sl_val,
                    "trailing_stop": sl_val,
                    "target_1": t1_val,
                    "target_2": t2_val,
                    "target_3": t3_val,
                    "t1_hit": False,
                    "t2_hit": False,
                    "max_high": c_val,
                    "min_low": c_val,
                    "current_price": c_val,
                    "holding_days": 0,
                    "realized_pnl": 0.0,
                    "pyramided": False
                }
                if len(active_positions) >= max_slots:
                    break

        open_val = sum(pos["shares"] * pos["current_price"] for pos in active_positions.values())
        tot_eq = cash + open_val
        equity_history.append(tot_eq)

    final_eq = equity_history[-1] if equity_history else initial_capital
    peak_eq = pd.Series(equity_history).cummax()
    max_dd = ((pd.Series(equity_history) - peak_eq) / peak_eq * 100.0).min()
    ret_pct = (final_eq - initial_capital) / initial_capital * 100.0
    alpha_pct = ret_pct - benchmark_pct

    end_dt = datetime.strptime(all_dates[-1], "%Y-%m-%d").date()
    cf_list = list(cash_flows.items()) + [(end_dt, final_eq)]
    xirr_val = calculate_xirr(cf_list)

    tot_trades = len(completed_trades)
    wins = [t for t in completed_trades if t["gain_val"] > 0]
    losses = [t for t in completed_trades if t["gain_val"] <= 0]
    wr = len(wins) / tot_trades * 100.0 if tot_trades > 0 else 0.0

    tot_win_val = sum(t["gain_val"] for t in wins)
    tot_loss_val = abs(sum(t["gain_val"] for t in losses))
    pf = tot_win_val / tot_loss_val if tot_loss_val > 0 else 1.0

    avg_win = np.mean([t["gain_pct"] for t in wins]) if wins else 0.0
    avg_loss = abs(np.mean([t["gain_pct"] for t in losses])) if losses else 0.0
    pr = avg_win / avg_loss if avg_loss > 0 else 1.0

    return {
        "final_equity": round(final_eq, 2),
        "return_pct": round(ret_pct, 2),
        "benchmark_pct": round(benchmark_pct, 2),
        "alpha_pct": round(alpha_pct, 2),
        "xirr": round(xirr_val, 2),
        "max_dd": round(abs(max_dd), 2),
        "win_rate": round(wr, 1),
        "profit_factor": round(pf, 2),
        "payoff_ratio": round(pr, 2),
        "total_trades": tot_trades
    }


# ─── 4. Build 10,000 Systematic Swing Strategies ──────────────────────────────
def build_10000_swing_strategies():
    strategies = []
    strat_idx = 1

    entry_modes = [
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
    ] # 10 archetypes

    slot_options = [3, 4, 5, 6, 8] # 5 slot sizes
    pyramid_options = ["NONE", "CONSERVATIVE_25", "LIVERMORE_50", "AGGRESSIVE_75", "INVERSE_VOL_SIZING"] # 5 options

    exit_options = [
        ("SCALPER_TIGHT", 1.2, 2.2, 3.5, 1.2, 4),
        ("THREE_TIER_STANDARD", 1.5, 3.0, 5.0, 1.5, 5),
        ("THREE_TIER_WIDE", 2.0, 4.0, 7.0, 1.5, 7),
        ("ASYMMETRIC_RUNNER", 2.2, 4.5, 8.5, 1.6, 6),
        ("REGIME_ADAPTIVE", 1.8, 3.5, 6.0, 1.5, 6),
        ("CHANDELIER_RUNNER", 2.0, 4.0, 9.5, 1.8, 8),
        ("MOMENTUM_EXPONENTIAL", 2.5, 5.0, 11.0, 1.8, 9),
        ("SUPER_RUNNER_15X", 3.0, 6.0, 14.0, 2.0, 10),
    ] # 8 exit geometries

    defense_modes = [
        "RAW_EXECUTION",
        "REGIME_SHIELD_50",
        "REGIME_SHIELD_AND_SWEEP",
        "TIME_DECAY_STOP_7D",
        "COMPREHENSIVE_FORTRESS"
    ] # 5 defense modes
    # Total combinations = 10 * 5 * 5 * 8 * 5 = exactly 10,000 strategies!

    for em in entry_modes:
        for slots in slot_options:
            for pyr in pyramid_options:
                for exit_name, t1, t2, t3, sl, t_stop in exit_options:
                    for def_mode in defense_modes:
                        name = f"SW_{strat_idx:05d}: {em[:10]} | {slots}Sl | {pyr[:8]} | {exit_name[:10]} | {def_mode[:8]}"
                        strategies.append({
                            "id": f"SW_{strat_idx:05d}",
                            "name": name,
                            "entry_mode": em,
                            "max_slots": slots,
                            "pyramid_mode": pyr,
                            "exit_mode": exit_name,
                            "defense_mode": def_mode,
                            "t1_atr": t1,
                            "t2_atr": t2,
                            "t3_atr": t3,
                            "sl_atr": sl,
                            "time_stop_days": t_stop,
                        })
                        strat_idx += 1

    return strategies


# ─── 5. Main Grid Execution ───────────────────────────────────────────────────
def main():
    print("=" * 125)
    print("🚀 ULTRA-MASSIVE 10,000-STRATEGY QUANTITATIVE EXPLORATION: DAILY SWING TRADING")
    print("   Evaluating 10,000 Systematic Paradigms across 5 Diverse Historical Market Regimes")
    print("=" * 125)

    nifty_map, prices_by_symbol = preload_market_data()
    symbol_records, candidates_by_mode = precompute_candidates_and_records(prices_by_symbol, nifty_map)
    strategies = build_10000_swing_strategies()
    print(f"📋 Generated {len(strategies)} distinct systematic swing strategy permutations.")

    results_table = []
    t_start = time.time()

    print(f"\n▶️ Launching multi-regime simulation grid (10,000 strategies × 5 regimes = 50,000 simulations)...")

    for i, strat in enumerate(strategies):
        regime_metrics = {}
        for reg in REGIMES:
            res = simulate_swing_strategy(strat, reg, nifty_map, symbol_records, candidates_by_mode)
            regime_metrics[reg["id"]] = res

        worst_xirr = regime_metrics["BEAR_WORST"].get("xirr", 0.0)
        chop_xirr = regime_metrics["CHOP_CONSOLIDATION"].get("xirr", 0.0)
        bull_ret = regime_metrics["BULL_TRENDING"].get("return_pct", 0.0)
        avg_ret = regime_metrics["AVG_MODERATE"].get("return_pct", 0.0)
        cycle_alpha = regime_metrics["CYCLE_1YR"].get("alpha_pct", 0.0)
        cycle_ret = regime_metrics["CYCLE_1YR"].get("return_pct", 0.0)
        cycle_xirr = regime_metrics["CYCLE_1YR"].get("xirr", 0.0)
        cycle_pr = regime_metrics["CYCLE_1YR"].get("payoff_ratio", 1.0)
        cycle_pf = regime_metrics["CYCLE_1YR"].get("profit_factor", 1.0)
        cycle_dd = regime_metrics["CYCLE_1YR"].get("max_dd", 20.0)
        cycle_wr = regime_metrics["CYCLE_1YR"].get("win_rate", 50.0)

        composite_score = (
            0.30 * worst_xirr
            + 0.25 * chop_xirr
            + 0.20 * bull_ret
            + 0.10 * avg_ret
            + 0.15 * cycle_alpha
        )

        row = {
            "id": strat["id"],
            "name": strat["name"],
            "entry_mode": strat["entry_mode"],
            "slots": strat["max_slots"],
            "pyramid": strat["pyramid_mode"],
            "exit_mode": strat["exit_mode"],
            "defense_mode": strat["defense_mode"],
            "composite_score": round(composite_score, 2),
            "worst_bear_ret": regime_metrics["BEAR_WORST"].get("return_pct", 0.0),
            "worst_bear_xirr": worst_xirr,
            "worst_bear_pr": regime_metrics["BEAR_WORST"].get("payoff_ratio", 0.0),
            "chop_ret": regime_metrics["CHOP_CONSOLIDATION"].get("return_pct", 0.0),
            "chop_xirr": chop_xirr,
            "chop_pr": regime_metrics["CHOP_CONSOLIDATION"].get("payoff_ratio", 0.0),
            "bull_ret": bull_ret,
            "avg_ret": avg_ret,
            "cycle_ret": cycle_ret,
            "cycle_alpha": cycle_alpha,
            "cycle_xirr": cycle_xirr,
            "cycle_pr": cycle_pr,
            "cycle_pf": cycle_pf,
            "cycle_dd": cycle_dd,
            "cycle_wr": cycle_wr,
        }
        results_table.append(row)

        if (i + 1) % 1000 == 0 or (i + 1) == len(strategies):
            rate = (i + 1) / (time.time() - t_start)
            print(f"   • Completed {i + 1:,}/{len(strategies):,} Swing strategies ({rate:.1f} strat/s | Elapsed: {time.time() - t_start:.1f}s)...")

    results_df = pd.DataFrame(results_table).sort_values("composite_score", ascending=False).reset_index(drop=True)

    out_csv = BASE_DIR / "scripts" / "swing_10000_strategies_results.csv"
    results_df.to_csv(out_csv, index=False)
    print(f"\n💾 Saved all 10,000 Swing strategy results to: {out_csv}")

    print("\n" + "=" * 135)
    print("🏆 TOP 10 ALL-WEATHER OPTIMUM SWING STRATEGIES (OUT OF 10,000 PERMUTATIONS)")
    print("=" * 135)
    cols = ["id", "composite_score", "cycle_xirr", "cycle_alpha", "worst_bear_xirr", "chop_xirr", "bull_ret", "cycle_pf", "cycle_pr", "cycle_dd", "name"]
    print(results_df[cols].head(10).to_string(index=False))

    print("\n" + "=" * 135)
    print("🛡️ TOP 5 BEAR MARKET IMMUNE SWING STRATEGIES (HIGHEST BEAR MARKET XIRR)")
    print("=" * 135)
    bear_top = results_df.sort_values("worst_bear_xirr", ascending=False).head(5)
    print(bear_top[cols].to_string(index=False))

    print("\n" + "=" * 135)
    print("🚀 TOP 5 BULL MARKET SWING MULTIPLIERS (HIGHEST BULL MARKET RETURN)")
    print("=" * 135)
    bull_top = results_df.sort_values("bull_ret", ascending=False).head(5)
    print(bull_top[cols].to_string(index=False))

    print(f"\n✅ 10,000 Swing Strategies Grid Completed in {time.time() - t_start:.1f} seconds!")


if __name__ == "__main__":
    main()
