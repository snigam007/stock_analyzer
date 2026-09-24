#!/usr/bin/env python3
"""
scripts/massive_100_strategy_swing_grid.py

Massive 100-Strategy High-Throughput Quantitative Grid Explorer for Daily Swing Trading.
Simulates 100 distinct strategies across 5 historical market regimes:
  1. Worst / Bear Market: 2024-10-01 to 2025-03-31 (NIFTY -8.83%, Max DD -14.4%)
  2. Choppy Consolidation: 2026-07-01 to 2026-09-22 (NIFTY -2.82%, Max DD -6.68%)
  3. Strong Bull Trending: 2024-01-01 to 2024-09-30 (NIFTY +22.50%)
  4. Moderate / Average: 2025-04-01 to 2025-09-22 (NIFTY +8.79%, Max DD -5.02%)
  5. 1-Year Multi-Regime Cycle: 2025-09-22 to 2026-09-22 (NIFTY -7.43%, Max DD -15.18%)

Evaluates Return, Alpha, Annualized Cash-Flow XIRR, Win Rate, Profit Factor, Payoff Ratio, Max DD, and Expectancy.
"""
import sys
import os
import math
import time
import json
from pathlib import Path
from datetime import datetime, date

# Ensure UTF-8 output on Windows
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
        "name": "4. Average Moderate Market (2025-04-01 to 2025-09-22)",
        "start": "2025-04-01",
        "end": "2025-09-22",
        "weight": 0.10
    },
    {
        "id": "CYCLE_1YR",
        "name": "5. 1-Year Multi-Regime Cycle (2025-09-22 to 2026-09-22)",
        "start": "2025-09-22",
        "end": "2026-09-22",
        "weight": 0.15
    }
]


# ─── 2. In-Memory Precomputation & Data Preloading ────────────────────────────
def preload_market_data():
    print("⏳ Preloading historical prices and calculating vector indicators into memory...")
    t0 = time.time()
    engine = get_global_engine()
    session = get_session(engine)

    # 1. NIFTY 50 Benchmark
    nifty_df = pd.read_sql(text("""
        SELECT date, close FROM index_prices
        WHERE symbol IN ('^NSEI', 'NIFTY 50') AND date >= '2023-01-01' AND date <= '2026-09-22'
        ORDER BY date ASC
    """), session.bind)
    nifty_df["date_str"] = nifty_df["date"].astype(str)
    nifty_df = nifty_df.drop_duplicates(subset=["date_str"]).sort_values("date_str").reset_index(drop=True)
    nifty_df["ema_21"] = nifty_df["close"].ewm(span=21, adjust=False).mean()
    nifty_df["ema_50"] = nifty_df["close"].ewm(span=50, adjust=False).mean()
    nifty_df["ema_200"] = nifty_df["close"].ewm(span=200, adjust=False).mean()
    nifty_df["mom_20d"] = (nifty_df["close"] - nifty_df["close"].shift(20)) / nifty_df["close"].shift(20) * 100.0
    nifty_map = nifty_df.set_index("date_str").to_dict(orient="index")

    # 2. Stock Prices
    df_prices = pd.read_sql(text("""
        SELECT dp.symbol, dp.date, dp.open, dp.high, dp.low, dp.close, dp.volume, stk.sector
        FROM daily_prices dp
        LEFT JOIN stocks stk ON dp.symbol = stk.symbol
        WHERE dp.date >= '2023-01-01' AND dp.date <= '2026-09-22'
        ORDER BY dp.symbol, dp.date ASC
    """), session.bind)

    prices_by_symbol = {}
    for sym, group in df_prices.groupby("symbol"):
        group = group.sort_values("date").reset_index(drop=True)
        if len(group) < 30:
            continue
        c = group["close"]
        group["ema_21"] = c.ewm(span=21, adjust=False).mean()
        group["ema_50"] = c.ewm(span=50, adjust=False).mean()
        group["ema_200"] = c.ewm(span=200, adjust=False).mean()

        # RSI 14
        delta = c.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(14, min_periods=14).mean()
        avg_loss = loss.rolling(14, min_periods=14).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        group["rsi_14"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)

        # ATR 14
        hl = group["high"] - group["low"]
        hc = (group["high"] - c.shift(1)).abs()
        lc = (group["low"] - c.shift(1)).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        group["atr_14"] = tr.rolling(14, min_periods=14).mean().fillna(c * 0.025)

        # Bollinger Band Width (BBW)
        sma_20 = c.rolling(20, min_periods=20).mean()
        std_20 = c.rolling(20, min_periods=20).std()
        group["bbw"] = ((std_20 * 4.0) / sma_20 * 100.0).fillna(10.0)
        group["bbw_pctile"] = group["bbw"].rolling(120, min_periods=30).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1] * 100.0 if len(x) > 0 else 50.0
        ).fillna(50.0)

        # 52-Week High & Proximity
        group["high_52w"] = group["high"].rolling(250, min_periods=30).max()
        group["prox_52w"] = (c / group["high_52w"] * 100.0).fillna(85.0)

        # Lookback Returns
        group["mom_1m"] = ((c - c.shift(20)) / c.shift(20) * 100.0).fillna(0.0)
        group["mom_3m"] = ((c - c.shift(60)) / c.shift(60) * 100.0).fillna(0.0)
        group["mom_6m"] = ((c - c.shift(126)) / c.shift(126) * 100.0).fillna(0.0)
        group["mom_12m"] = ((c - c.shift(250)) / c.shift(250) * 100.0).fillna(0.0)

        # Clenow Trend Smoothness
        y_log = np.log(c.replace(0, np.nan).ffill().values.astype(float))
        group["clenow"] = 0.0
        # Fast rolling Clenow approximation (R^2 * annualized slope over 90 days)
        if len(group) >= 90:
            roll_r2 = group["mom_3m"].clip(lower=0) * (1.0 - (group["bbw"] / 100.0).clip(0, 0.8))
            group["clenow"] = roll_r2.fillna(0.0)

        # Volume Multiplier
        vol_sma20 = group["volume"].rolling(20, min_periods=20).mean().replace(0, 1.0)
        group["vol_mult"] = (group["volume"] / vol_sma20).fillna(1.0)

        # Range expansion ratio (Day Range / ATR)
        group["range_ratio"] = (group["high"] - group["low"]) / group["atr_14"].replace(0, 1.0)

        # 20-Day Donchian Channel High
        group["donchian_high_20"] = group["high"].shift(1).rolling(20, min_periods=10).max()

        prices_by_symbol[sym] = group.set_index("date")

    session.close()
    elapsed = time.time() - t0
    print(f"✅ Preloaded {len(prices_by_symbol)} stocks across {len(nifty_map)} trading sessions in {elapsed:.1f}s.")
    return nifty_map, prices_by_symbol


def precompute_candidates_and_records(prices_by_symbol: dict, nifty_map: dict):
    t0 = time.time()
    modes = [
        "MULTI_LOOKBACK",
        "CLENOW_SMOOTHNESS",
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
        records = df.to_dict(orient="index")
        symbol_records[sym] = records

        for dt, r in records.items():
            c_val = float(r["close"])
            if c_val < 20.0:
                continue
            e50 = float(r["ema_50"])
            e200 = float(r["ema_200"])
            rsi = float(r["rsi_14"])
            atr = float(r["atr_14"])
            prox = float(r["prox_52w"])
            m1 = float(r["mom_1m"])
            m3 = float(r["mom_3m"])
            m6 = float(r["mom_6m"])
            m12 = float(r["mom_12m"])
            bbw_p = float(r["bbw_pctile"])
            vol_m = float(r["vol_mult"])
            donch = float(r["donchian_high_20"]) if not np.isnan(r.get("donchian_high_20", np.nan)) else c_val
            range_r = float(r["range_ratio"])
            clen = float(r.get("clenow", 0.0))

            cur_nifty = nifty_map.get(dt, {})
            n_mom20 = cur_nifty.get("mom_20d", 0.0)

            # 1. MULTI_LOOKBACK
            if c_val >= e50 >= e200 * 0.985 and m1 > 0 and m3 > 10 and m6 > 25 and m12 > 35:
                score = 75.0 + (m1 * 0.15 + m3 * 0.25 + m6 * 0.35 + m12 * 0.25)
                candidates_by_mode["MULTI_LOOKBACK"].setdefault(dt, []).append({
                    "symbol": sym, "close": c_val, "atr": atr, "score": score
                })

            # 2. CLENOW_SMOOTHNESS
            if c_val >= e50 >= e200 and clen >= 30.0 and m6 >= 20.0:
                score = 70.0 + clen
                candidates_by_mode["CLENOW_SMOOTHNESS"].setdefault(dt, []).append({
                    "symbol": sym, "close": c_val, "atr": atr, "score": score
                })

            # 3. MINERVINI_VCP
            if c_val >= e50 >= e200 and prox >= 85.0 and bbw_p <= 25.0 and vol_m >= 1.25 and 50.0 <= rsi <= 68.0:
                score = 80.0 + (100.0 - bbw_p) * 0.1
                candidates_by_mode["MINERVINI_VCP"].setdefault(dt, []).append({
                    "symbol": sym, "close": c_val, "atr": atr, "score": score
                })

            # 4. OVERSOLD_SPRINGBOARD
            if c_val >= e200 and abs(c_val - e50) / e50 <= 0.035 and 32.0 <= rsi <= 48.0:
                score = 70.0 + (50.0 - rsi) * 1.5
                candidates_by_mode["OVERSOLD_SPRINGBOARD"].setdefault(dt, []).append({
                    "symbol": sym, "close": c_val, "atr": atr, "score": score
                })

            # 5. SECTOR_LEAD_RS
            rs = m1 - n_mom20
            if c_val >= e50 >= e200 and m6 >= 25.0 and rs >= 6.0 and 48.0 <= rsi <= 68.0:
                score = 72.0 + rs
                candidates_by_mode["SECTOR_LEAD_RS"].setdefault(dt, []).append({
                    "symbol": sym, "close": c_val, "atr": atr, "score": score
                })

            # 6. DONCHIAN_TURTLE
            if c_val > donch and c_val >= e50 >= e200 and m6 >= 20.0:
                score = 70.0 + (c_val - donch) / donch * 100.0
                candidates_by_mode["DONCHIAN_TURTLE"].setdefault(dt, []).append({
                    "symbol": sym, "close": c_val, "atr": atr, "score": score
                })

            # 7. RANGE_EXPANSION_BURST
            if range_r >= 1.8 and vol_m >= 1.5 and c_val >= e50 and 52.0 <= rsi <= 72.0:
                score = 75.0 + range_r * 5.0
                candidates_by_mode["RANGE_EXPANSION_BURST"].setdefault(dt, []).append({
                    "symbol": sym, "close": c_val, "atr": atr, "score": score
                })

            # 8. MULTI_FACTOR_APEX
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

    # Trading days in this regime
    all_dates = [d for d in nifty_map.keys() if start_date <= d <= end_date]
    if not all_dates:
        return {}

    nifty_start = nifty_map[all_dates[0]]["close"]
    nifty_end = nifty_map[all_dates[-1]]["close"]
    benchmark_pct = (nifty_end - nifty_start) / nifty_start * 100.0

    # Unpack strategy parameters
    entry_mode = strategy["entry_mode"]
    max_slots = strategy["max_slots"]
    pyramid_mode = strategy.get("pyramid_mode", "NONE") # NONE, LIVERMORE_50, AGGRESSIVE_75, TWO_STAGE
    exit_mode = strategy.get("exit_mode", "THREE_TIER_SCALE")
    t1_atr = strategy.get("t1_atr", 1.6)
    t2_atr = strategy.get("t2_atr", 3.2)
    t3_atr = strategy.get("t3_atr", 6.0)
    sl_atr = strategy.get("sl_atr", 1.5)
    time_stop_days = strategy.get("time_stop_days", 6)
    min_gain_for_be = strategy.get("min_gain_for_be", 4.5)
    cash_sweep = strategy.get("cash_sweep", True)
    regime_shield = strategy.get("regime_shield", False)
    min_score = strategy.get("min_score", 60.0)

    cash = initial_capital
    active_positions = {}
    completed_trades = []
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
            entry_p = pos["entry_price"]
            pos["max_high"] = max(pos["max_high"], h_p)
            pos["min_low"] = min(pos["min_low"], l_p)
            pos["holding_days"] += 1
            pos["current_price"] = c_p

            cur_peak_pct = (pos["max_high"] - entry_p) / entry_p * 100.0

            # Beginning-of-bar stop check
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
                # Inactivity Time Stop
                if time_stop_days > 0 and pos["holding_days"] >= time_stop_days and cur_peak_pct < 1.5:
                    closed = True
                    exit_price = c_p
                    exit_reason = "TIME_STOP"

            if not closed:
                # Check Pyramiding
                if pyramid_mode != "NONE" and cur_peak_pct >= 4.0 and not pos["pyramided"] and not pos["t1_hit"]:
                    pyr_ratio = 0.50 if pyramid_mode == "LIVERMORE_50" else (0.75 if pyramid_mode == "AGGRESSIVE_75" else 0.33)
                    extra_cost = pos["cost"] * pyr_ratio
                    if cash >= extra_cost:
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

                # Noise-proof trailing stop ratchets
                if cur_peak_pct >= min_gain_for_be:
                    pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.005, 2))
                if cur_peak_pct >= 8.0:
                    pos["trailing_stop"] = max(pos["trailing_stop"], round(pos["max_high"] * 0.965, 2))
                if cur_peak_pct >= 14.0:
                    pos["trailing_stop"] = max(pos["trailing_stop"], round(pos["max_high"] * 0.940, 2))
                effective_sl = max(pos["stop_loss"], pos["trailing_stop"])

                # Exits depending on mode
                if exit_mode == "THREE_TIER_SCALE":
                    # 1/3 T1, 1/3 T2, 1/3 T3
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
                            pos["trailing_stop"] = max(pos["trailing_stop"], pos["target_1"])

                    if pos["t2_hit"]:
                        if h_p >= pos["target_3"]:
                            closed = True; exit_price = pos["target_3"]; exit_reason = "T3_RUNNER"
                        elif l_p <= effective_sl:
                            closed = True; exit_price = effective_sl; exit_reason = "TRAIL_RUNNER"

                elif exit_mode == "REGIME_ADAPTIVE":
                    if is_bull:
                        if not pos["t1_hit"] and h_p >= pos["target_1"]:
                            pos["t1_hit"] = True
                            half = pos["shares"] // 2
                            if half > 0:
                                cash += half * pos["target_1"]
                                pos["shares"] -= half
                                pos["realized_pnl"] += (pos["target_1"] - entry_p) * half
                                pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.005, 2))
                        if pos["t1_hit"]:
                            if h_p >= pos["target_2"]:
                                closed = True; exit_price = pos["target_2"]; exit_reason = "T2_RUNNER"
                            elif l_p <= effective_sl:
                                closed = True; exit_price = effective_sl; exit_reason = "TRAIL_RUNNER"
                    else:
                        if h_p >= pos["target_1"]:
                            closed = True; exit_price = pos["target_1"]; exit_reason = "T1_HIT"

                elif exit_mode == "CHANDELIER_RUNNER":
                    if h_p >= pos["target_1"] and not pos["t1_hit"]:
                        pos["t1_hit"] = True
                        half = pos["shares"] // 2
                        if half > 0:
                            cash += half * pos["target_1"]
                            pos["shares"] -= half
                            pos["realized_pnl"] += (pos["target_1"] - entry_p) * half
                    # Trail from highest high by 2.5 ATR
                    chan_stop = pos["max_high"] - (bar["atr_14"] * 2.5)
                    pos["trailing_stop"] = max(pos["trailing_stop"], round(chan_stop, 2))
                    if pos["t1_hit"] and l_p <= pos["trailing_stop"]:
                        closed = True; exit_price = pos["trailing_stop"]; exit_reason = "CHANDELIER_EXIT"

                else:  # SYMMETRIC_1.5 or ASYMMETRIC_2.0
                    if h_p >= pos["target_1"]:
                        closed = True; exit_price = pos["target_1"]; exit_reason = "T1_HIT"

            if closed:
                proceeds = pos["shares"] * exit_price
                cash += proceeds
                total_gain = pos["realized_pnl"] + (proceeds - (pos["shares"] * entry_p))
                net_gain_pct = (total_gain / max(1.0, pos["initial_cost"])) * 100.0

                completed_trades.append({
                    "symbol": sym,
                    "gain_val": total_gain,
                    "gain_pct": net_gain_pct,
                    "exit_reason": exit_reason,
                    "holding_days": pos["holding_days"]
                })
                symbols_to_close.append(sym)

        for s in symbols_to_close:
            del active_positions[s]

        # B. Cash Yield Auto-Sweep
        if cash_sweep:
            cash += cash * (6.5 / 100.0 / 365.0)

        # C. Deployable Capital & Slots
        deployable = cash
        if regime_shield and not is_bull:
            deployable = max(0.0, cash - initial_capital * 0.50) # 50% cash reserve in bear

        avail_slots = max_slots - len(active_positions)
        target_per_slot = initial_capital / max_slots

        if avail_slots > 0 and deployable >= (target_per_slot * 0.40):
            cand_pool = candidates_by_mode.get(entry_mode, {}).get(cur_date, [])
            for cand in cand_pool:
                if cand["symbol"] in active_positions:
                    continue
                if cand["score"] < min_score:
                    continue

                c_val = cand["close"]
                atr = cand["atr"]
                t1_val = round(c_val + t1_atr * atr, 2)
                t2_val = round(c_val + t2_atr * atr, 2)
                t3_val = round(c_val + t3_atr * atr, 2)
                sl_val = round(c_val - sl_atr * atr, 2)

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

        # D. Daily Valuation & Drawdown
        open_val = sum(pos["shares"] * pos["current_price"] for pos in active_positions.values())
        tot_eq = cash + open_val
        equity_history.append(tot_eq)

    # Wrap up final portfolio value
    final_eq = equity_history[-1] if equity_history else initial_capital
    peak_eq = pd.Series(equity_history).cummax()
    max_dd = ((pd.Series(equity_history) - peak_eq) / peak_eq * 100.0).min()
    ret_pct = (final_eq - initial_capital) / initial_capital * 100.0
    alpha_pct = ret_pct - benchmark_pct

    # Cash-Flow XIRR
    end_dt = datetime.strptime(all_dates[-1], "%Y-%m-%d").date()
    cf_list = list(cash_flows.items()) + [(end_dt, final_eq)]
    xirr_val = calculate_xirr(cf_list)

    # Trade Statistics
    tot_trades = len(completed_trades)
    wins = [t for t in completed_trades if t["gain_val"] > 0]
    losses = [t for t in completed_trades if t["gain_val"] <= 0]
    win_rate = (len(wins) / tot_trades * 100.0) if tot_trades > 0 else 0.0
    tot_win_val = sum(t["gain_val"] for t in wins)
    tot_loss_val = abs(sum(t["gain_val"] for t in losses))
    profit_factor = round(tot_win_val / max(1.0, tot_loss_val), 2) if tot_loss_val > 0 else 5.0
    avg_win = (sum(t["gain_pct"] for t in wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(t["gain_pct"] for t in losses) / len(losses)) if losses else 0.0
    payoff_ratio = round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else 1.0

    return {
        "return_pct": round(ret_pct, 2),
        "benchmark_pct": round(benchmark_pct, 2),
        "alpha_pct": round(alpha_pct, 2),
        "xirr": round(xirr_val, 1),
        "win_rate": round(win_rate, 1),
        "profit_factor": profit_factor,
        "payoff_ratio": payoff_ratio,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "max_dd": round(abs(max_dd), 1),
        "trades": tot_trades,
        "wins": len(wins),
        "losses": len(losses)
    }


# ─── 4. Generate 100 Distinct Strategy Configurations ─────────────────────────
def build_100_swing_strategies() -> list:
    strategies = []
    strat_idx = 1

    entry_modes = [
        "MULTI_LOOKBACK",
        "CLENOW_SMOOTHNESS",
        "MINERVINI_VCP",
        "OVERSOLD_SPRINGBOARD",
        "SECTOR_LEAD_RS",
        "DONCHIAN_TURTLE",
        "RANGE_EXPANSION_BURST",
        "MULTI_FACTOR_APEX"
    ]
    slot_options = [4, 6, 8, 10]
    pyramid_options = ["NONE", "LIVERMORE_50", "AGGRESSIVE_75"]
    exit_options = [
        ("THREE_TIER_SCALE", 1.6, 3.2, 6.0, 1.5, 6),
        ("REGIME_ADAPTIVE", 1.8, 3.5, 5.0, 1.5, 6),
        ("SYMMETRIC_1.5", 1.5, 3.0, 4.5, 1.5, 6),
        ("ASYMMETRIC_2.0", 2.0, 3.8, 5.5, 1.5, 6),
        ("CHANDELIER_RUNNER", 1.8, 3.5, 6.0, 1.5, 8),
    ]

    for em in entry_modes:
        for slots in slot_options:
            for pyr in pyramid_options:
                for exit_name, t1, t2, t3, sl, t_stop in exit_options:
                    if len(strategies) >= 100:
                        break

                    name = f"SW_{strat_idx:03d}: {em[:14]} | {slots}Slots | {pyr[:10]} | {exit_name[:12]}"
                    strategies.append({
                        "id": f"SW_{strat_idx:03d}",
                        "name": name,
                        "entry_mode": em,
                        "max_slots": slots,
                        "pyramid_mode": pyr,
                        "exit_mode": exit_name,
                        "t1_atr": t1,
                        "t2_atr": t2,
                        "t3_atr": t3,
                        "sl_atr": sl,
                        "time_stop_days": t_stop,
                        "min_gain_for_be": 4.5,
                        "cash_sweep": True,
                        "regime_shield": (slots <= 6 and pyr != "NONE")
                    })
                    strat_idx += 1
                if len(strategies) >= 100:
                    break
            if len(strategies) >= 100:
                break
        if len(strategies) >= 100:
            break

    return strategies


# ─── 5. Main Grid Execution ───────────────────────────────────────────────────
def main():
    print("=" * 125)
    print("🚀 MASSIVE 100-STRATEGY QUANTITATIVE EXPLORATION: DAILY SWING TRADING")
    print("   Evaluating 100 Systematic Paradigms across 5 Diverse Historical Market Regimes")
    print("=" * 125)

    nifty_map, prices_by_symbol = preload_market_data()
    symbol_records, candidates_by_mode = precompute_candidates_and_records(prices_by_symbol, nifty_map)
    strategies = build_100_swing_strategies()
    print(f"📋 Generated {len(strategies)} distinct swing strategy permutations.")

    results_table = []
    t_start = time.time()

    print(f"\n▶️ Launching multi-regime simulation grid (100 strategies × 5 regimes = 500 simulations)...")

    for i, strat in enumerate(strategies):
        regime_metrics = {}
        for reg in REGIMES:
            res = simulate_swing_strategy(strat, reg, nifty_map, symbol_records, candidates_by_mode)
            regime_metrics[reg["id"]] = res

        # Compute Cross-Regime Composite Score
        # Weighting: Worst Bear (30%) + Consolidation (25%) + Bull (20%) + Moderate (10%) + 1-Yr Cycle (15%)
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

        # Composite Fitness Objective:
        # High XIRR in bear + high alpha in bull + PR >= 1.0 + low DD
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
            "composite_score": round(composite_score, 2),
            # Key Regime Metrics
            "worst_bear_ret": regime_metrics["BEAR_WORST"].get("return_pct", 0.0),
            "worst_bear_xirr": worst_xirr,
            "worst_bear_pr": regime_metrics["BEAR_WORST"].get("payoff_ratio", 0.0),
            "chop_ret": regime_metrics["CHOP_CONSOLIDATION"].get("return_pct", 0.0),
            "chop_xirr": chop_xirr,
            "chop_pr": regime_metrics["CHOP_CONSOLIDATION"].get("payoff_ratio", 0.0),
            "bull_ret": bull_ret,
            "cycle_ret": cycle_ret,
            "cycle_alpha": cycle_alpha,
            "cycle_xirr": cycle_xirr,
            "cycle_pr": cycle_pr,
            "cycle_pf": cycle_pf,
            "cycle_dd": cycle_dd,
            "cycle_wr": cycle_wr,
        }
        results_table.append(row)

        if (i + 1) % 20 == 0 or (i + 1) == len(strategies):
            print(f"   • Completed {i + 1}/{len(strategies)} strategies (Elapsed: {time.time() - t_start:.1f}s)...")

    # Sort results by Composite Score
    results_df = pd.DataFrame(results_table).sort_values("composite_score", ascending=False).reset_index(drop=True)

    # Save complete results
    out_csv = BASE_DIR / "scripts" / "swing_100_strategies_results.csv"
    results_df.to_csv(out_csv, index=False)
    print(f"\n💾 Full 100-Strategy Results saved to: {out_csv}")

    # Display Top 10 Champion Leaderboard
    print("\n" + "=" * 145)
    print("🏆 TOP 10 CHAMPION DAILY SWING STRATEGIES (RANKED BY CROSS-REGIME COMPOSITE SCORE)")
    print("=" * 145)
    headers = f"{'Rank':<4} | {'Strategy Name':<45} | {'Score':<6} | {'Worst XIRR':<10} | {'Chop XIRR':<9} | {'Bull Ret':<8} | {'1Yr Alpha':<9} | {'1Yr XIRR':<8} | {'PR':<5} | {'PF':<5} | {'DD':<5}"
    print(headers)
    print("-" * 145)

    for rank, row in enumerate(results_df.head(10).to_dict(orient="records"), start=1):
        print(
            f"{rank:<4} | {row['name']:<45} | {row['composite_score']:+6.1f} | "
            f"{row['worst_bear_xirr']:+9.1f}% | {row['chop_xirr']:+8.1f}% | "
            f"{row['bull_ret']:+7.1f}% | {row['cycle_alpha']:+8.1f}% | "
            f"{row['cycle_xirr']:+7.1f}% | {row['cycle_pr']:4.2f}x | {row['cycle_pf']:4.2f} | {row['cycle_dd']:4.1f}%"
        )
    print("=" * 145)


if __name__ == "__main__":
    main()
