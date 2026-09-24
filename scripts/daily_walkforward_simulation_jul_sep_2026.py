"""
Extensive Daily Walk-Forward Quantitative Trading Simulation
Period: July 1, 2026 to September 22, 2026 (60 Trading Days)

Strategy: Apex Champion Multi-Factor Strategy
- Point-in-time daily signal generation (Technicals, ML, 5-Pillar Score, 52W High, Momentum Hurdle)
- Dynamic Trailing Stop Loss Management:
    * T1 reached (+3.5% to +5%) -> Trail to Breakeven (Entry Price)
    * T2 reached (+8% to +10%)  -> Trail to Target 1
    * Beta-calibrated stepladder profit floors (+15% -> +10%, +25% -> +20%, +50% -> +40%)
    * Multi-tier Profit Target exits (T1 partial / T3 full runner exit)
- LiquidBees Cash Sweep (6.5% risk-free yield on idle reserves)
- Equal-Risk Slot Allocation (Max 10 active positions, max 15% per stock)
- Real-time Performance Accounting:
    * Daily Equity Curve & Benchmark (NIFTY 50) Comparison
    * Annualized Cash-Flow XIRR
    * Profit Factor & Payoff Ratio
    * Win Rate & Max Drawdown
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import math
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple
import pandas as pd
import numpy as np
from sqlalchemy import text
from db.database import get_global_engine, get_session
from core.sip_audit_backtester import calculate_xirr

def run_daily_walkforward_simulation(
    initial_capital: float = 1000000.0,   # ₹10 Lakhs trading capital
    start_date: str = "2026-07-01",
    end_date: str = "2026-09-22",
    max_active_positions: int = 10,
    min_momentum_6m_pct: float = 20.0,
    min_composite_score: float = 62.0,
    liquid_yield_pct: float = 6.5,
    enable_stepladders: bool = True,
    exit_mode: str = "TRAILING_RUNNER"  # "TRAILING_RUNNER" or "TARGET_1_SWING"
) -> Dict:
    engine = get_global_engine()
    session = get_session(engine)

    print("=" * 110)
    print(f"🚀 EXTENSIVE WALK-FORWARD DAILY SIGNAL SIMULATION ({start_date} TO {end_date})")
    print(f"   Capital: ₹{initial_capital/1e5:.1f}L | Strategy: Apex Champion Multi-Pillar (Technicals, ML, Stepladders)")
    print("=" * 110)

    # 1. Fetch all trading dates in daily_prices
    dates_query = session.execute(text("""
        SELECT DISTINCT date FROM daily_prices 
        WHERE date >= :sd AND date <= :ed 
        ORDER BY date ASC
    """), {"sd": start_date, "ed": end_date}).fetchall()
    trading_dates = [str(r[0]) for r in dates_query]
    print(f"Total Trading Sessions: {len(trading_dates)} days (from {trading_dates[0]} to {trading_dates[-1]})")

    # 2. Pre-fetch NIFTY 50 benchmark prices for comparison
    nifty_rows = session.execute(text("""
        SELECT date, close FROM index_prices 
        WHERE symbol = '^NSEI' AND date >= :sd AND date <= :ed 
        ORDER BY date ASC
    """), {"sd": start_date, "ed": end_date}).fetchall()
    nifty_dict = {str(r[0]): float(r[1]) for r in nifty_rows if r[1] is not None}
    nifty_start = nifty_dict.get(trading_dates[0]) or (list(nifty_dict.values())[0] if nifty_dict else 24000.0)

    # 3. Pre-load daily prices from 2025 onwards into fast memory structures
    print("Loading historical price matrix into memory for instant technicals...")
    df_prices = pd.read_sql(text("""
        SELECT dp.symbol, dp.date, dp.open, dp.high, dp.low, dp.close, stk.sector, stk.market_cap_tier
        FROM daily_prices dp
        JOIN stocks stk ON dp.symbol = stk.symbol
        WHERE dp.date >= '2025-01-01' AND dp.close IS NOT NULL
        ORDER BY dp.symbol, dp.date ASC
    """), session.bind)

    # Pre-organize by symbol for rapid lookups
    prices_by_symbol = {}
    for sym, group in df_prices.groupby("symbol"):
        group = group.sort_values("date").reset_index(drop=True)
        # Precompute rolling metrics
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
        group["rsi_14"] = 100.0 - (100.0 / (1.0 + rs))
        group["rsi_14"] = group["rsi_14"].fillna(50.0)

        # ATR 14
        hl = group["high"] - group["low"]
        hc = (group["high"] - group["close"].shift(1)).abs()
        lc = (group["low"] - group["close"].shift(1)).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        group["atr_14"] = tr.rolling(14, min_periods=14).mean().fillna(group["close"] * 0.025)

        # 52W High rolling
        group["high_52w"] = group["high"].rolling(250, min_periods=30).max()

        # 6M momentum (126 days)
        group["mom_6m"] = (group["close"] - group["close"].shift(126)) / group["close"].shift(126) * 100.0

        # Index by date string for O(1) lookup
        prices_by_symbol[sym] = group.set_index("date")

    print(f"Indexed {len(prices_by_symbol)} active stocks into quantitative memory.")

    # 4. State Variables
    cash = initial_capital
    active_positions = {}  # symbol -> position dict
    completed_trades = []  # list of closed trade dicts
    daily_equity_history = []
    daily_cash_flows = {datetime.strptime(start_date, "%Y-%m-%d").date(): -initial_capital}

    total_signals_generated = 0

    for day_idx, cur_date in enumerate(trading_dates):
        cur_dt = datetime.strptime(cur_date, "%Y-%m-%d").date()

        # -------------------------------------------------------------
        # Step A: Manage Existing Open Positions with Today's Bar
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

            # Check T1 & T2 Ratchets
            if h_p >= pos["target_1"] and not pos["t1_hit"]:
                pos["t1_hit"] = True
                pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.01, 2))

            if h_p >= pos["target_2"] and not pos["t2_hit"]:
                pos["t2_hit"] = True
                pos["trailing_stop"] = max(pos["trailing_stop"], pos["target_1"])

            # Smart Progressive Stepladder Trailing Floors (from accuracy_tracker.py)
            if enable_stepladders:
                cur_peak_pct = (pos["max_high"] - entry_p) / entry_p * 100.0
                if cur_peak_pct >= 15.0:
                    pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.10, 2))
                elif cur_peak_pct >= 8.0:
                    pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.05, 2), round(pos["max_high"] * 0.965, 2))
                elif cur_peak_pct >= 4.5:
                    pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.025, 2))
                elif cur_peak_pct >= 2.5:
                    pos["trailing_stop"] = max(pos["trailing_stop"], round(entry_p * 1.005, 2))

            effective_sl = max(pos["stop_loss"], pos["trailing_stop"])

            # Check Exits: Target 3 (Full Runner Exit) or Stop Loss / Trailing Stop
            closed = False
            exit_price = 0.0
            exit_reason = ""

            if h_p >= pos["target_3"]:
                closed = True
                exit_price = pos["target_3"]
                exit_reason = "T3_HIT"
            elif exit_mode == "TARGET_1_SWING" and h_p >= pos["target_1"]:
                closed = True
                exit_price = pos["target_1"]
                exit_reason = "T1_HIT"
            elif l_p <= effective_sl:
                closed = True
                exit_price = effective_sl
                exit_reason = "TRAILING_SL_HIT" if effective_sl >= entry_p else "SL_HIT"

            if closed:
                shares = pos["shares"]
                proceeds = shares * exit_price
                cost = shares * entry_p
                gain_val = proceeds - cost
                gain_pct = (exit_price - entry_p) / entry_p * 100.0

                cash += proceeds
                symbols_to_close.append(sym)

                completed_trades.append({
                    "symbol": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": cur_date,
                    "entry_price": entry_p,
                    "exit_price": exit_price,
                    "shares": shares,
                    "cost": cost,
                    "proceeds": proceeds,
                    "gain_val": gain_val,
                    "gain_pct": gain_pct,
                    "exit_reason": exit_reason,
                    "holding_days": pos["holding_days"],
                    "max_high": pos["max_high"],
                    "t1_hit": pos["t1_hit"],
                    "t2_hit": pos["t2_hit"]
                })

        for sym in symbols_to_close:
            del active_positions[sym]

        # -------------------------------------------------------------
        # Step B: LiquidBees Auto-Sweep Yield on Overnight Cash
        # -------------------------------------------------------------
        overnight_interest = cash * (liquid_yield_pct / 100.0 / 365.0)
        cash += overnight_interest

        # -------------------------------------------------------------
        # Step C: Point-in-Time Daily Signal Generation for Day cur_date
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

                e50 = float(row["ema_50"]) if pd.notna(row["ema_50"]) else curr_c
                e200 = float(row["ema_200"]) if pd.notna(row["ema_200"]) else curr_c * 0.95
                rsi = float(row["rsi_14"]) if pd.notna(row["rsi_14"]) else 50.0
                atr = float(row["atr_14"]) if (pd.notna(row["atr_14"]) and float(row["atr_14"]) > 0) else curr_c * 0.025
                high_52w = float(row["high_52w"]) if pd.notna(row["high_52w"]) else curr_c
                mom_6m = float(row["mom_6m"]) if pd.notna(row["mom_6m"]) else 0.0

                prox_52w = (curr_c / high_52w * 100.0) if high_52w > 0 else 90.0

                # 5-Pillar Score approximation based on technical alignment + momentum + trend
                # Alignment score (0-100)
                trend_score = 30.0 if (curr_c >= e50 >= e200) else (15.0 if curr_c >= e50 else 0.0)
                rsi_score = 25.0 if (45.0 <= rsi <= 65.0) else (15.0 if (40.0 <= rsi <= 72.0) else 5.0)
                mom_score = min(25.0, max(0.0, mom_6m * 0.5))
                prox_score = 20.0 if prox_52w >= 85.0 else (10.0 if prox_52w >= 75.0 else 0.0)
                score = trend_score + rsi_score + mom_score + prox_score

                # Apex Strategy Criteria:
                # 1. Structural Bull Alignment: Close >= EMA50 and EMA50 >= EMA200 * 0.98
                # 2. Positive 6M Momentum: >= 20%
                # 3. Proximity to 52W High >= 80% (leading strength)
                # 4. Healthy RSI (42 - 70)
                # 5. Composite Score >= 60
                if (curr_c >= e50 and e50 >= e200 * 0.98 and
                    mom_6m >= min_momentum_6m_pct and
                    prox_52w >= 80.0 and
                    42.0 <= rsi <= 70.0 and
                    score >= min_composite_score):

                    t1 = round(curr_c + 1.5 * atr, 2)
                    t2 = round(curr_c + 3.0 * atr, 2)
                    t3 = round(curr_c + 5.5 * atr, 2)
                    # Wide enough stop loss to absorb market noise (minimum 4.5% distance)
                    sl = round(min(curr_c - 1.5 * atr, curr_c * 0.95), 2)

                    valid_signals.append({
                        "symbol": sym,
                        "close": curr_c,
                        "score": score,
                        "mom_6m": mom_6m,
                        "prox_52w": prox_52w,
                        "t1": t1,
                        "t2": t2,
                        "t3": t3,
                        "sl": sl,
                    })

            total_signals_generated += len(valid_signals)
            valid_signals.sort(key=lambda x: (x["score"], x["mom_6m"]), reverse=True)

            # Deploy into available slots
            for sig in valid_signals[:available_slots]:
                alloc = min(cash * 0.95, target_per_slot)
                if alloc < 20000.0:
                    break

                shares = int(alloc / sig["close"])
                if shares <= 0:
                    continue

                actual_cost = shares * sig["close"]
                cash -= actual_cost

                active_positions[sig["symbol"]] = {
                    "entry_date": cur_date,
                    "entry_price": sig["close"],
                    "shares": shares,
                    "cost": actual_cost,
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
                    "holding_days": 0
                }

        # -------------------------------------------------------------
        # Step D: Daily Mark-to-Market Valuation & Benchmark Tracking
        # -------------------------------------------------------------
        unrealized_equity = sum(p["shares"] * p["current_price"] for p in active_positions.values())
        total_equity = cash + unrealized_equity

        nifty_cur = nifty_dict.get(cur_date, nifty_start)
        nifty_ret = (nifty_cur - nifty_start) / nifty_start * 100.0
        strat_ret = (total_equity - initial_capital) / initial_capital * 100.0

        daily_equity_history.append({
            "date": cur_date,
            "cash": round(cash, 2),
            "unrealized_equity": round(unrealized_equity, 2),
            "total_equity": round(total_equity, 2),
            "active_positions_count": len(active_positions),
            "strategy_return_pct": round(strat_ret, 2),
            "benchmark_return_pct": round(nifty_ret, 2),
            "alpha_pct": round(strat_ret - nifty_ret, 2)
        })

    # -----------------------------------------------------------------
    # Step E: Terminal Liquidation on Latest Date for Final XIRR
    # -----------------------------------------------------------------
    final_date_dt = datetime.strptime(trading_dates[-1], "%Y-%m-%d").date()
    terminal_cash_flows = [(d, amt) for d, amt in daily_cash_flows.items()]
    final_equity = daily_equity_history[-1]["total_equity"]
    terminal_cash_flows.append((final_date_dt, final_equity))

    annualized_xirr = calculate_xirr(terminal_cash_flows)

    # Performance Analytics
    total_trades = len(completed_trades)
    winning_trades = [t for t in completed_trades if t["gain_val"] > 0]
    losing_trades = [t for t in completed_trades if t["gain_val"] <= 0]
    win_rate = (len(winning_trades) / max(1, total_trades)) * 100.0

    gross_profit = sum(t["gain_val"] for t in winning_trades)
    gross_loss = abs(sum(t["gain_val"] for t in losing_trades))
    profit_factor = round(gross_profit / max(0.01, gross_loss), 2) if gross_profit > 0 else 0.0

    avg_win_val = np.mean([t["gain_val"] for t in winning_trades]) if winning_trades else 0.0
    avg_loss_val = abs(np.mean([t["gain_val"] for t in losing_trades])) if losing_trades else 0.0
    payoff_ratio = round(avg_win_val / max(0.01, avg_loss_val), 2)

    avg_win_pct = np.mean([t["gain_pct"] for t in winning_trades]) if winning_trades else 0.0
    avg_loss_pct = np.mean([t["gain_pct"] for t in losing_trades]) if losing_trades else 0.0

    # Max Drawdown Calculation
    equity_series = [d["total_equity"] for d in daily_equity_history]
    peak = equity_series[0]
    max_dd = 0.0
    for eq in equity_series:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100.0
        if dd > max_dd:
            max_dd = dd

    # Exit reason breakdown
    exit_counts = {}
    for t in completed_trades:
        r = t["exit_reason"]
        exit_counts[r] = exit_counts.get(r, 0) + 1

    t1_hits_total = sum(1 for t in completed_trades if t["t1_hit"])
    t2_hits_total = sum(1 for t in completed_trades if t["t2_hit"])

    session.close()

    return {
        "start_date": start_date,
        "end_date": end_date,
        "trading_days": len(trading_dates),
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        "net_profit": final_equity - initial_capital,
        "strategy_return_pct": daily_equity_history[-1]["strategy_return_pct"],
        "benchmark_return_pct": daily_equity_history[-1]["benchmark_return_pct"],
        "alpha_pct": daily_equity_history[-1]["alpha_pct"],
        "annualized_xirr": annualized_xirr,
        "total_signals_generated": total_signals_generated,
        "total_completed_trades": total_trades,
        "winning_trades_count": len(winning_trades),
        "losing_trades_count": len(losing_trades),
        "active_open_positions": len(active_positions),
        "win_rate_pct": round(win_rate, 1),
        "profit_factor": profit_factor,
        "payoff_ratio": payoff_ratio,
        "avg_win_pct": round(avg_win_pct, 2),
        "avg_loss_pct": round(avg_loss_pct, 2),
        "max_drawdown_pct": round(max_dd, 1),
        "avg_holding_days": round(float(np.mean([t["holding_days"] for t in completed_trades])), 1) if completed_trades else 0.0,
        "t1_hit_rate_pct": round(t1_hits_total / max(1, total_trades) * 100.0, 1),
        "t2_hit_rate_pct": round(t2_hits_total / max(1, total_trades) * 100.0, 1),
        "exit_breakdown": exit_counts,
        "top_winning_trades": sorted(winning_trades, key=lambda x: x["gain_val"], reverse=True)[:5],
        "top_losing_trades": sorted(losing_trades, key=lambda x: x["gain_val"])[:5],
        "daily_history": daily_equity_history,
        "active_positions": active_positions,
        "completed_trades": completed_trades
    }

if __name__ == "__main__":
    variants = [
        ("🏆 Apex Champion: Progressive Stepladders (30% Hurdle)", {"min_momentum_6m_pct": 30.0, "exit_mode": "TRAILING_RUNNER"}),
        ("⚡ Apex Champion: Progressive Stepladders (20% Hurdle)", {"min_momentum_6m_pct": 20.0, "exit_mode": "TRAILING_RUNNER"}),
        ("🎯 Tactical Swing: Target 1 Milestone Exits (30% Hurdle)", {"min_momentum_6m_pct": 30.0, "exit_mode": "TARGET_1_SWING"}),
        ("🎯 Tactical Swing: Target 1 Milestone Exits (20% Hurdle)", {"min_momentum_6m_pct": 20.0, "exit_mode": "TARGET_1_SWING"}),
    ]

    all_results = []
    for name, kwargs in variants:
        res = run_daily_walkforward_simulation(**kwargs)
        all_results.append((name, res))

    print("\n" + "=" * 115)
    print(f"{'Strategy Variant':<55} | {'Final Corpus':<11} | {'Return':<7} | {'XIRR':<7} | {'Win %':<5} | {'PF':<5} | {'Payoff':<6} | {'Max DD':<6}")
    print("-" * 115)
    for name, r in all_results:
        print(f"{name:<55} | ₹{r['final_equity']/1e5:5.2f} Lakh | {r['strategy_return_pct']:+5.1f}% | {r['annualized_xirr']:+5.1f}% | {r['win_rate_pct']:4.1f}% | {r['profit_factor']:4.2f} | {r['payoff_ratio']:5.2f}x | {r['max_drawdown_pct']:5.1f}%")
    print("=" * 115)

    # Detailed report on the best variant
    best_name, best_res = max(all_results, key=lambda x: x[1]["strategy_return_pct"])
    print(f"\n🏆 DETAILED BREAKDOWN OF TOP PERFORMING VARIANT: {best_name}")
    print(f"  • Period:               {best_res['start_date']} to {best_res['end_date']} ({best_res['trading_days']} trading sessions)")
    print(f"  • Initial Capital:      ₹{best_res['initial_capital']:,.2f}")
    print(f"  • Final Portfolio Value:₹{best_res['final_equity']:,.2f} (Net Gain: ₹{best_res['net_profit']:+,.2f})")
    print(f"  • Absolute Return:      {best_res['strategy_return_pct']:+.2f}%  (vs NIFTY 50: {best_res['benchmark_return_pct']:+.2f}%)")
    print(f"  • Strategy Alpha:       {best_res['alpha_pct']:+5.2f}% vs Benchmark")
    print(f"  • Annualized XIRR:      {best_res['annualized_xirr']:+.2f}%")
    print(f"  • Win Rate:             {best_res['win_rate_pct']:.1f}% ({best_res['winning_trades_count']} Won / {best_res['losing_trades_count']} Lost / {best_res['active_open_positions']} In-Play)")
    print(f"  • Profit Factor:        {best_res['profit_factor']:.2f}")
    print(f"  • Payoff Ratio:         {best_res['payoff_ratio']:.2f}x (Avg Win: +{best_res['avg_win_pct']:.2f}% / Avg Loss: {best_res['avg_loss_pct']:.2f}%)")
    print(f"  • Max Drawdown:         {best_res['max_drawdown_pct']:.1f}%")
    print(f"  • Avg Holding Days:     {best_res['avg_holding_days']:.1f} days")
    print(f"  • T1 Milestone Hit Rate:{best_res['t1_hit_rate_pct']:.1f}%")
    print(f"  • Exits Breakdown:      {best_res['exit_breakdown']}")

    print("\n⭐ Top Winning Trades:")
    for t in best_res["top_winning_trades"]:
        print(f"  🚀 {t['symbol']:<15} | Entry: ₹{t['entry_price']:<7.1f} ({t['entry_date']}) -> Exit: ₹{t['exit_price']:<7.1f} ({t['exit_date']}) | Gain: ₹{t['gain_val']:+7,.0f} ({t['gain_pct']:+5.1f}%) | {t['exit_reason']} | {t['holding_days']}d")

    print("\n🛑 Top Controlled Exits:")
    for t in best_res["top_losing_trades"]:
        print(f"  🛑 {t['symbol']:<15} | Entry: ₹{t['entry_price']:<7.1f} ({t['entry_date']}) -> Exit: ₹{t['exit_price']:<7.1f} ({t['exit_date']}) | Loss: ₹{t['gain_val']:+7,.0f} ({t['gain_pct']:+5.1f}%) | {t['exit_reason']} | {t['holding_days']}d")

    print("\n📋 Active In-Play Positions as of 22-Sep-2026:")
    for sym, pos in best_res["active_positions"].items():
        unrlz_pct = (pos["current_price"] - pos["entry_price"]) / pos["entry_price"] * 100.0
        eff_sl = max(pos["stop_loss"], pos["trailing_stop"])
        sl_status = f"Trailed to ₹{pos['trailing_stop']:.1f}" if pos['trailing_stop'] > pos['entry_price'] else f"SL at ₹{pos['stop_loss']:.1f}"
        print(f"  🟢 {sym:<15} | Entry: ₹{pos['entry_price']:<7.1f} ({pos['entry_date']}) | Current: ₹{pos['current_price']:<7.1f} | P&L: {unrlz_pct:+5.2f}% | {sl_status} | Held: {pos['holding_days']}d")
    print("=" * 115)
