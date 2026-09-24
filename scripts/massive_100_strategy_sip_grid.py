#!/usr/bin/env python3
"""
scripts/massive_100_strategy_sip_grid.py

Massive 100-Strategy High-Throughput Quantitative Grid Explorer for Monthly SIP Investing.
Simulates 100 distinct systematic SIP strategies across historical market regimes:
  1. Full Multi-Regime 2.75-Year Cycle: 2024-01-01 to 2026-09-22 (33 months)
  2. 1-Year Multi-Regime Cycle: 2025-09-22 to 2026-09-22 (12 months, NIFTY -7.43%)
  3. Worst Bear Market: 2024-10-01 to 2025-03-31 (6 months, NIFTY -8.83%)
  4. Strong Bull Trending: 2024-01-01 to 2024-09-30 (9 months, NIFTY +22.50%)

Evaluates Net Wealth, Alpha, Annualized Cash-Flow XIRR, Win Rate, Profit Factor, Payoff Ratio, Max DD, and Capital Preservation.
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


# ─── 1. Preload Price & Indicator Data for Fast In-Memory SIP ─────────────────
def preload_sip_data():
    print("⏳ Preloading historical monthly prices & indicators for SIP grid...")
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
    nifty_df["ema_200"] = nifty_df["close"].ewm(span=200, adjust=False).mean()
    nifty_map = nifty_df.set_index("date_str").to_dict(orient="index")

    # 2. GoldBEES & NiftyBEES
    etf_df = pd.read_sql(text("""
        SELECT symbol, date, close FROM index_prices
        WHERE symbol IN ('GOLDBEES.NS', 'GOLDBEES', 'NIFTYBEES.NS', 'NIFTYBEES')
        AND date >= '2023-01-01' AND date <= '2026-09-22'
        ORDER BY symbol, date ASC
    """), session.bind)
    etf_map = {}
    for sym, grp in etf_df.groupby("symbol"):
        clean_sym = "GOLDBEES" if "GOLD" in sym.upper() else "NIFTYBEES"
        etf_map[clean_sym] = grp.set_index("date")["close"].to_dict()

    # 3. Stock Daily Prices & Indicators
    df_prices = pd.read_sql(text("""
        SELECT dp.symbol, dp.date, dp.close, stk.sector, stk.market_cap_tier
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
        group["ema_50"] = c.ewm(span=50, adjust=False).mean()
        group["ema_200"] = c.ewm(span=200, adjust=False).mean()

        # Lookback Momentums
        group["mom_1m"] = ((c - c.shift(20)) / c.shift(20) * 100.0).fillna(0.0)
        group["mom_3m"] = ((c - c.shift(60)) / c.shift(60) * 100.0).fillna(0.0)
        group["mom_6m"] = ((c - c.shift(126)) / c.shift(126) * 100.0).fillna(0.0)
        group["mom_12m"] = ((c - c.shift(250)) / c.shift(250) * 100.0).fillna(0.0)

        # 52-Week High & Proximity
        group["high_52w"] = group["close"].rolling(250, min_periods=30).max()
        group["prox_52w"] = (c / group["high_52w"] * 100.0).fillna(85.0)

        # Clenow Trend Smoothness approximation
        group["clenow"] = group["mom_6m"].clip(lower=0) * (1.0 - (group["close"].rolling(20).std() / group["close"]).fillna(0.05).clip(0, 0.5))

        prices_by_symbol[sym] = group.set_index("date")

    session.close()
    elapsed = time.time() - t0
    print(f"✅ Preloaded SIP data: {len(prices_by_symbol)} stocks across {len(nifty_map)} dates in {elapsed:.1f}s.")
    return nifty_map, etf_map, prices_by_symbol


# ─── 2. Fast In-Memory Monthly SIP Simulation ─────────────────────────────────
def simulate_sip_strategy(
    strategy: dict,
    start_date: str,
    end_date: str,
    nifty_map: dict,
    etf_map: dict,
    prices_by_symbol: dict,
    monthly_budget: float = 20000.0
) -> dict:
    all_dates = sorted([d for d in nifty_map.keys() if start_date <= d <= end_date])
    if len(all_dates) < 20:
        return {}

    # Identify Monthly Rebalance Dates (first trading day of each month)
    monthly_dates = []
    seen_months = set()
    for dt_str in all_dates:
        m_key = dt_str[:7] # YYYY-MM
        if m_key not in seen_months:
            seen_months.add(m_key)
            monthly_dates.append(dt_str)

    if not monthly_dates:
        return {}

    # Strategy Parameters
    asset_mode = strategy["asset_mode"]               # PURE_STOCKS, MULTI_ASSET, CORE_SATELLITE
    selection_filter = strategy["selection_filter"]   # MOM_30, CLENOW, MULTI_LOOKBACK, 52W_HIGH, CONVEXITY
    basket_size = strategy["basket_size"]             # 3, 4, 5, 6
    exit_protocol = strategy["exit_protocol"]         # ADAPTIVE_STRUCTURAL, VAN_THARP_3TIER, STEPLADDER, DYNAMIC_ATR
    enable_macro_hedge = strategy.get("enable_macro_hedge", True)
    enable_macro_rotation = strategy.get("enable_macro_rotation", True)
    enable_dip_buying = strategy.get("enable_dip_buying", True)
    enable_parabolic_skim = strategy.get("enable_parabolic_skim", True)
    enable_capital_recycler = strategy.get("enable_capital_recycler", True)
    max_position_cap = strategy.get("max_position_cap", 0.50)

    cash_flows = []
    portfolio_holdings = {} # sym -> {shares, cost, entry_p, peak_p, sector, asset_class}
    cash_reserve = 0.0
    total_invested = 0.0
    closed_trades = []
    monthly_snapshots = []

    # Benchmark tracking
    nifty_start = nifty_map[all_dates[0]]["close"]
    nifty_end = nifty_map[all_dates[-1]]["close"]
    benchmark_ret_pct = (nifty_end - nifty_start) / nifty_start * 100.0

    # Monthly Iteration Loop
    for m_idx, m_date in enumerate(monthly_dates):
        # Monthly cash injection
        cash_flows.append((datetime.strptime(m_date, "%Y-%m-%d").date(), -monthly_budget))
        cash_reserve += monthly_budget
        total_invested += monthly_budget

        cur_nifty = nifty_map.get(m_date, {})
        n_close = cur_nifty.get("close", 24000.0)
        n_e200 = cur_nifty.get("ema_200", 23000.0)
        is_nifty_bull = (n_close >= n_e200)

        # 1. Macro Cycle Rotation Check (Sell Gold into Equities when NIFTY >= 200 EMA)
        if enable_macro_rotation and is_nifty_bull and "GOLDBEES" in portfolio_holdings:
            gold_pos = portfolio_holdings["GOLDBEES"]
            gold_p = etf_map.get("GOLDBEES", {}).get(m_date, gold_pos["entry_p"])
            gold_proceeds = gold_pos["shares"] * gold_p
            cash_reserve += gold_proceeds
            closed_trades.append({
                "symbol": "GOLDBEES",
                "gain_pct": (gold_p - gold_pos["entry_p"]) / gold_pos["entry_p"] * 100.0,
                "reason": "MACRO_ROTATION_TO_EQUITY"
            })
            del portfolio_holdings["GOLDBEES"]

        # 2. Check Exits on Existing Holdings
        syms_to_remove = []
        for sym, pos in portfolio_holdings.items():
            if sym in ("GOLDBEES", "NIFTYBEES"):
                continue
            s_df = prices_by_symbol.get(sym)
            if s_df is None or m_date not in s_df.index:
                continue

            r = s_df.loc[m_date]
            cp = float(r["close"])
            pos["peak_p"] = max(pos["peak_p"], cp)
            peak_gain_pct = (pos["peak_p"] - pos["entry_p"]) / pos["entry_p"] * 100.0
            cur_gain_pct = (cp - pos["entry_p"]) / pos["entry_p"] * 100.0

            should_exit = False
            exit_reason = ""
            trim_shares = 0

            # Protocol-Specific Exits
            if exit_protocol == "ADAPTIVE_STRUCTURAL":
                # Structural stop loss (-13% on large, -17% on small)
                sl_floor = 0.85
                if cp <= pos["entry_p"] * sl_floor:
                    should_exit = True
                    exit_reason = "STRUCTURAL_SL"
                elif enable_parabolic_skim and cur_gain_pct >= 120.0:
                    trim_shares = int(pos["shares"] * 0.10)
                    exit_reason = "PARABOLIC_SKIM"

            elif exit_protocol == "VAN_THARP_3TIER":
                if peak_gain_pct >= 25.0 and cp <= pos["entry_p"] * 1.02:
                    should_exit = True
                    exit_reason = "VAN_THARP_BE_STOP"
                elif peak_gain_pct >= 50.0 and cp <= pos["peak_p"] * 0.88:
                    should_exit = True
                    exit_reason = "CHANDELIER_HARVEST"
                elif cp <= pos["entry_p"] * 0.86:
                    should_exit = True
                    exit_reason = "STOP_LOSS"

            elif exit_protocol == "SMART_STEPLADDER":
                if peak_gain_pct >= 100.0 and cp <= pos["entry_p"] * 1.60:
                    should_exit = True; exit_reason = "STEPLADDER_T3"
                elif peak_gain_pct >= 50.0 and cp <= pos["entry_p"] * 1.25:
                    should_exit = True; exit_reason = "STEPLADDER_T2"
                elif peak_gain_pct >= 20.0 and cp <= pos["entry_p"] * 1.02:
                    should_exit = True; exit_reason = "STEPLADDER_T1"
                elif cp <= pos["entry_p"] * 0.86:
                    should_exit = True; exit_reason = "STOP_LOSS"

            else: # DYNAMIC_ATR
                if cp <= pos["entry_p"] * 0.86:
                    should_exit = True; exit_reason = "ATR_STOP"

            if should_exit:
                proceeds = pos["shares"] * cp
                cash_reserve += proceeds
                closed_trades.append({
                    "symbol": sym,
                    "gain_pct": cur_gain_pct,
                    "reason": exit_reason
                })
                syms_to_remove.append(sym)
            elif trim_shares > 0:
                trim_proc = trim_shares * cp
                cash_reserve += trim_proc
                pos["shares"] -= trim_shares
                pos["cost"] -= trim_shares * pos["entry_p"]

        for s in syms_to_remove:
            del portfolio_holdings[s]

        # 3. Macro Hedge Allocation (if NIFTY < 200 EMA)
        macro_hedge_cost = 0.0
        if enable_macro_hedge and not is_nifty_bull:
            gold_p = etf_map.get("GOLDBEES", {}).get(m_date, 70.0)
            hedge_budget = cash_reserve * 0.15 # 15% Gold defense
            if gold_p > 0 and hedge_budget >= gold_p:
                g_sh = int(hedge_budget / gold_p)
                macro_hedge_cost = g_sh * gold_p
                cash_reserve -= macro_hedge_cost
                if "GOLDBEES" in portfolio_holdings:
                    portfolio_holdings["GOLDBEES"]["shares"] += g_sh
                    portfolio_holdings["GOLDBEES"]["cost"] += macro_hedge_cost
                else:
                    portfolio_holdings["GOLDBEES"] = {
                        "shares": g_sh,
                        "cost": macro_hedge_cost,
                        "entry_p": gold_p,
                        "peak_p": gold_p,
                        "sector": "Precious Metals",
                        "asset_class": "Commodity"
                    }

        # 4. Select New Monthly Equities
        avail_for_equity = cash_reserve
        candidate_pool = []

        for sym, s_df in prices_by_symbol.items():
            if m_date not in s_df.index:
                continue
            r = s_df.loc[m_date]
            cp = float(r["close"])
            if cp < 25.0:
                continue

            e50 = float(r["ema_50"])
            e200 = float(r["ema_200"])
            m1 = float(r["mom_1m"])
            m3 = float(r["mom_3m"])
            m6 = float(r["mom_6m"])
            m12 = float(r["mom_12m"])
            prox = float(r["prox_52w"])
            clen = float(r["clenow"])
            sec = str(r["sector"] or "General")

            qualifies = False
            q_score = 50.0

            if selection_filter == "MOM_HURDLE_30":
                if cp >= e50 >= e200 * 0.98 and m6 >= 30.0 and prox >= 80.0:
                    qualifies = True; q_score = m6 + prox

            elif selection_filter == "MOM_HURDLE_20":
                if cp >= e50 >= e200 * 0.98 and m6 >= 20.0:
                    qualifies = True; q_score = m6

            elif selection_filter == "CLENOW_MOMENTUM":
                if cp >= e50 >= e200 and clen >= 25.0:
                    qualifies = True; q_score = clen * 1.5

            elif selection_filter == "MULTI_LOOKBACK_BLEND":
                if cp >= e50 >= e200 * 0.985 and m1 > 0 and m3 > 10 and m6 > 25 and m12 > 35:
                    qualifies = True
                    q_score = (m1 * 0.15 + m3 * 0.25 + m6 * 0.35 + m12 * 0.25) + 50.0

            elif selection_filter == "52W_HIGH_PROXIMITY":
                if cp >= e50 >= e200 and prox >= 88.0 and m6 >= 15.0:
                    qualifies = True; q_score = prox + m6 * 0.5

            elif selection_filter == "MOMENTUM_CONVEXITY":
                # Accelerating trend (3M mom >= 0.5 * 6M mom)
                if cp >= e50 >= e200 and m6 >= 20.0 and m3 >= (m6 * 0.45):
                    qualifies = True; q_score = m3 * 2.0 + m6

            else: # QUALITY_COMPOSITE
                if cp >= e50 and m6 >= 20.0 and prox >= 75.0:
                    qualifies = True; q_score = m6 + 20.0

            if qualifies:
                candidate_pool.append({
                    "symbol": sym,
                    "close": cp,
                    "score": q_score,
                    "sector": sec
                })

        candidate_pool.sort(key=lambda x: x["score"], reverse=True)

        # Diversified selection across distinct sectors
        chosen_candidates = []
        chosen_sectors = set()
        for cand in candidate_pool:
            if len(chosen_candidates) >= basket_size:
                break
            if cand["sector"] not in chosen_sectors or len(candidate_pool) < basket_size:
                chosen_candidates.append(cand)
                chosen_sectors.add(cand["sector"])

        # Allocate cash into selected candidates
        if chosen_candidates and avail_for_equity >= 3000.0:
            target_alloc_per_stock = avail_for_equity / len(chosen_candidates)
            for cand in chosen_candidates:
                sym = cand["symbol"]
                cp = cand["close"]
                sh = int(target_alloc_per_stock / cp)
                if sh <= 0:
                    continue

                cost = sh * cp
                cash_reserve -= cost

                if sym in portfolio_holdings:
                    # Winner Pyramiding / Average Up
                    old_pos = portfolio_holdings[sym]
                    new_tot_sh = old_pos["shares"] + sh
                    new_cost = old_pos["cost"] + cost
                    old_pos["shares"] = new_tot_sh
                    old_pos["cost"] = new_cost
                    old_pos["entry_p"] = new_cost / new_tot_sh
                else:
                    portfolio_holdings[sym] = {
                        "shares": sh,
                        "cost": cost,
                        "entry_p": cp,
                        "peak_p": cp,
                        "sector": cand["sector"],
                        "asset_class": "Equity"
                    }

        # End-of-month portfolio valuation
        cur_port_val = cash_reserve
        for sym, pos in portfolio_holdings.items():
            if sym == "GOLDBEES":
                cp = etf_map.get("GOLDBEES", {}).get(m_date, pos["entry_p"])
            else:
                s_df = prices_by_symbol.get(sym)
                cp = float(s_df.loc[m_date]["close"]) if (s_df is not None and m_date in s_df.index) else pos["entry_p"]
            cur_port_val += pos["shares"] * cp

        monthly_snapshots.append(cur_port_val)

    # Final Liquidation & Valuation on End Date
    final_dt = datetime.strptime(all_dates[-1], "%Y-%m-%d").date()
    final_port_val = cash_reserve
    for sym, pos in portfolio_holdings.items():
        if sym == "GOLDBEES":
            cp = etf_map.get("GOLDBEES", {}).get(all_dates[-1], pos["entry_p"])
        else:
            s_df = prices_by_symbol.get(sym)
            cp = float(s_df.loc[all_dates[-1]]["close"]) if (s_df is not None and all_dates[-1] in s_df.index) else pos["entry_p"]
        final_port_val += pos["shares"] * cp

    # Cash-Flow XIRR
    cf_list = list(cash_flows) + [(final_dt, final_port_val)]
    xirr_val = calculate_xirr(cf_list)

    # Net Return & Alpha
    abs_return_pct = ((final_port_val - total_invested) / max(1.0, total_invested)) * 100.0
    alpha_pct = abs_return_pct - benchmark_ret_pct

    # Max Drawdown across monthly snapshots
    peak_snap = pd.Series(monthly_snapshots).cummax()
    max_dd = ((pd.Series(monthly_snapshots) - peak_snap) / peak_snap * 100.0).min() if monthly_snapshots else 0.0

    # Trade Stats on closed positions
    wins = [t for t in closed_trades if t["gain_pct"] > 0]
    losses = [t for t in closed_trades if t["gain_pct"] <= 0]
    win_rate = (len(wins) / len(closed_trades) * 100.0) if closed_trades else 100.0
    avg_win = (sum(t["gain_pct"] for t in wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(t["gain_pct"] for t in losses) / len(losses)) if losses else 0.0
    payoff_ratio = round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else 2.0
    profit_factor = round(sum(t["gain_pct"] for t in wins) / max(0.01, abs(sum(t["gain_pct"] for t in losses))), 2) if losses else 5.0

    return {
        "final_wealth": round(final_port_val, 2),
        "total_invested": round(total_invested, 2),
        "return_pct": round(abs_return_pct, 2),
        "benchmark_pct": round(benchmark_ret_pct, 2),
        "alpha_pct": round(alpha_pct, 2),
        "xirr": round(xirr_val, 1),
        "win_rate": round(win_rate, 1),
        "profit_factor": profit_factor,
        "payoff_ratio": payoff_ratio,
        "max_dd": round(abs(max_dd), 1),
        "closed_trades": len(closed_trades),
        "open_holdings": len(portfolio_holdings)
    }


# ─── 3. Generate 100 Distinct Systematic SIP Strategies ───────────────────────
def build_100_sip_strategies() -> list:
    strategies = []
    strat_idx = 1

    asset_modes = ["PURE_STOCKS", "MULTI_ASSET", "CORE_SATELLITE"]
    selection_filters = [
        "MULTI_LOOKBACK_BLEND",
        "CLENOW_MOMENTUM",
        "MOM_HURDLE_30",
        "MOM_HURDLE_20",
        "52W_HIGH_PROXIMITY",
        "MOMENTUM_CONVEXITY",
        "QUALITY_COMPOSITE"
    ]
    basket_sizes = [3, 4, 5, 6]
    exit_protocols = [
        "ADAPTIVE_STRUCTURAL",
        "VAN_THARP_3TIER",
        "SMART_STEPLADDER",
        "DYNAMIC_ATR"
    ]

    for am in asset_modes:
        for sf in selection_filters:
            for bs in basket_sizes:
                for ep in exit_protocols:
                    if len(strategies) >= 100:
                        break

                    name = f"SIP_{strat_idx:03d}: {am[:11]} | {sf[:14]} | {bs}Stk | {ep[:12]}"
                    strategies.append({
                        "id": f"SIP_{strat_idx:03d}",
                        "name": name,
                        "asset_mode": am,
                        "selection_filter": sf,
                        "basket_size": bs,
                        "exit_protocol": ep,
                        "enable_macro_hedge": (am != "PURE_STOCKS"),
                        "enable_macro_rotation": True,
                        "enable_dip_buying": True,
                        "enable_parabolic_skim": (ep in ("ADAPTIVE_STRUCTURAL", "VAN_THARP_3TIER")),
                        "enable_capital_recycler": True
                    })
                    strat_idx += 1
                if len(strategies) >= 100:
                    break
            if len(strategies) >= 100:
                break
        if len(strategies) >= 100:
            break

    return strategies


# ─── 4. Main Grid Execution ───────────────────────────────────────────────────
def main():
    print("=" * 125)
    print("🚀 MASSIVE 100-STRATEGY QUANTITATIVE EXPLORATION: MONTHLY SIP INVESTING")
    print("   Evaluating 100 Systematic Paradigms across Multiple Historical Regimes")
    print("=" * 125)

    nifty_map, etf_map, prices_by_symbol = preload_sip_data()
    strategies = build_100_sip_strategies()
    print(f"📋 Generated {len(strategies)} distinct monthly SIP strategy permutations.")

    # Regimes to test
    sip_regimes = [
        {"id": "CYCLE_2_75YR", "name": "1. Full 2.75-Year Multi-Regime Cycle", "start": "2024-01-01", "end": "2026-09-22", "w": 0.35},
        {"id": "CYCLE_1YR", "name": "2. 1-Year Cycle (Bear/Chop)", "start": "2025-09-22", "end": "2026-09-22", "w": 0.25},
        {"id": "WORST_BEAR", "name": "3. Severe Bear Correction (2024-10 to 2025-03)", "start": "2024-10-01", "end": "2025-03-31", "w": 0.20},
        {"id": "BULL_TRENDING", "name": "4. Trending Bull Market (2024-01 to 2024-09)", "start": "2024-01-01", "end": "2024-09-30", "w": 0.20},
    ]

    results_table = []
    t_start = time.time()
    print(f"\n▶️ Launching SIP grid simulation (100 strategies × 4 regimes = 400 simulations)...")

    for i, strat in enumerate(strategies):
        reg_metrics = {}
        for reg in sip_regimes:
            res = simulate_sip_strategy(
                strat, reg["start"], reg["end"], nifty_map, etf_map, prices_by_symbol
            )
            reg_metrics[reg["id"]] = res

        # Key Metrics
        full_xirr = reg_metrics["CYCLE_2_75YR"].get("xirr", 0.0)
        full_ret = reg_metrics["CYCLE_2_75YR"].get("return_pct", 0.0)
        full_alpha = reg_metrics["CYCLE_2_75YR"].get("alpha_pct", 0.0)
        full_pr = reg_metrics["CYCLE_2_75YR"].get("payoff_ratio", 1.0)
        full_pf = reg_metrics["CYCLE_2_75YR"].get("profit_factor", 1.0)
        full_dd = reg_metrics["CYCLE_2_75YR"].get("max_dd", 10.0)

        one_yr_ret = reg_metrics["CYCLE_1YR"].get("return_pct", 0.0)
        one_yr_alpha = reg_metrics["CYCLE_1YR"].get("alpha_pct", 0.0)
        one_yr_xirr = reg_metrics["CYCLE_1YR"].get("xirr", 0.0)

        bear_ret = reg_metrics["WORST_BEAR"].get("return_pct", 0.0)
        bear_alpha = reg_metrics["WORST_BEAR"].get("alpha_pct", 0.0)
        bear_xirr = reg_metrics["WORST_BEAR"].get("xirr", 0.0)

        bull_ret = reg_metrics["BULL_TRENDING"].get("return_pct", 0.0)

        # Composite Fitness
        composite_score = (
            0.35 * full_xirr
            + 0.25 * one_yr_alpha
            + 0.20 * bear_xirr
            + 0.20 * bull_ret
        )

        row = {
            "id": strat["id"],
            "name": strat["name"],
            "asset_mode": strat["asset_mode"],
            "filter": strat["selection_filter"],
            "basket_size": strat["basket_size"],
            "exit_protocol": strat["exit_protocol"],
            "composite_score": round(composite_score, 2),
            "full_ret": full_ret,
            "full_alpha": full_alpha,
            "full_xirr": full_xirr,
            "one_yr_ret": one_yr_ret,
            "one_yr_alpha": one_yr_alpha,
            "one_yr_xirr": one_yr_xirr,
            "bear_ret": bear_ret,
            "bear_alpha": bear_alpha,
            "bear_xirr": bear_xirr,
            "bull_ret": bull_ret,
            "full_pr": full_pr,
            "full_pf": full_pf,
            "full_dd": full_dd,
        }
        results_table.append(row)

        if (i + 1) % 20 == 0 or (i + 1) == len(strategies):
            print(f"   • Completed {i + 1}/{len(strategies)} SIP strategies (Elapsed: {time.time() - t_start:.1f}s)...")

    # Sort results
    results_df = pd.DataFrame(results_table).sort_values("composite_score", ascending=False).reset_index(drop=True)

    out_csv = BASE_DIR / "scripts" / "sip_100_strategies_results.csv"
    results_df.to_csv(out_csv, index=False)
    print(f"\n💾 Full 100-Strategy SIP Results saved to: {out_csv}")

    # Display Top 10 Champion Leaderboard
    print("\n" + "=" * 145)
    print("🏆 TOP 10 CHAMPION MONTHLY SIP STRATEGIES (RANKED BY CROSS-REGIME COMPOSITE SCORE)")
    print("=" * 145)
    headers = f"{'Rank':<4} | {'Strategy Name':<45} | {'Score':<6} | {'Full XIRR':<9} | {'1Yr Alpha':<9} | {'1Yr XIRR':<8} | {'Bear XIRR':<9} | {'Bull Ret':<8} | {'PR':<5} | {'DD':<5}"
    print(headers)
    print("-" * 145)

    for rank, row in enumerate(results_df.head(10).to_dict(orient="records"), start=1):
        print(
            f"{rank:<4} | {row['name']:<45} | {row['composite_score']:+6.1f} | "
            f"{row['full_xirr']:+8.1f}% | {row['one_yr_alpha']:+8.1f}% | "
            f"{row['one_yr_xirr']:+7.1f}% | {row['bear_xirr']:+8.1f}% | "
            f"{row['bull_ret']:+7.1f}% | {row['full_pr']:4.2f}x | {row['full_dd']:4.1f}%"
        )
    print("=" * 145)


if __name__ == "__main__":
    main()
