#!/usr/bin/env python3
"""
scripts/backtest_tactical_swing_optimizations.py

Comprehensive Backtester comparing tactical swing trading enhancements:
1. Rule 1: Noise Filter - Do not move stops to breakeven on minor intraday noise (< 4.5%).
2. Rule 2: Symmetrical ATR Risk-Reward - Initial SL = 1.5 * ATR (no hard -5% floor).
3. Rule 3: Scaling Exits - 50% at Target 1 (+1.5 ATR), move remaining 50% stop to breakeven for T2/T3 runners.
4. Combined Syntheses: Testing individual rules and combined institutional setups.

Evaluated across the exact 60 trading days (July 1, 2026 to Sept 22, 2026) across 367 stocks.
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


def run_tactical_backtest(
    start_date="2026-07-01",
    end_date="2026-09-22",
    initial_capital=1000000.0,
    max_active_positions=10,
    min_momentum_6m_pct=30.0,
    min_composite_score=60.0,
    liquid_yield_pct=6.5,
    # Tactical Rules Configuration:
    breakeven_min_gain_pct=2.5,   # Rule 1: Minimum gain to trigger breakeven ratchet (default was 2.5%, optimized is 4.5% or None)
    use_symmetrical_atr=False,   # Rule 2: If True, SL is strictly 1.5*ATR (no -5% hard floor)
    target_1_atr_mult=1.5,       # ATR multiplier for Target 1
    sl_atr_mult=1.5,             # ATR multiplier for Stop Loss
    scaling_exit_mode="NONE",    # Rule 3: "NONE" (100% exit at T1 or SL), "SCALE_50_50" (50% at T1, 50% at T2/Trail)
    target_2_atr_mult=3.0,       # ATR multiplier for Target 2
    target_3_atr_mult=5.5        # ATR multiplier for Target 3
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
    nifty_rows = session.execute(text("""
        SELECT date, close FROM index_prices
        WHERE symbol = 'NIFTY 50' AND date >= :s AND date <= :e
        ORDER BY date ASC
    """), {"s": start_date, "e": end_date}).fetchall()
    nifty_map = {r[0]: float(r[1]) for r in nifty_rows}
    nifty_start = nifty_map.get(trading_dates[0], 24710.25)
    nifty_end = nifty_map.get(trading_dates[-1], 24013.80)
    nifty_return_pct = (nifty_end - nifty_start) / nifty_start * 100.0

    # 3. Load Stocks Historical Matrix
    df_prices = pd.read_sql(text("""
        SELECT symbol, date, open, high, low, close, volume
        FROM daily_prices
        WHERE date >= '2024-01-01' AND date <= :e
        ORDER BY symbol, date ASC
    """), session.bind, params={"e": end_date})

    prices_by_symbol = {}
    for sym, group in df_prices.groupby("symbol"):
        group = group.sort_values("date").reset_index(drop=True)
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

        # Proximity to 52W High
        group["high_52w"] = group["high"].rolling(250, min_periods=30).max()
        group["prox_52w"] = (group["close"] / group["high_52w"] * 100.0).fillna(85.0)

        # 6M Momentum
        group["mom_6m"] = ((group["close"] - group["close"].shift(126)) / group["close"].shift(126) * 100.0).fillna(0.0)

        prices_by_symbol[sym] = group.set_index("date")

    session.close()

    # 4. Simulation State
    cash = initial_capital
    active_positions = {}  # sym -> dict
    completed_trades = []
    daily_equity_history = []
    daily_cash_flows = {datetime.strptime(start_date, "%Y-%m-%d").date(): -initial_capital}

    total_signals_generated = 0

    for day_idx, cur_date in enumerate(trading_dates):
        cur_dt = datetime.strptime(cur_date, "%Y-%m-%d").date()

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

            # --- Rule 1: Breakeven Ratchet on Noise ---
            # If breakeven_min_gain_pct is specified (e.g. 2.5% vs 4.5%), ratchet to entry * 1.005
            if breakeven_min_gain_pct is not None and cur_peak_pct >= breakeven_min_gain_pct:
                pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.005, 2))

            # Advanced stepladder ratchets if peak reaches higher thresholds
            if cur_peak_pct >= 15.0:
                pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.10, 2))
            elif cur_peak_pct >= 8.0:
                pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.05, 2), round(pos["max_high"] * 0.965, 2))

            effective_sl = max(pos["stop_loss"], pos["trailing_stop"])

            # ---------------------------------------------------------
            # Check Exits based on scaling_exit_mode
            # ---------------------------------------------------------
            if scaling_exit_mode == "SCALE_50_50":
                # --- Rule 3: Scaling Exits (50% at T1, 50% Runner to T2/Trailing Stop) ---
                
                # Check Tranche 1 (50% at T1)
                if not pos["t1_hit"] and h_p >= pos["target_1"]:
                    pos["t1_hit"] = True
                    tranche_shares = pos["initial_shares"] // 2
                    if tranche_shares > 0:
                        proceeds = tranche_shares * pos["target_1"]
                        cost = tranche_shares * entry_p
                        gain_val = proceeds - cost
                        gain_pct = (pos["target_1"] - entry_p) / entry_p * 100.0
                        cash += proceeds
                        pos["remaining_shares"] -= tranche_shares
                        pos["realized_pnl"] += gain_val
                        pos["exit_tranches"].append({
                            "tranche": "T1_HALF",
                            "shares": tranche_shares,
                            "exit_price": pos["target_1"],
                            "gain_pct": gain_pct,
                            "date": cur_date
                        })
                        # Move stop on remaining 50% to Breakeven (+0.5%)
                        pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.005, 2))
                        effective_sl = max(pos["stop_loss"], pos["trailing_stop"])

                # Check Tranche 2 (Remaining 50% at T2 or Trailing Stop)
                if pos["t1_hit"]:
                    # We are holding the runner half
                    if h_p >= pos["target_2"]:
                        # Runner hits Target 2!
                        tranche_shares = pos["remaining_shares"]
                        proceeds = tranche_shares * pos["target_2"]
                        cost = tranche_shares * entry_p
                        gain_val = proceeds - cost
                        gain_pct = (pos["target_2"] - entry_p) / entry_p * 100.0
                        cash += proceeds
                        pos["realized_pnl"] += gain_val
                        pos["exit_tranches"].append({
                            "tranche": "T2_RUNNER",
                            "shares": tranche_shares,
                            "exit_price": pos["target_2"],
                            "gain_pct": gain_pct,
                            "date": cur_date
                        })
                        pos["remaining_shares"] = 0
                        symbols_to_close.append(sym)
                    elif l_p <= effective_sl:
                        # Runner stopped out at trailing stop (breakeven or higher)
                        tranche_shares = pos["remaining_shares"]
                        exit_price = effective_sl
                        proceeds = tranche_shares * exit_price
                        cost = tranche_shares * entry_p
                        gain_val = proceeds - cost
                        gain_pct = (exit_price - entry_p) / entry_p * 100.0
                        cash += proceeds
                        pos["realized_pnl"] += gain_val
                        pos["exit_tranches"].append({
                            "tranche": "TRAIL_RUNNER",
                            "shares": tranche_shares,
                            "exit_price": exit_price,
                            "gain_pct": gain_pct,
                            "date": cur_date
                        })
                        pos["remaining_shares"] = 0
                        symbols_to_close.append(sym)

                else:
                    # T1 not yet hit: check if initial Stop Loss is hit
                    if l_p <= effective_sl:
                        # Full stop out (100% of shares)
                        tranche_shares = pos["remaining_shares"]
                        exit_price = effective_sl
                        proceeds = tranche_shares * exit_price
                        cost = tranche_shares * entry_p
                        gain_val = proceeds - cost
                        gain_pct = (exit_price - entry_p) / entry_p * 100.0
                        cash += proceeds
                        pos["realized_pnl"] += gain_val
                        pos["exit_tranches"].append({
                            "tranche": "FULL_SL",
                            "shares": tranche_shares,
                            "exit_price": exit_price,
                            "gain_pct": gain_pct,
                            "date": cur_date
                        })
                        pos["remaining_shares"] = 0
                        symbols_to_close.append(sym)

            else:
                # Standard 100% Milestone Exit at T1 or SL
                closed = False
                exit_price = 0.0
                exit_reason = ""

                if h_p >= pos["target_1"]:
                    closed = True
                    exit_price = pos["target_1"]
                    exit_reason = "T1_HIT"
                elif l_p <= effective_sl:
                    closed = True
                    exit_price = effective_sl
                    exit_reason = "TRAILING_SL_HIT" if effective_sl >= entry_p else "SL_HIT"

                if closed:
                    shares = pos["remaining_shares"]
                    proceeds = shares * exit_price
                    cost = shares * entry_p
                    gain_val = proceeds - cost
                    gain_pct = (exit_price - entry_p) / entry_p * 100.0
                    cash += proceeds
                    pos["realized_pnl"] = gain_val
                    pos["exit_tranches"].append({
                        "tranche": exit_reason,
                        "shares": shares,
                        "exit_price": exit_price,
                        "gain_pct": gain_pct,
                        "date": cur_date
                    })
                    pos["remaining_shares"] = 0
                    symbols_to_close.append(sym)

        # Finalize closed positions
        for sym in symbols_to_close:
            pos = active_positions[sym]
            total_cost = pos["initial_shares"] * pos["entry_price"]
            net_gain_val = pos["realized_pnl"]
            net_gain_pct = net_gain_val / total_cost * 100.0

            # Determine dominant exit reason
            tranche_names = [t["tranche"] for t in pos["exit_tranches"]]
            reason_str = "+".join(tranche_names)

            completed_trades.append({
                "symbol": sym,
                "entry_date": pos["entry_date"],
                "exit_date": cur_date,
                "entry_price": pos["entry_price"],
                "initial_shares": pos["initial_shares"],
                "total_cost": total_cost,
                "gain_val": net_gain_val,
                "gain_pct": net_gain_pct,
                "exit_reason": reason_str,
                "holding_days": pos["holding_days"],
                "max_high": pos["max_high"],
                "t1_hit": pos["t1_hit"]
            })
            del active_positions[sym]

        # -------------------------------------------------------------
        # Step B: LiquidBees Auto-Sweep Yield on Cash
        # -------------------------------------------------------------
        cash += cash * (liquid_yield_pct / 100.0 / 365.0)

        # -------------------------------------------------------------
        # Step C: Generate Signals on Day cur_date
        # -------------------------------------------------------------
        available_slots = max_active_positions - len(active_positions)
        target_per_slot = initial_capital / max_active_positions

        if available_slots > 0 and cash >= (target_per_slot * 0.4):
            valid_signals = []
            for sym, sym_df in prices_by_symbol.items():
                if sym in active_positions or cur_date not in sym_df.index:
                    continue

                row = sym_df.loc[cur_date]
                curr_c = float(row["close"])
                if curr_c < 20.0:
                    continue

                e50 = float(row["ema_50"])
                e200 = float(row["ema_200"])
                rsi = float(row["rsi_14"])
                atr = float(row["atr_14"])
                prox_52w = float(row["prox_52w"])
                mom_6m = float(row["mom_6m"])

                # Scoring
                score = 50.0
                if curr_c >= e50 >= e200: score += 15.0
                if prox_52w >= 90.0: score += 15.0
                elif prox_52w >= 80.0: score += 8.0
                if mom_6m >= 40.0: score += 15.0
                elif mom_6m >= 20.0: score += 8.0
                if 48.0 <= rsi <= 65.0: score += 10.0

                if (curr_c >= e50 and e50 >= e200 * 0.98 and
                    mom_6m >= min_momentum_6m_pct and
                    prox_52w >= 80.0 and
                    42.0 <= rsi <= 70.0 and
                    score >= min_composite_score):

                    t1 = round(curr_c + target_1_atr_mult * atr, 2)
                    t2 = round(curr_c + target_2_atr_mult * atr, 2)
                    t3 = round(curr_c + target_3_atr_mult * atr, 2)

                    # --- Rule 2: Symmetrical ATR vs Hard Floor ---
                    if use_symmetrical_atr:
                        # Pure symmetrical ATR: no arbitrary -5% hard floor!
                        sl = round(curr_c - sl_atr_mult * atr, 2)
                    else:
                        # Original baseline logic: hard -5% floor trap
                        sl = round(min(curr_c - sl_atr_mult * atr, curr_c * 0.95), 2)

                    valid_signals.append({
                        "symbol": sym,
                        "close": curr_c,
                        "score": score,
                        "mom_6m": mom_6m,
                        "t1": t1,
                        "t2": t2,
                        "t3": t3,
                        "sl": sl
                    })

            total_signals_generated += len(valid_signals)
            valid_signals.sort(key=lambda x: (x["score"], x["mom_6m"]), reverse=True)

            for sig in valid_signals[:available_slots]:
                alloc = min(cash * 0.95, target_per_slot)
                if alloc < 20000.0:
                    break

                shares = int(alloc / sig["close"])
                if shares <= 1:  # Need at least 2 shares for 50/50 scaling
                    continue

                actual_cost = shares * sig["close"]
                cash -= actual_cost

                active_positions[sig["symbol"]] = {
                    "entry_date": cur_date,
                    "entry_price": sig["close"],
                    "initial_shares": shares,
                    "remaining_shares": shares,
                    "stop_loss": sig["sl"],
                    "trailing_stop": sig["sl"],
                    "target_1": sig["t1"],
                    "target_2": sig["t2"],
                    "target_3": sig["t3"],
                    "t1_hit": False,
                    "t2_hit": False,
                    "max_high": sig["close"],
                    "min_low": sig["close"],
                    "current_price": sig["close"],
                    "holding_days": 0,
                    "realized_pnl": 0.0,
                    "exit_tranches": []
                }

        # -------------------------------------------------------------
        # Step D: Mark to Market Daily Valuation
        # -------------------------------------------------------------
        portfolio_pos_val = sum(pos["remaining_shares"] * pos["current_price"] for pos in active_positions.values())
        total_equity = cash + portfolio_pos_val
        strat_return = (total_equity - initial_capital) / initial_capital * 100.0
        nifty_cur = nifty_map.get(cur_date, nifty_start)
        nifty_ret = (nifty_cur - nifty_start) / nifty_start * 100.0

        daily_equity_history.append({
            "date": cur_date,
            "cash": cash,
            "positions_value": portfolio_pos_val,
            "total_equity": total_equity,
            "strategy_return_pct": strat_return,
            "benchmark_return_pct": nifty_ret,
            "alpha_pct": strat_return - nifty_ret,
            "open_positions": len(active_positions)
        })

    # 5. Final Valuation & Performance Computation
    final_equity = daily_equity_history[-1]["total_equity"]
    terminal_flows = [(d, amt) for d, amt in daily_cash_flows.items()]
    terminal_flows.append((datetime.strptime(end_date, "%Y-%m-%d").date(), final_equity))
    annualized_xirr = calculate_xirr(terminal_flows)

    total_trades = len(completed_trades)
    winning_trades = [t for t in completed_trades if t["gain_val"] > 0]
    losing_trades = [t for t in completed_trades if t["gain_val"] <= 0]

    gross_profit = sum(t["gain_val"] for t in winning_trades)
    gross_loss = abs(sum(t["gain_val"] for t in losing_trades))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 99.0

    win_rate = (len(winning_trades) / total_trades * 100.0) if total_trades > 0 else 0.0
    avg_win_pct = np.mean([t["gain_pct"] for t in winning_trades]) if winning_trades else 0.0
    avg_loss_pct = np.mean([t["gain_pct"] for t in losing_trades]) if losing_trades else 0.0
    payoff_ratio = round(abs(avg_win_pct / avg_loss_pct), 2) if abs(avg_loss_pct) > 0 else 0.0

    # Max Drawdown
    eq_series = pd.Series([d["total_equity"] for d in daily_equity_history])
    peak_series = eq_series.cummax()
    dd_series = (eq_series - peak_series) / peak_series * 100.0
    max_dd = abs(dd_series.min())

    exit_counts = {}
    for t in completed_trades:
        r = t["exit_reason"]
        exit_counts[r] = exit_counts.get(r, 0) + 1

    return {
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        "net_profit": final_equity - initial_capital,
        "strategy_return_pct": round(daily_equity_history[-1]["strategy_return_pct"], 2),
        "benchmark_return_pct": round(nifty_return_pct, 2),
        "alpha_pct": round(daily_equity_history[-1]["strategy_return_pct"] - nifty_return_pct, 2),
        "annualized_xirr": annualized_xirr,
        "total_trades": total_trades,
        "winning_trades": len(winning_trades),
        "losing_trades": len(losing_trades),
        "in_play_positions": len(active_positions),
        "win_rate_pct": round(win_rate, 1),
        "profit_factor": profit_factor,
        "payoff_ratio": payoff_ratio,
        "avg_win_pct": round(avg_win_pct, 2),
        "avg_loss_pct": round(avg_loss_pct, 2),
        "max_drawdown_pct": round(max_dd, 1),
        "avg_holding_days": round(float(np.mean([t["holding_days"] for t in completed_trades])), 1) if completed_trades else 0.0,
        "exit_counts": exit_counts,
        "completed_trades": completed_trades
    }


if __name__ == "__main__":
    print("=" * 115)
    print("🔬 COMPREHENSIVE BACKTEST: TESTING TACTICAL SWING OPTIMIZATIONS (JULY 1 - SEPT 22, 2026)")
    print("=" * 115)

    experiments = [
        ("0. Baseline (The Flawed Trap: Ratchet at 2.5%, -5% Hard Floor SL, 100% at T1)", {
            "breakeven_min_gain_pct": 2.5,
            "use_symmetrical_atr": False,
            "scaling_exit_mode": "NONE",
            "target_1_atr_mult": 1.5,
            "sl_atr_mult": 1.5
        }),
        ("1. Rule 1 Isolated: Noise Filter (No Breakeven < 4.5%, Ratchet only at >=4.5%)", {
            "breakeven_min_gain_pct": 4.5,
            "use_symmetrical_atr": False,
            "scaling_exit_mode": "NONE",
            "target_1_atr_mult": 1.5,
            "sl_atr_mult": 1.5
        }),
        ("2. Rule 2 Isolated: Symmetrical ATR Risk-Reward (SL = 1.5 ATR, no -5% floor)", {
            "breakeven_min_gain_pct": 2.5,
            "use_symmetrical_atr": True,
            "scaling_exit_mode": "NONE",
            "target_1_atr_mult": 1.5,
            "sl_atr_mult": 1.5
        }),
        ("3. Rule 1 + Rule 2 Combined: Noise Filter (4.5%) + Symmetrical ATR (1.5 / 1.5)", {
            "breakeven_min_gain_pct": 4.5,
            "use_symmetrical_atr": True,
            "scaling_exit_mode": "NONE",
            "target_1_atr_mult": 1.5,
            "sl_atr_mult": 1.5
        }),
        ("4. Rule 3 Isolated: Scaling Exits (50% at T1, 50% Runner to T2/Breakeven)", {
            "breakeven_min_gain_pct": 2.5,
            "use_symmetrical_atr": False,
            "scaling_exit_mode": "SCALE_50_50",
            "target_1_atr_mult": 1.5,
            "target_2_atr_mult": 3.0,
            "sl_atr_mult": 1.5
        }),
        ("5. Institutional Grand Synthesis: Rules 1 + 2 + 3 (Noise Filter + Symmetric ATR + 50/50 Scaling)", {
            "breakeven_min_gain_pct": 4.5,
            "use_symmetrical_atr": True,
            "scaling_exit_mode": "SCALE_50_50",
            "target_1_atr_mult": 1.5,
            "target_2_atr_mult": 3.0,
            "sl_atr_mult": 1.5
        }),
        ("6. Asymmetric Favorable Alpha Engine: (T1=2.0 ATR, SL=1.5 ATR, 50/50 Scaling to T2=3.5 ATR)", {
            "breakeven_min_gain_pct": 5.0,
            "use_symmetrical_atr": True,
            "scaling_exit_mode": "SCALE_50_50",
            "target_1_atr_mult": 2.0,
            "target_2_atr_mult": 3.5,
            "sl_atr_mult": 1.5
        }),
    ]

    results = []
    for label, params in experiments:
        print(f"▶️ Running: {label}...")
        res = run_tactical_backtest(**params)
        results.append((label, res))

    print("\n" + "=" * 125)
    print(f"{'Strategy Variant':<60} | {'Return':<7} | {'Alpha':<7} | {'XIRR':<7} | {'Win %':<5} | {'PF':<5} | {'Payoff':<6} | {'Max DD':<6}")
    print("-" * 125)
    for label, r in results:
        print(f"{label:<60} | {r['strategy_return_pct']:+5.2f}% | {r['alpha_pct']:+5.2f}% | {r['annualized_xirr']:+5.1f}% | {r['win_rate_pct']:4.1f}% | {r['profit_factor']:4.2f} | {r['payoff_ratio']:5.2f}x | {r['max_drawdown_pct']:5.1f}%")
    print("=" * 125)
    print(f"Benchmark NIFTY 50 Return over same 60 sessions: {results[0][1]['benchmark_return_pct']:+.2f}%\n")
