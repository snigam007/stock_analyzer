#!/usr/bin/env python3
"""
scripts/backtest_advanced_swing_strategies.py

Comprehensive Backtester evaluating the 4 proposed Swing Optimization Strategies:
1. Strategy 1: Asymmetric 1.6:1 Volatility Coiling Filter (T1 = 2.0 ATR, SL = 1.25 ATR + VCP / Volatility Squeeze)
2. Strategy 2: Bimodal Regime-Adaptive Exit Execution (Milestone T1 during Risk-Off/Neutral vs Scaling Runners in Bull)
3. Strategy 3: Time-Based Stop / Velocity Guardrail (Inactivity Decay Cut: exit after 5 days if peak gain < 1.5%)
4. Strategy 4: Relative Strength (RS) Momentum Frontrunning (Mansfield RS vs NIFTY 50 > 0, 3M RS Rank >= 75)
5. Strategy 5 (Grand Master Synthesis): All 4 Strategies Combined!

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


def run_advanced_swing_backtest(
    strategy_name: str,
    start_date: str = "2026-07-01",
    end_date: str = "2026-09-22",
    initial_capital: float = 1000000.0,
    max_active_positions: int = 10,
    # Strategy 1 Parameters: Asymmetric Volatility Coiling
    use_asymmetric_rr: bool = False,
    t1_atr_mult: float = 1.5,
    sl_atr_mult: float = 1.5,
    use_vcp_filter: bool = False,
    # Strategy 2 Parameters: Regime Adaptive Exit
    use_regime_adaptive_exits: bool = False,
    # Strategy 3 Parameters: Time Stop
    use_time_stop: bool = False,
    max_stagnant_days: int = 5,
    stagnant_min_gain_pct: float = 1.5,
    # Strategy 4 Parameters: Relative Strength Filter
    use_relative_strength_filter: bool = False,
    min_rs_outperformance_pct: float = 5.0,
    # Common Noise Filter
    breakeven_min_gain_pct: float = 4.5,
    liquid_yield_pct: float = 6.5
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

    # 2. Benchmark NIFTY 50 & Regime Precomputation
    nifty_df = pd.read_sql(text("""
        SELECT date, open, high, low, close
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

    first_d = trading_dates[0]
    last_d = trading_dates[-1]
    nifty_start = nifty_map.get(first_d, {}).get("close", 24710.25)
    nifty_end = nifty_map.get(last_d, {}).get("close", 24013.80)
    nifty_return_pct = (nifty_end - nifty_start) / nifty_start * 100.0

    # 3. Load Stocks Price Matrix & Precompute Indicators
    df_prices = pd.read_sql(text("""
        SELECT symbol, date, open, high, low, close, volume
        FROM daily_prices
        WHERE date >= '2024-01-01' AND date <= :e
        ORDER BY symbol, date ASC
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

        # Bollinger Band Width (for Volatility Squeeze / VCP Detection)
        sma_20 = group["close"].rolling(20, min_periods=20).mean()
        std_20 = group["close"].rolling(20, min_periods=20).std()
        group["bbw"] = ((std_20 * 4.0) / sma_20 * 100.0).fillna(10.0)
        group["bbw_percentile"] = group["bbw"].rolling(120, min_periods=30).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1] * 100.0 if len(x) > 0 else 50.0
        ).fillna(50.0)

        # Proximity to 52W High
        group["high_52w"] = group["high"].rolling(250, min_periods=30).max()
        group["prox_52w"] = (group["close"] / group["high_52w"] * 100.0).fillna(85.0)

        # Momentum 1M and 6M
        group["mom_1m"] = ((group["close"] - group["close"].shift(20)) / group["close"].shift(20) * 100.0).fillna(0.0)
        group["mom_3m"] = ((group["close"] - group["close"].shift(60)) / group["close"].shift(60) * 100.0).fillna(0.0)
        group["mom_6m"] = ((group["close"] - group["close"].shift(126)) / group["close"].shift(126) * 100.0).fillna(0.0)

        prices_by_symbol[sym] = group.set_index("date")

    session.close()

    # 4. Simulation Engine
    cash = initial_capital
    active_positions = {}  # sym -> dict
    completed_trades = []
    daily_equity_history = []
    daily_cash_flows = {datetime.strptime(start_date, "%Y-%m-%d").date(): -initial_capital}

    for day_idx, cur_date in enumerate(trading_dates):
        cur_nifty = nifty_map.get(cur_date, {})
        nifty_c = cur_nifty.get("close", 24000.0)
        nifty_e50 = cur_nifty.get("ema_50", 24000.0)
        nifty_e21 = cur_nifty.get("ema_21", 24000.0)
        is_bull_regime = (nifty_c >= nifty_e50 and nifty_c >= nifty_e21)

        # -------------------------------------------------------------
        # Step A: Manage Existing Positions
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

            # Rule 1 Noise Filter: Ratchet to Breakeven (+0.5%) only if gain >= 4.5%
            if cur_peak_pct >= breakeven_min_gain_pct:
                pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.005, 2))

            # Trail runner if gain >= 8%
            if cur_peak_pct >= 8.0:
                pos["trailing_stop"] = max(pos["trailing_stop"], round(pos["max_high"] * 0.965, 2))

            effective_sl = max(pos["stop_loss"], pos["trailing_stop"])

            # ---------------------------------------------------------
            # Evaluate Exits
            # ---------------------------------------------------------
            closed = False
            exit_price = 0.0
            exit_reason = ""

            # Check Strategy 3: Time-Based Stop (Inactivity Decay Cut)
            # If held for >= max_stagnant_days and peak gain < stagnant_min_gain_pct: exit at market!
            if use_time_stop and pos["holding_days"] >= max_stagnant_days and cur_peak_pct < stagnant_min_gain_pct:
                closed = True
                exit_price = c_p
                exit_reason = "TIME_INACTIVITY_EXIT"

            # Check Target Exits (Bimodal Regime-Adaptive vs Fixed Milestone)
            if not closed:
                if use_regime_adaptive_exits and is_bull_regime:
                    # In Bull Regime: Scale out 50% at T1, let 50% run to T2
                    if not pos["t1_hit"] and h_p >= pos["target_1"]:
                        pos["t1_hit"] = True
                        half_shares = pos["initial_shares"] // 2
                        if half_shares > 0:
                            proceeds = half_shares * pos["target_1"]
                            gain_val = proceeds - (half_shares * entry_p)
                            cash += proceeds
                            pos["remaining_shares"] -= half_shares
                            pos["realized_pnl"] += gain_val
                            pos["exit_tranches"].append({
                                "tranche": "T1_HALF",
                                "shares": half_shares,
                                "price": pos["target_1"],
                                "gain_pct": (pos["target_1"] - entry_p) / entry_p * 100.0,
                                "date": cur_date
                            })
                            pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.005, 2))
                            effective_sl = max(pos["stop_loss"], pos["trailing_stop"])

                    if pos["t1_hit"]:
                        if h_p >= pos["target_2"]:
                            closed = True
                            exit_price = pos["target_2"]
                            exit_reason = "T2_RUNNER_HIT"
                        elif l_p <= effective_sl:
                            closed = True
                            exit_price = effective_sl
                            exit_reason = "TRAIL_RUNNER_HIT"
                    else:
                        if l_p <= effective_sl:
                            closed = True
                            exit_price = effective_sl
                            exit_reason = "SL_HIT"

                else:
                    # Neutral / Risk-Off or Standard: 100% Clean Milestone Exit at T1 or SL
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
                cash += proceeds
                pos["realized_pnl"] += gain_val
                pos["exit_tranches"].append({
                    "tranche": exit_reason,
                    "shares": shares,
                    "price": exit_price,
                    "gain_pct": (exit_price - entry_p) / entry_p * 100.0,
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
            reasons = [t["tranche"] for t in pos["exit_tranches"]]

            completed_trades.append({
                "symbol": sym,
                "entry_date": pos["entry_date"],
                "exit_date": cur_date,
                "entry_price": pos["entry_price"],
                "initial_shares": pos["initial_shares"],
                "total_cost": total_cost,
                "gain_val": net_gain_val,
                "gain_pct": net_gain_pct,
                "exit_reason": "+".join(reasons),
                "holding_days": pos["holding_days"],
                "max_high": pos["max_high"],
                "t1_hit": pos["t1_hit"]
            })
            del active_positions[sym]

        # -------------------------------------------------------------
        # Step B: Overnight Liquid Yield Auto-Sweep
        # -------------------------------------------------------------
        cash += cash * (liquid_yield_pct / 100.0 / 365.0)

        # -------------------------------------------------------------
        # Step C: Point-in-Time Daily Signal Discovery
        # -------------------------------------------------------------
        available_slots = max_active_positions - len(active_positions)
        target_per_slot = initial_capital / max_active_positions

        if available_slots > 0 and cash >= (target_per_slot * 0.4):
            candidates = []
            nifty_20d_ret = cur_nifty.get("mom_20d", 0.0)
            nifty_60d_ret = cur_nifty.get("mom_60d", 0.0)

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
                prox_52w = float(row["prox_52w"])
                mom_6m = float(row["mom_6m"])
                mom_1m = float(row["mom_1m"])
                mom_3m = float(row["mom_3m"])
                bbw_pctile = float(row["bbw_percentile"])

                # Base Trend & Momentum Alignment
                if not (c_val >= e50 and e50 >= e200 * 0.98 and mom_6m >= 25.0 and prox_52w >= 80.0 and 42.0 <= rsi <= 70.0):
                    continue

                # Strategy 1 Filter: Volatility Contraction Pattern (VCP) Squeeze
                # Only enter when Bollinger Band Width is in bottom 40th percentile (coiling)
                if use_vcp_filter and bbw_pctile > 40.0:
                    continue

                # Strategy 4 Filter: Relative Strength (Mansfield Outperformance vs NIFTY 50)
                # Stock must outperform NIFTY over both 1M and 3M horizons by >= min_rs_outperformance_pct
                if use_relative_strength_filter:
                    rs_1m = mom_1m - nifty_20d_ret
                    rs_3m = mom_3m - nifty_60d_ret
                    if rs_1m < min_rs_outperformance_pct or rs_3m < 0.0:
                        continue

                # Target & Stop Loss Calibration
                if use_asymmetric_rr:
                    # Strategy 1: Asymmetric 1.6:1 (T1 = 2.0 ATR, SL = 1.25 ATR)
                    t1 = round(c_val + t1_atr_mult * atr, 2)
                    t2 = round(c_val + (t1_atr_mult + 1.5) * atr, 2)
                    sl = round(c_val - sl_atr_mult * atr, 2)
                else:
                    # Symmetric 1.5 / 1.5 ATR
                    t1 = round(c_val + t1_atr_mult * atr, 2)
                    t2 = round(c_val + (t1_atr_mult + 1.5) * atr, 2)
                    sl = round(c_val - sl_atr_mult * atr, 2)

                # Composite Conviction Scoring
                score = 60.0
                if c_val >= e50 >= e200: score += 10.0
                if prox_52w >= 90.0: score += 10.0
                if mom_6m >= 40.0: score += 10.0
                if 48.0 <= rsi <= 62.0: score += 10.0

                candidates.append({
                    "symbol": sym,
                    "close": c_val,
                    "score": score,
                    "mom_6m": mom_6m,
                    "t1": t1,
                    "t2": t2,
                    "sl": sl
                })

            candidates.sort(key=lambda x: (x["score"], x["mom_6m"]), reverse=True)

            for cand in candidates[:available_slots]:
                alloc = min(cash * 0.95, target_per_slot)
                if alloc < 20000.0:
                    break

                shares = int(alloc / cand["close"])
                if shares <= 1:
                    continue

                actual_cost = shares * cand["close"]
                cash -= actual_cost

                active_positions[cand["symbol"]] = {
                    "entry_date": cur_date,
                    "entry_price": cand["close"],
                    "initial_shares": shares,
                    "remaining_shares": shares,
                    "stop_loss": cand["sl"],
                    "trailing_stop": cand["sl"],
                    "target_1": cand["t1"],
                    "target_2": cand["t2"],
                    "t1_hit": False,
                    "max_high": cand["close"],
                    "min_low": cand["close"],
                    "current_price": cand["close"],
                    "holding_days": 0,
                    "realized_pnl": 0.0,
                    "exit_tranches": []
                }

        # -------------------------------------------------------------
        # Step D: Mark to Market Daily Valuation
        # -------------------------------------------------------------
        port_val = sum(pos["remaining_shares"] * pos["current_price"] for pos in active_positions.values())
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

    # 5. Performance Metrics
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
        "strategy_name": strategy_name,
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
        "exit_counts": exit_counts
    }


if __name__ == "__main__":
    print("=" * 125)
    print("🚀 EXTENSIVE BACKTEST OF ALL 4 ADVANCED SWING OPTIMIZATION STRATEGIES (JULY 1 - SEPT 22, 2026)")
    print("=" * 125)

    experiments = [
        ("Baseline (Clean Symmetrical 1.5 ATR + Noise Filter)", {
            "use_asymmetric_rr": False,
            "t1_atr_mult": 1.5,
            "sl_atr_mult": 1.5,
            "use_vcp_filter": False,
            "use_regime_adaptive_exits": False,
            "use_time_stop": False,
            "use_relative_strength_filter": False
        }),
        ("Strategy 1: Asymmetric 1.6:1 R:R (T1=2.0 ATR, SL=1.25 ATR + VCP Squeeze)", {
            "use_asymmetric_rr": True,
            "t1_atr_mult": 2.0,
            "sl_atr_mult": 1.25,
            "use_vcp_filter": True,
            "use_regime_adaptive_exits": False,
            "use_time_stop": False,
            "use_relative_strength_filter": False
        }),
        ("Strategy 2: Bimodal Regime-Adaptive Exits (Milestone in Bear/Flat vs Scaling in Bull)", {
            "use_asymmetric_rr": False,
            "t1_atr_mult": 1.5,
            "sl_atr_mult": 1.5,
            "use_vcp_filter": False,
            "use_regime_adaptive_exits": True,
            "use_time_stop": False,
            "use_relative_strength_filter": False
        }),
        ("Strategy 3: Time-Based Stop / Velocity Guardrail (Inactivity Cut: 5 Days < 1.5% Gain)", {
            "use_asymmetric_rr": False,
            "t1_atr_mult": 1.5,
            "sl_atr_mult": 1.5,
            "use_vcp_filter": False,
            "use_regime_adaptive_exits": False,
            "use_time_stop": True,
            "max_stagnant_days": 5,
            "stagnant_min_gain_pct": 1.5,
            "use_relative_strength_filter": False
        }),
        ("Strategy 4: Relative Strength (RS) Momentum Frontrunning (Outperforming NIFTY)", {
            "use_asymmetric_rr": False,
            "t1_atr_mult": 1.5,
            "sl_atr_mult": 1.5,
            "use_vcp_filter": False,
            "use_regime_adaptive_exits": False,
            "use_time_stop": False,
            "use_relative_strength_filter": True,
            "min_rs_outperformance_pct": 4.0
        }),
        ("Strategy 5: Grand Master Combo (Asymmetric 1.6:1 + Time Stop + RS Frontrunner)", {
            "use_asymmetric_rr": True,
            "t1_atr_mult": 2.0,
            "sl_atr_mult": 1.25,
            "use_vcp_filter": True,
            "use_regime_adaptive_exits": True,
            "use_time_stop": True,
            "max_stagnant_days": 5,
            "stagnant_min_gain_pct": 1.5,
            "use_relative_strength_filter": True,
            "min_rs_outperformance_pct": 4.0
        })
    ]

    results = []
    for name, params in experiments:
        print(f"\n▶️ Running: {name}...")
        r = run_advanced_swing_backtest(strategy_name=name, **params)
        results.append(r)
        print(f"   • Return: {r['strategy_return_pct']:+.2f}% | Alpha: {r['alpha_pct']:+.2f}% | XIRR: {r['annualized_xirr']:+.1f}%")
        print(f"   • Win Rate: {r['win_rate_pct']}% ({r['winning_trades']}W / {r['losing_trades']}L) | PF: {r['profit_factor']:.2f} | Payoff: {r['payoff_ratio']:.2f}x")
        print(f"   • Avg Win: +{r['avg_win_pct']:.2f}% | Avg Loss: {r['avg_loss_pct']:.2f}% | Max DD: {r['max_drawdown_pct']:.1f}% | Avg Days: {r['avg_holding_days']:.1f}d")
        print(f"   • Exits: {r['exit_counts']}")

    print("\n" + "=" * 135)
    print(f"{'Strategy Variant':<65} | {'Return':<7} | {'Alpha':<7} | {'XIRR':<7} | {'Win %':<5} | {'PF':<5} | {'Payoff':<6} | {'Max DD':<6}")
    print("-" * 135)
    for r in results:
        print(f"{r['strategy_name']:<65} | {r['strategy_return_pct']:+5.2f}% | {r['alpha_pct']:+5.2f}% | {r['annualized_xirr']:+5.1f}% | {r['win_rate_pct']:4.1f}% | {r['profit_factor']:4.2f} | {r['payoff_ratio']:5.2f}x | {r['max_drawdown_pct']:5.1f}%")
    print("=" * 135)
    print(f"Benchmark NIFTY 50 Return over same 60 sessions: {results[0]['benchmark_return_pct']:+.2f}%\n")
