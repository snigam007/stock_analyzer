#!/usr/bin/env python3
"""
scripts/backtest_broad_spectrum_strategies.py

Extensive Quantitative Backtest across a Broad Spectrum of Strategies:
Testing 10 diverse strategic paradigms across both:
1. The 60-Day Stress Consolidation Period (July 1, 2026 to Sept 22, 2026, NIFTY = -2.82%)
2. The 1-Year Multi-Regime Cycle (Oct 1, 2025 to Sept 22, 2026)

Objective: Identify strategies that achieve:
- > 20% Annualized XIRR even in the worst/consolidating market
- Compound and multiply investments in normal/trending regimes
- High Payoff Ratio (PR > 1.0x) and strong Risk:Reward (R:R)
"""

import sys
from pathlib import Path

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import numpy as np
import pandas as pd
from datetime import datetime
from sqlalchemy import text
from db.database import get_global_engine, get_session
from core.sip_audit_backtester import calculate_xirr


def run_spectrum_simulation(
    strategy_id: str,
    strategy_name: str,
    start_date: str = "2026-07-01",
    end_date: str = "2026-09-22",
    initial_capital: float = 1000000.0,
    max_slots: int = 10,
    # Strategy Tuning Parameters
    entry_mode: str = "TREND_MOMENTUM", # "TREND_MOMENTUM", "OVERSOLD_DIP", "VCP_SQUEEZE", "MULTI_LOOKBACK", "SECTOR_LEAD"
    exit_mode: str = "SYMMETRIC_T1",    # "SYMMETRIC_T1", "REGIME_ADAPTIVE", "THREE_TIER_SCALE", "CHANDELIER_RUNNER", "VELOCITY_BURST"
    t1_atr: float = 1.5,
    sl_atr: float = 1.5,
    t2_atr: float = 3.0,
    t3_atr: float = 5.0,
    time_stop_days: int = 0,            # 0 = disabled, >0 = exit if gain < 1.5% in N days
    min_gain_for_breakeven: float = 4.5,
    pyramid_on_win: bool = False,
    defensive_cash_sweep: bool = True,
    bear_cash_reserve_pct: float = 0.0, # e.g. 50% cash when NIFTY < 50 EMA
    min_score: float = 60.0,
    min_mom_6m: float = 25.0
):
    engine = get_global_engine()
    session = get_session(engine)

    # 1. Trading Dates
    td_rows = session.execute(text("""
        SELECT DISTINCT date FROM daily_prices
        WHERE date >= :s AND date <= :e
        ORDER BY date ASC
    """), {"s": start_date, "e": end_date}).fetchall()
    trading_dates = [r[0] for r in td_rows]

    # 2. Benchmark NIFTY 50
    nifty_df = pd.read_sql(text("""
        SELECT date, close
        FROM index_prices
        WHERE symbol IN ('^NSEI', 'NIFTY 50') AND date >= '2024-01-01' AND date <= :e
        ORDER BY date ASC
    """), session.bind, params={"e": end_date})
    nifty_df["date_str"] = nifty_df["date"].astype(str)
    nifty_df = nifty_df.drop_duplicates(subset=["date_str"]).sort_values("date_str").reset_index(drop=True)
    nifty_df["ema_21"] = nifty_df["close"].ewm(span=21, adjust=False).mean()
    nifty_df["ema_50"] = nifty_df["close"].ewm(span=50, adjust=False).mean()
    nifty_df["mom_20d"] = (nifty_df["close"] - nifty_df["close"].shift(20)) / nifty_df["close"].shift(20) * 100.0
    nifty_df["mom_60d"] = (nifty_df["close"] - nifty_df["close"].shift(60)) / nifty_df["close"].shift(60) * 100.0
    nifty_map = nifty_df.set_index("date_str").to_dict(orient="index")

    nifty_start = nifty_map.get(trading_dates[0], {}).get("close", 24710.25)
    nifty_end = nifty_map.get(trading_dates[-1], {}).get("close", 24013.80)
    nifty_return_pct = (nifty_end - nifty_start) / nifty_start * 100.0

    # 3. Load Price Matrix
    df_prices = pd.read_sql(text("""
        SELECT dp.symbol, dp.date, dp.open, dp.high, dp.low, dp.close, dp.volume, stk.sector
        FROM daily_prices dp
        LEFT JOIN stocks stk ON dp.symbol = stk.symbol
        WHERE dp.date >= '2024-01-01' AND dp.date <= :e
        ORDER BY dp.symbol, dp.date ASC
    """), session.bind, params={"e": end_date})

    prices_by_symbol = {}
    for sym, group in df_prices.groupby("symbol"):
        group = group.sort_values("date").reset_index(drop=True)
        group["ema_21"] = group["close"].ewm(span=21, adjust=False).mean()
        group["ema_50"] = group["close"].ewm(span=50, adjust=False).mean()
        group["ema_200"] = group["close"].ewm(span=200, adjust=False).mean()
        
        # RSI 14
        delta = group["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(14, min_periods=14).mean()
        avg_loss = loss.rolling(14, min_periods=14).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        group["rsi_14"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)

        # ATR 14
        hl = group["high"] - group["low"]
        hc = (group["high"] - group["close"].shift(1)).abs()
        lc = (group["low"] - group["close"].shift(1)).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        group["atr_14"] = tr.rolling(14, min_periods=14).mean().fillna(group["close"] * 0.025)

        # Bollinger Band Width (VCP Squeeze)
        sma_20 = group["close"].rolling(20, min_periods=20).mean()
        std_20 = group["close"].rolling(20, min_periods=20).std()
        group["bbw"] = ((std_20 * 4.0) / sma_20 * 100.0).fillna(10.0)
        group["bbw_pctile"] = group["bbw"].rolling(120, min_periods=30).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1] * 100.0 if len(x) > 0 else 50.0
        ).fillna(50.0)

        # Proximity to 52W High
        group["high_52w"] = group["high"].rolling(250, min_periods=30).max()
        group["prox_52w"] = (group["close"] / group["high_52w"] * 100.0).fillna(85.0)

        # Lookback Momentums
        group["mom_1m"] = ((group["close"] - group["close"].shift(20)) / group["close"].shift(20) * 100.0).fillna(0.0)
        group["mom_3m"] = ((group["close"] - group["close"].shift(60)) / group["close"].shift(60) * 100.0).fillna(0.0)
        group["mom_6m"] = ((group["close"] - group["close"].shift(126)) / group["close"].shift(126) * 100.0).fillna(0.0)
        group["mom_12m"] = ((group["close"] - group["close"].shift(250)) / group["close"].shift(250) * 100.0).fillna(0.0)

        # Volume Multiplier
        vol_sma20 = group["volume"].rolling(20, min_periods=20).mean().replace(0, 1.0)
        group["vol_mult"] = (group["volume"] / vol_sma20).fillna(1.0)

        prices_by_symbol[sym] = group.set_index("date")

    session.close()

    # 4. Simulation Execution
    cash = initial_capital
    active_positions = {}
    completed_trades = []
    daily_equity_history = []
    daily_cash_flows = {datetime.strptime(start_date, "%Y-%m-%d").date(): -initial_capital}

    for cur_date in trading_dates:
        cur_nifty = nifty_map.get(cur_date, {})
        nifty_c = cur_nifty.get("close", 24000.0)
        nifty_e50 = cur_nifty.get("ema_50", 24000.0)
        nifty_e21 = cur_nifty.get("ema_21", 24000.0)
        is_bull_regime = (nifty_c >= nifty_e50 and nifty_c >= nifty_e21)

        # -------------------------------------------------------------
        # Step A: Manage Existing Open Positions
        # -------------------------------------------------------------
        symbols_to_close = []
        for sym, pos in active_positions.items():
            sym_df = prices_by_symbol.get(sym)
            if sym_df is None or cur_date not in sym_df.index:
                continue

            bar = sym_df.loc[cur_date]
            h_p, l_p, c_p = float(bar["high"]), float(bar["low"]), float(bar["close"])
            entry_p = pos["entry_price"]
            pos["max_high"] = max(pos["max_high"], h_p)
            pos["min_low"] = min(pos["min_low"], l_p)
            pos["current_price"] = c_p
            pos["holding_days"] += 1

            cur_peak_pct = (pos["max_high"] - entry_p) / entry_p * 100.0

            # Noise-Proof Trailing Ratchets
            if cur_peak_pct >= min_gain_for_breakeven:
                pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.005, 2))
            if cur_peak_pct >= 8.0:
                pos["trailing_stop"] = max(pos["trailing_stop"], round(pos["max_high"] * 0.965, 2))
            if cur_peak_pct >= 14.0:
                pos["trailing_stop"] = max(pos["trailing_stop"], round(pos["max_high"] * 0.940, 2))

            effective_sl = max(pos["stop_loss"], pos["trailing_stop"])

            # Check Pyramiding Opportunity
            if pyramid_on_win and cur_peak_pct >= 4.0 and not pos.get("pyramided", False):
                # Add 50% extra size from available cash
                extra_alloc = pos["cost"] * 0.5
                if cash >= extra_alloc:
                    extra_shares = int(extra_alloc / c_p)
                    if extra_shares > 0:
                        pos["shares"] += extra_shares
                        pos["cost"] += extra_shares * c_p
                        cash -= extra_shares * c_p
                        pos["pyramided"] = True
                        pos["entry_price"] = pos["cost"] / pos["shares"]
                        pos["trailing_stop"] = max(pos["trailing_stop"], round(pos["entry_price"] * 1.002, 2))
                        effective_sl = max(pos["stop_loss"], pos["trailing_stop"])

            closed = False
            exit_price = 0.0
            exit_reason = ""

            # Time-Based Inactivity Exit
            if time_stop_days > 0 and pos["holding_days"] >= time_stop_days and cur_peak_pct < 1.5:
                closed = True
                exit_price = c_p
                exit_reason = "TIME_STOP"

            if not closed:
                if exit_mode == "REGIME_ADAPTIVE":
                    if is_bull_regime:
                        # In Bull: 50% at T1, 50% at T2/Trail
                        if not pos["t1_hit"] and h_p >= pos["target_1"]:
                            pos["t1_hit"] = True
                            half_s = pos["shares"] // 2
                            if half_s > 0:
                                proceeds = half_s * pos["target_1"]
                                cash += proceeds
                                pos["shares"] -= half_s
                                pos["realized_pnl"] += (pos["target_1"] - entry_p) * half_s
                                pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.005, 2))
                                effective_sl = max(pos["stop_loss"], pos["trailing_stop"])

                        if pos["t1_hit"]:
                            if h_p >= pos["target_2"]:
                                closed = True; exit_price = pos["target_2"]; exit_reason = "T2_RUNNER"
                            elif l_p <= effective_sl:
                                closed = True; exit_price = effective_sl; exit_reason = "TRAIL_RUNNER"
                        else:
                            if l_p <= effective_sl:
                                closed = True; exit_price = effective_sl; exit_reason = "SL_HIT"
                    else:
                        # In Bear/Sideways: 100% Milestone Exit at Target 1
                        if h_p >= pos["target_1"]:
                            closed = True; exit_price = pos["target_1"]; exit_reason = "T1_HIT"
                        elif l_p <= effective_sl:
                            closed = True; exit_price = effective_sl
                            exit_reason = "TRAILING_SL_HIT" if effective_sl >= entry_p else "SL_HIT"

                elif exit_mode == "THREE_TIER_SCALE":
                    # 1/3 at T1 (+5%), 1/3 at T2 (+10%), 1/3 at T3 (+18% / Runner)
                    if not pos.get("t1_hit", False) and h_p >= pos["target_1"]:
                        pos["t1_hit"] = True
                        s_third = pos["initial_shares"] // 3
                        if s_third > 0 and pos["shares"] > s_third:
                            cash += s_third * pos["target_1"]
                            pos["shares"] -= s_third
                            pos["realized_pnl"] += (pos["target_1"] - entry_p) * s_third
                            pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.005, 2))
                            effective_sl = max(pos["stop_loss"], pos["trailing_stop"])

                    if pos.get("t1_hit", False) and not pos.get("t2_hit", False) and h_p >= pos["target_2"]:
                        pos["t2_hit"] = True
                        s_third = pos["initial_shares"] // 3
                        if s_third > 0 and pos["shares"] > s_third:
                            cash += s_third * pos["target_2"]
                            pos["shares"] -= s_third
                            pos["realized_pnl"] += (pos["target_2"] - entry_p) * s_third
                            pos["trailing_stop"] = max(pos["trailing_stop"], pos["target_1"])
                            effective_sl = max(pos["stop_loss"], pos["trailing_stop"])

                    if pos.get("t2_hit", False):
                        if h_p >= pos["target_3"]:
                            closed = True; exit_price = pos["target_3"]; exit_reason = "T3_SUPER_RUNNER"
                        elif l_p <= effective_sl:
                            closed = True; exit_price = effective_sl; exit_reason = "TRAIL_RUNNER"
                    else:
                        if l_p <= effective_sl:
                            closed = True; exit_price = effective_sl
                            exit_reason = "TRAIL_RUNNER" if pos.get("t1_hit", False) else "SL_HIT"

                elif exit_mode == "VELOCITY_BURST":
                    # Fast target exit at T1, but if held > 4 days and gain < 2.0% -> exit immediately
                    if h_p >= pos["target_1"]:
                        closed = True; exit_price = pos["target_1"]; exit_reason = "T1_BURST"
                    elif pos["holding_days"] >= 4 and cur_peak_pct < 2.0:
                        closed = True; exit_price = c_p; exit_reason = "VELOCITY_CUT"
                    elif l_p <= effective_sl:
                        closed = True; exit_price = effective_sl; exit_reason = "SL_HIT"

                else:  # SYMMETRIC_T1
                    if h_p >= pos["target_1"]:
                        closed = True; exit_price = pos["target_1"]; exit_reason = "T1_HIT"
                    elif l_p <= effective_sl:
                        closed = True; exit_price = effective_sl
                        exit_reason = "TRAILING_SL_HIT" if effective_sl >= entry_p else "SL_HIT"

            if closed:
                proceeds = pos["shares"] * exit_price
                cash += proceeds
                total_gain = pos["realized_pnl"] + (proceeds - (pos["shares"] * entry_p))
                net_gain_pct = total_gain / pos["initial_cost"] * 100.0

                completed_trades.append({
                    "symbol": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": cur_date,
                    "entry_price": entry_p,
                    "exit_price": exit_price,
                    "gain_val": total_gain,
                    "gain_pct": net_gain_pct,
                    "exit_reason": exit_reason,
                    "holding_days": pos["holding_days"],
                    "max_high": pos["max_high"]
                })
                symbols_to_close.append(sym)

        for s in symbols_to_close:
            del active_positions[s]

        # -------------------------------------------------------------
        # Step B: Liquid Yield Auto-Sweep
        # -------------------------------------------------------------
        if defensive_cash_sweep:
            cash += cash * (6.5 / 100.0 / 365.0)

        # -------------------------------------------------------------
        # Step C: Point-in-Time Daily Signal Discovery
        # -------------------------------------------------------------
        # Calculate Deployable Capital (Defensive Reserve if in Bear Regime)
        deployable_cash = cash
        if not is_bull_regime and bear_cash_reserve_pct > 0:
            target_reserve = initial_capital * (bear_cash_reserve_pct / 100.0)
            deployable_cash = max(0.0, cash - target_reserve)

        avail_slots = max_slots - len(active_positions)
        target_per_slot = initial_capital / max_slots

        if avail_slots > 0 and deployable_cash >= (target_per_slot * 0.4):
            candidates = []
            nifty_20d = cur_nifty.get("mom_20d", 0.0)

            for sym, sym_df in prices_by_symbol.items():
                if sym in active_positions or cur_date not in sym_df.index:
                    continue

                row = sym_df.loc[cur_date]
                c_val = float(row["close"])
                if c_val < 20.0:
                    continue

                e50 = float(row["ema_50"])
                e200 = float(row["ema_200"])
                rsi = float(row["rsi_14"])
                atr = float(row["atr_14"])
                prox = float(row["prox_52w"])
                mom6 = float(row["mom_6m"])
                mom3 = float(row["mom_3m"])
                mom1 = float(row["mom_1m"])
                mom12 = float(row["mom_12m"])
                bbw_p = float(row["bbw_pctile"])
                vol_m = float(row["vol_mult"])

                qualifies = False
                cand_score = 60.0

                if entry_mode == "OVERSOLD_DIP":
                    # Mean-Reverting Dip Hunter: Secular bull (c >= e200) but short-term oversold dip (RSI 32-48 near 50-EMA)
                    if c_val >= e200 and abs(c_val - e50) / e50 <= 0.03 and 30.0 <= rsi <= 48.0:
                        qualifies = True
                        cand_score = 80.0 + (50.0 - rsi)

                elif entry_mode == "VCP_SQUEEZE":
                    # Minervini Volatility Contraction Pattern + Volume Expansion
                    if c_val >= e50 >= e200 and prox >= 85.0 and bbw_p <= 25.0 and vol_m >= 1.25 and 50.0 <= rsi <= 68.0:
                        qualifies = True
                        cand_score = 85.0 + (100.0 - bbw_p) * 0.1

                elif entry_mode == "MULTI_LOOKBACK":
                    # Multi-Lookback Composite Z-Blend: Strong across 1M, 3M, 6M, and 12M simultaneously!
                    if c_val >= e50 >= e200 and mom1 > 0 and mom3 > 10 and mom6 > 25 and mom12 > 35:
                        qualifies = True
                        cand_score = 70.0 + (mom1 * 0.2 + mom3 * 0.3 + mom6 * 0.3 + mom12 * 0.2)

                elif entry_mode == "SECTOR_LEAD":
                    # Relative Strength Outperformance vs NIFTY
                    rs_outperform = mom1 - nifty_20d
                    if c_val >= e50 >= e200 and mom6 >= 30.0 and rs_outperform >= 6.0 and 48.0 <= rsi <= 68.0:
                        qualifies = True
                        cand_score = 75.0 + rs_outperform

                else:  # TREND_MOMENTUM (Default Apex Multi-Pillar)
                    if c_val >= e50 and e50 >= e200 * 0.98 and mom6 >= min_mom_6m and prox >= 80.0 and 42.0 <= rsi <= 70.0:
                        qualifies = True
                        cand_score = 60.0
                        if c_val >= e50 >= e200: cand_score += 10.0
                        if prox >= 90.0: cand_score += 10.0
                        if mom6 >= 40.0: cand_score += 10.0

                if qualifies and cand_score >= min_score:
                    t1 = round(c_val + t1_atr * atr, 2)
                    t2 = round(c_val + t2_atr * atr, 2)
                    t3 = round(c_val + t3_atr * atr, 2)
                    sl = round(c_val - sl_atr * atr, 2)

                    candidates.append({
                        "symbol": sym,
                        "close": c_val,
                        "score": cand_score,
                        "t1": t1,
                        "t2": t2,
                        "t3": t3,
                        "sl": sl,
                        "mom6": mom6
                    })

            candidates.sort(key=lambda x: (x["score"], x["mom6"]), reverse=True)

            for cand in candidates[:avail_slots]:
                alloc = min(deployable_cash * 0.95, target_per_slot)
                if alloc < 20000.0:
                    break

                shares = int(alloc / cand["close"])
                if shares <= 2:
                    continue

                cost = shares * cand["close"]
                cash -= cost
                deployable_cash -= cost

                active_positions[cand["symbol"]] = {
                    "entry_date": cur_date,
                    "entry_price": cand["close"],
                    "shares": shares,
                    "initial_shares": shares,
                    "cost": cost,
                    "initial_cost": cost,
                    "stop_loss": cand["sl"],
                    "trailing_stop": cand["sl"],
                    "target_1": cand["t1"],
                    "target_2": cand["t2"],
                    "target_3": cand["t3"],
                    "t1_hit": False,
                    "t2_hit": False,
                    "max_high": cand["close"],
                    "min_low": cand["close"],
                    "current_price": cand["close"],
                    "holding_days": 0,
                    "realized_pnl": 0.0,
                    "pyramided": False
                }

        # -------------------------------------------------------------
        # Step D: Mark to Market Daily Valuation
        # -------------------------------------------------------------
        port_val = sum(pos["shares"] * pos["current_price"] for pos in active_positions.values())
        tot_eq = cash + port_val
        st_ret = (tot_eq - initial_capital) / initial_capital * 100.0
        cur_nifty_c = cur_nifty.get("close", nifty_start)
        nifty_ret = (cur_nifty_c - nifty_start) / nifty_start * 100.0

        daily_equity_history.append({
            "date": cur_date,
            "cash": cash,
            "port_val": port_val,
            "total_equity": tot_eq,
            "strategy_return_pct": st_ret,
            "benchmark_return_pct": nifty_ret,
            "alpha_pct": st_ret - nifty_ret,
            "open_positions": len(active_positions)
        })

    # 5. Summary Analytics
    final_equity = daily_equity_history[-1]["total_equity"]
    terminal_flows = [(d, amt) for d, amt in daily_cash_flows.items()]
    terminal_flows.append((datetime.strptime(end_date, "%Y-%m-%d").date(), final_equity))
    annualized_xirr = calculate_xirr(terminal_flows)

    total_trades = len(completed_trades)
    winning_trades = [t for t in completed_trades if t["gain_val"] > 0]
    losing_trades = [t for t in completed_trades if t["gain_val"] <= 0]

    gross_profit = sum(t["gain_val"] for t in winning_trades)
    gross_loss = abs(sum(t["gain_val"] for t in losing_trades))
    profit_factor = round(gross_profit / max(0.01, gross_loss), 2) if gross_profit > 0 else 0.0

    win_rate = (len(winning_trades) / max(1, total_trades)) * 100.0
    avg_win_pct = np.mean([t["gain_pct"] for t in winning_trades]) if winning_trades else 0.0
    avg_loss_pct = np.mean([t["gain_pct"] for t in losing_trades]) if losing_trades else 0.0
    payoff_ratio = round(abs(avg_win_pct / max(0.01, abs(avg_loss_pct))), 2)

    eq_series = pd.Series([d["total_equity"] for d in daily_equity_history])
    peak_series = eq_series.cummax()
    dd_series = (eq_series - peak_series) / peak_series * 100.0
    max_dd = abs(dd_series.min())

    exit_counts = {}
    for t in completed_trades:
        r = t["exit_reason"]
        exit_counts[r] = exit_counts.get(r, 0) + 1

    return {
        "id": strategy_id,
        "name": strategy_name,
        "return_pct": round(daily_equity_history[-1]["strategy_return_pct"], 2),
        "benchmark_pct": round(nifty_return_pct, 2),
        "alpha_pct": round(daily_equity_history[-1]["strategy_return_pct"] - nifty_return_pct, 2),
        "xirr": annualized_xirr,
        "trades": total_trades,
        "wins": len(winning_trades),
        "losses": len(losing_trades),
        "in_play": len(active_positions),
        "win_rate": round(win_rate, 1),
        "profit_factor": profit_factor,
        "payoff_ratio": payoff_ratio,
        "avg_win": round(avg_win_pct, 2),
        "avg_loss": round(avg_loss_pct, 2),
        "max_dd": round(max_dd, 1),
        "exits": exit_counts
    }


if __name__ == "__main__":
    print("=" * 135)
    print("🔬 COMPREHENSIVE BROAD-SPECTRUM STRATEGY EXPLORATION")
    print("   Goal: Identify strategies achieving > 20% XIRR in worst markets and hyper-multiplying in bull trends.")
    print("=" * 135)

    spectrum = [
        ("S1_DIP_HUNTER", "1. Institutional Dip Hunter (Oversold 50-EMA Pullbacks)", {
            "entry_mode": "OVERSOLD_DIP",
            "exit_mode": "SYMMETRIC_T1",
            "t1_atr": 1.6,
            "sl_atr": 1.4,
            "time_stop_days": 6
        }),
        ("S2_CONCENTRATED_ALPHA", "2. Concentrated 5-Slot Clenow Hyper-Momentum", {
            "max_slots": 5,
            "entry_mode": "TREND_MOMENTUM",
            "exit_mode": "REGIME_ADAPTIVE",
            "t1_atr": 1.8,
            "sl_atr": 1.5,
            "min_mom_6m": 35.0,
            "time_stop_days": 6
        }),
        ("S3_VCP_BREAKOUT", "3. Minervini VCP Squeeze Breakout with Volume Surge", {
            "entry_mode": "VCP_SQUEEZE",
            "exit_mode": "SYMMETRIC_T1",
            "t1_atr": 2.0,
            "sl_atr": 1.5,
            "time_stop_days": 5
        }),
        ("S4_THREE_TIER_SCALE", "4. Asymmetric 3-Tier Ladder (1/3 T1, 1/3 T2, 1/3 Runner)", {
            "entry_mode": "TREND_MOMENTUM",
            "exit_mode": "THREE_TIER_SCALE",
            "t1_atr": 1.5,
            "t2_atr": 3.0,
            "t3_atr": 5.5,
            "sl_atr": 1.5,
            "time_stop_days": 6
        }),
        ("S5_MULTI_LOOKBACK", "5. Multi-Lookback Z-Blend Momentum (1M+3M+6M+12M)", {
            "entry_mode": "MULTI_LOOKBACK",
            "exit_mode": "REGIME_ADAPTIVE",
            "t1_atr": 1.8,
            "sl_atr": 1.5,
            "time_stop_days": 6
        }),
        ("S6_BEAR_SHIELD_BULL_AGGRESSOR", "6. Dual-Speed Regime Shield (50% LiquidBees in Bear, 100% Bull)", {
            "entry_mode": "TREND_MOMENTUM",
            "exit_mode": "REGIME_ADAPTIVE",
            "bear_cash_reserve_pct": 50.0,
            "t1_atr": 1.6,
            "sl_atr": 1.4,
            "time_stop_days": 5
        }),
        ("S7_VELOCITY_BURST", "7. Fast-Velocity Momentum Burst (4-Day Time Cut)", {
            "entry_mode": "SECTOR_LEAD",
            "exit_mode": "VELOCITY_BURST",
            "t1_atr": 1.5,
            "sl_atr": 1.3,
            "time_stop_days": 4
        }),
        ("S8_PYRAMID_COMPOUNDER", "8. Jesse Livermore Winner Pyramiding (+50% size at +4% gain)", {
            "entry_mode": "TREND_MOMENTUM",
            "exit_mode": "REGIME_ADAPTIVE",
            "pyramid_on_win": True,
            "t1_atr": 1.8,
            "sl_atr": 1.5,
            "time_stop_days": 6
        }),
        ("S9_APEX_SYNTHESIS_PRIME", "9. Apex Prime Synthesis (VCP + Regime Adaptive + Velocity Guardrail)", {
            "max_slots": 7,
            "entry_mode": "VCP_SQUEEZE",
            "exit_mode": "REGIME_ADAPTIVE",
            "t1_atr": 1.8,
            "sl_atr": 1.4,
            "time_stop_days": 5,
            "min_gain_for_breakeven": 4.5
        }),
        ("S10_SUPER_ALPHA_HYBRID", "10. Super-Alpha Hybrid (Dip Hunter + Multi-Lookback + 3-Tier Runner)", {
            "max_slots": 6,
            "entry_mode": "MULTI_LOOKBACK",
            "exit_mode": "THREE_TIER_SCALE",
            "t1_atr": 1.6,
            "t2_atr": 3.2,
            "t3_atr": 6.0,
            "sl_atr": 1.5,
            "time_stop_days": 6
        })
    ]

    print("\n--- PHASE 1: STRESS TEST IN WORST CONSOLIDATING MARKET (JULY 1 - SEPT 22, 2026, NIFTY = -2.82%) ---")
    stress_results = []
    for sid, sname, params in spectrum:
        print(f"▶️ Testing: {sname}...")
        res = run_spectrum_simulation(sid, sname, start_date="2026-07-01", end_date="2026-09-22", **params)
        stress_results.append(res)

    print("\n" + "=" * 135)
    print(f"{'Strategy Name':<60} | {'Return':<7} | {'Alpha':<7} | {'XIRR':<7} | {'Win %':<5} | {'PF':<5} | {'PR':<5} | {'Max DD':<6}")
    print("-" * 135)
    for r in stress_results:
        print(f"{r['name']:<60} | {r['return_pct']:+5.2f}% | {r['alpha_pct']:+5.2f}% | {r['xirr']:+5.1f}% | {r['win_rate']:4.1f}% | {r['profit_factor']:4.2f} | {r['payoff_ratio']:4.2f}x | {r['max_dd']:5.1f}%")
    print("=" * 135)
    print(f"Benchmark NIFTY 50 Return over same 60 sessions: {stress_results[0]['benchmark_pct']:+.2f}%\n")
