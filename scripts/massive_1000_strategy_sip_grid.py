#!/usr/bin/env python3
"""
scripts/massive_1000_strategy_sip_grid.py

Ultra-Massive 1,000-Strategy High-Throughput Quantitative Grid Explorer for Monthly SIP Investing.
Evaluates exactly 1,000 systematic SIP strategies across 4 multi-year historical regimes:
  1. Full 2.75-Year Multi-Regime Cycle: 2024-01-01 to 2026-09-22
  2. 1-Year Multi-Regime Cycle: 2025-09-22 to 2026-09-22 (Bear & Choppy Correction)
  3. Severe Bear Correction: 2024-10-01 to 2025-03-31 (NIFTY -8.83%, Max DD -14.4%)
  4. Trending Bull Market: 2024-01-01 to 2024-09-30 (NIFTY +22.50%)

Total simulations: 1,000 strategies × 4 regimes = 4,000 full portfolio simulations.
Precomputes monthly rankings and asset prices for ultra-high throughput execution.
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


# ─── 1. Preload Market Data & Precompute Monthly Rankings ─────────────────────
def preload_and_precompute_sip_data():
    t0 = time.time()
    session = get_session()

    print("⏳ Preloading historical monthly prices & indicators for 1,000-strategy SIP grid...")

    # NIFTY benchmark
    nifty_rows = session.execute(text("""
        SELECT date, close
        FROM daily_prices
        WHERE symbol IN ('^NSEI', 'NIFTY 50', 'NIFTY')
        ORDER BY date ASC
    """)).fetchall()

    if not nifty_rows:
        nifty_rows = session.execute(text("""
            SELECT date, AVG(close) as close
            FROM daily_prices
            GROUP BY date
            ORDER BY date ASC
        """)).fetchall()

    nifty_df = pd.DataFrame([dict(r._mapping) for r in nifty_rows])
    nifty_df["ema_50"] = nifty_df["close"].ewm(span=50, adjust=False).mean()
    nifty_df["ema_200"] = nifty_df["close"].ewm(span=200, adjust=False).mean()
    nifty_map = nifty_df.set_index("date").to_dict(orient="index")

    # ETFs
    etf_rows = session.execute(text("""
        SELECT symbol, date, close
        FROM daily_prices
        WHERE symbol IN ('GOLDBEES', 'SILVERBEES', 'LIQUIDBEES')
        ORDER BY symbol, date ASC
    """)).fetchall()

    etf_map = {}
    for r in etf_rows:
        d = dict(r._mapping)
        etf_map.setdefault(d["symbol"], {})[d["date"]] = float(d["close"])

    # Stock Universe
    stock_rows = session.execute(text("""
        SELECT p.symbol, p.date, p.close, p.high, p.low, p.volume, s.sector
        FROM daily_prices p
        LEFT JOIN stocks s ON p.symbol = s.symbol
        WHERE p.symbol NOT IN ('^NSEI', 'NIFTY 50', 'NIFTY', 'GOLDBEES', 'SILVERBEES', 'LIQUIDBEES')
          AND p.date >= '2023-01-01'
        ORDER BY p.symbol, p.date ASC
    """)).fetchall()

    df_all = pd.DataFrame([dict(r._mapping) for r in stock_rows])

    symbol_records = {}
    filters = [
        "CLENOW_MOMENTUM",
        "CLENOW_HIGH_CONVICTION",
        "MOM_HURDLE_20",
        "MOM_HURDLE_30",
        "MOM_HURDLE_40",
        "MULTI_LOOKBACK_BLEND",
        "52W_HIGH_PROXIMITY",
        "SECTOR_LEAD_ALPHA"
    ]
    candidates_by_filter_and_month = {f: {} for f in filters}

    # Extract all distinct calendar dates sorted
    all_dates = sorted(df_all["date"].unique())
    # Monthly dates (first trading day of each month)
    monthly_dates = []
    seen_months = set()
    for d_str in all_dates:
        m_key = d_str[:7]
        if m_key not in seen_months and d_str >= "2024-01-01":
            seen_months.add(m_key)
            monthly_dates.append(d_str)

    # Process each symbol
    for sym, group in df_all.groupby("symbol"):
        group = group.sort_values("date").copy()
        if len(group) < 120:
            continue

        c = group["close"]
        group["ema_50"] = c.ewm(span=50, adjust=False).mean()
        group["ema_200"] = c.ewm(span=200, adjust=False).mean()

        hl = group["high"] - group["low"]
        hc = (group["high"] - c.shift(1)).abs()
        lc = (group["low"] - c.shift(1)).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        group["atr_14"] = tr.rolling(14, min_periods=14).mean().fillna(c * 0.025)

        group["mom_1m"] = ((c - c.shift(20)) / c.shift(20) * 100.0).fillna(0.0)
        group["mom_3m"] = ((c - c.shift(60)) / c.shift(60) * 100.0).fillna(0.0)
        group["mom_6m"] = ((c - c.shift(126)) / c.shift(126) * 100.0).fillna(0.0)
        group["mom_12m"] = ((c - c.shift(250)) / c.shift(250) * 100.0).fillna(0.0)

        group["high_52w"] = group["high"].rolling(250, min_periods=30).max()
        group["prox_52w"] = (c / group["high_52w"] * 100.0).fillna(85.0)

        # Clenow approximation
        sma_20 = c.rolling(20, min_periods=20).mean()
        std_20 = c.rolling(20, min_periods=20).std()
        bbw = ((std_20 * 4.0) / sma_20 * 100.0).fillna(10.0)
        group["clenow"] = (group["mom_3m"].clip(lower=0) * (1.0 - (bbw / 100.0).clip(0, 0.8))).fillna(0.0)

        rec = group.set_index("date").to_dict(orient="index")
        symbol_records[sym] = rec

        # Classify candidate eligibility for each monthly date
        for m_date in monthly_dates:
            if m_date not in rec:
                continue
            r = rec[m_date]
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

            # 1. CLENOW_MOMENTUM
            if cp >= e50 and clen >= 15.0 and m6 > 0:
                candidates_by_filter_and_month["CLENOW_MOMENTUM"].setdefault(m_date, []).append({
                    "symbol": sym, "close": cp, "score": clen, "sector": sec
                })

            # 2. CLENOW_HIGH_CONVICTION
            if cp >= e50 >= e200 and clen >= 30.0 and m6 >= 15.0:
                candidates_by_filter_and_month["CLENOW_HIGH_CONVICTION"].setdefault(m_date, []).append({
                    "symbol": sym, "close": cp, "score": clen + 10.0, "sector": sec
                })

            # 3. MOM_HURDLE_20
            if m6 >= 20.0 and cp >= e50:
                candidates_by_filter_and_month["MOM_HURDLE_20"].setdefault(m_date, []).append({
                    "symbol": sym, "close": cp, "score": m6, "sector": sec
                })

            # 4. MOM_HURDLE_30
            if m6 >= 30.0 and cp >= e50:
                candidates_by_filter_and_month["MOM_HURDLE_30"].setdefault(m_date, []).append({
                    "symbol": sym, "close": cp, "score": m6, "sector": sec
                })

            # 5. MOM_HURDLE_40
            if m6 >= 40.0 and cp >= e50:
                candidates_by_filter_and_month["MOM_HURDLE_40"].setdefault(m_date, []).append({
                    "symbol": sym, "close": cp, "score": m6, "sector": sec
                })

            # 6. MULTI_LOOKBACK_BLEND
            if cp >= e50 >= e200 * 0.98 and m1 > 0 and m3 > 5 and m6 > 15 and m12 > 25:
                blend = m1 * 0.15 + m3 * 0.25 + m6 * 0.35 + m12 * 0.25
                candidates_by_filter_and_month["MULTI_LOOKBACK_BLEND"].setdefault(m_date, []).append({
                    "symbol": sym, "close": cp, "score": blend, "sector": sec
                })

            # 7. 52W_HIGH_PROXIMITY
            if prox >= 90.0 and cp >= e50 and m6 >= 15.0:
                candidates_by_filter_and_month["52W_HIGH_PROXIMITY"].setdefault(m_date, []).append({
                    "symbol": sym, "close": cp, "score": prox + m6 * 0.2, "sector": sec
                })

            # 8. SECTOR_LEAD_ALPHA
            if cp >= e50 >= e200 and m6 >= 25.0:
                candidates_by_filter_and_month["SECTOR_LEAD_ALPHA"].setdefault(m_date, []).append({
                    "symbol": sym, "close": cp, "score": m6 + (prox * 0.1), "sector": sec
                })

    # Sort each candidate list by score descending
    for f in filters:
        for m_date in candidates_by_filter_and_month[f]:
            candidates_by_filter_and_month[f][m_date].sort(key=lambda x: x["score"], reverse=True)

    session.close()
    elapsed = time.time() - t0
    print(f"✅ Preloaded SIP data: {len(symbol_records)} stocks, {len(monthly_dates)} months, {len(filters)} filters in {elapsed:.1f}s.")
    return nifty_map, etf_map, symbol_records, candidates_by_filter_and_month, monthly_dates


# ─── 2. Core SIP Simulation Function ──────────────────────────────────────────
def simulate_sip_strategy(
    strategy: dict,
    start_date: str,
    end_date: str,
    nifty_map: dict,
    etf_map: dict,
    symbol_records: dict,
    candidates_by_filter_and_month: dict,
    all_monthly_dates: list,
    monthly_sip_amount: float = 100000.0
) -> dict:
    active_months = [d for d in all_monthly_dates if start_date <= d <= end_date]
    if len(active_months) < 3:
        return {}

    asset_mode = strategy["asset_mode"]
    selection_filter = strategy["selection_filter"]
    basket_size = strategy["basket_size"]
    exit_protocol = strategy["exit_protocol"]
    enable_macro_hedge = strategy.get("enable_macro_hedge", False)
    enable_dip_buying = strategy.get("enable_dip_buying", True)

    portfolio_holdings = {}
    cash_reserve = 0.0
    completed_trades = []
    portfolio_equity_history = []
    cash_flows = {}

    for m_idx, m_date in enumerate(active_months):
        cash_reserve += monthly_sip_amount
        dep_date = datetime.strptime(m_date, "%Y-%m-%d").date()
        cash_flows[dep_date] = cash_flows.get(dep_date, 0.0) - monthly_sip_amount

        cur_nifty = nifty_map.get(m_date, {})
        n_close = cur_nifty.get("close", 24000.0)
        n_e200 = cur_nifty.get("ema_200", 22000.0)
        is_nifty_bull = (n_close >= n_e200)

        # 1. Update existing positions & check exits
        syms_to_remove = []
        for sym, pos in portfolio_holdings.items():
            if pos.get("asset_class") == "Commodity":
                cp = etf_map.get(sym, {}).get(m_date, pos["entry_p"])
            else:
                s_rec = symbol_records.get(sym, {}).get(m_date)
                if s_rec is None:
                    continue
                cp = float(s_rec["close"])

            pos["peak_p"] = max(pos["peak_p"], cp)
            cur_gain_pct = (cp - pos["entry_p"]) / pos["entry_p"] * 100.0

            should_exit = False
            exit_reason = ""
            trim_shares = 0

            if pos.get("asset_class") == "Stock":
                e50 = float(s_rec["ema_50"])

                if exit_protocol == "VAN_THARP_3TIER":
                    if cp < e50 * 0.96 and cur_gain_pct < 10.0:
                        should_exit = True
                        exit_reason = "50EMA_STOP"
                    elif cur_gain_pct >= 25.0 and not pos.get("skim_25", False):
                        pos["skim_25"] = True
                        trim_shares = int(pos["shares"] * 0.20)
                    elif cur_gain_pct >= 50.0 and not pos.get("skim_50", False):
                        pos["skim_50"] = True
                        trim_shares = int(pos["shares"] * 0.25)
                    elif cur_gain_pct >= 100.0 and not pos.get("skim_100", False):
                        pos["skim_100"] = True
                        trim_shares = int(pos["shares"] * 0.33)

                elif exit_protocol == "SMART_STEPLADDER":
                    if cp < e50 * 0.97:
                        should_exit = True
                        exit_reason = "STEPLADDER_STOP"
                    elif cur_gain_pct >= 30.0 and not pos.get("ladder_1", False):
                        pos["ladder_1"] = True
                        trim_shares = int(pos["shares"] * 0.25)

                elif exit_protocol == "ADAPTIVE_STRUCTURAL":
                    if cp < e50 * 0.95:
                        should_exit = True
                        exit_reason = "STRUCTURAL_EXIT"

                elif exit_protocol == "DYNAMIC_ATR":
                    atr_val = float(s_rec["atr_14"])
                    trailing_sl = pos["peak_p"] - (3.5 * atr_val)
                    if cp <= trailing_sl:
                        should_exit = True
                        exit_reason = "ATR_STOP"

                elif exit_protocol == "TIME_DECAY_MOMENTUM":
                    m3_val = float(s_rec["mom_3m"])
                    if m3_val < -5.0 or cp < e50 * 0.97:
                        should_exit = True
                        exit_reason = "MOM_DECAY_EXIT"

            if should_exit:
                proceeds = pos["shares"] * cp
                cash_reserve += proceeds
                tot_pnl = proceeds - pos["cost"]
                completed_trades.append({
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

        # 2. Macro Hedge Defense (if applicable)
        if enable_macro_hedge and not is_nifty_bull:
            gold_p = etf_map.get("GOLDBEES", {}).get(m_date, 70.0)
            hedge_budget = cash_reserve * (0.15 if asset_mode == "TACTICAL_MACRO_90_10" else 0.20)
            if gold_p > 0 and hedge_budget >= gold_p:
                g_sh = int(hedge_budget / gold_p)
                macro_cost = g_sh * gold_p
                cash_reserve -= macro_cost
                if "GOLDBEES" in portfolio_holdings:
                    portfolio_holdings["GOLDBEES"]["shares"] += g_sh
                    portfolio_holdings["GOLDBEES"]["cost"] += macro_cost
                else:
                    portfolio_holdings["GOLDBEES"] = {
                        "shares": g_sh,
                        "cost": macro_cost,
                        "entry_p": gold_p,
                        "peak_p": gold_p,
                        "sector": "Precious Metals",
                        "asset_class": "Commodity"
                    }

        # 3. Select New Equities from Precomputed Candidate Pool
        avail_for_equity = cash_reserve
        candidate_pool = candidates_by_filter_and_month.get(selection_filter, {}).get(m_date, [])

        # Filter out existing holdings & apply sector concentration rule (max 2 per sector)
        selected_candidates = []
        sector_counts = {}
        for h in portfolio_holdings.values():
            sec = h.get("sector", "General")
            sector_counts[sec] = sector_counts.get(sec, 0) + 1

        for cand in candidate_pool:
            sym = cand["symbol"]
            sec = cand["sector"]
            if sym in portfolio_holdings:
                continue
            if sector_counts.get(sec, 0) >= 2:
                continue
            selected_candidates.append(cand)
            sector_counts[sec] = sector_counts.get(sec, 0) + 1
            if len(selected_candidates) >= basket_size:
                break

        if selected_candidates and avail_for_equity > 5000.0:
            alloc_per_stock = avail_for_equity / len(selected_candidates)
            for cand in selected_candidates:
                sym = cand["symbol"]
                cp = cand["close"]
                sh = int(alloc_per_stock / cp)
                if sh > 0:
                    cost = sh * cp
                    cash_reserve -= cost
                    portfolio_holdings[sym] = {
                        "shares": sh,
                        "cost": cost,
                        "entry_p": cp,
                        "peak_p": cp,
                        "sector": cand["sector"],
                        "asset_class": "Stock",
                        "entry_date": m_date
                    }

        # 4. End-of-month valuation
        holdings_val = 0.0
        for sym, pos in portfolio_holdings.items():
            if pos.get("asset_class") == "Commodity":
                cp = etf_map.get(sym, {}).get(m_date, pos["entry_p"])
            else:
                s_rec = symbol_records.get(sym, {}).get(m_date)
                cp = float(s_rec["close"]) if s_rec is not None else pos["peak_p"]
            holdings_val += pos["shares"] * cp

        total_val = holdings_val + cash_reserve
        portfolio_equity_history.append(total_val)

    # Wrap up final portfolio metrics
    final_eq = portfolio_equity_history[-1] if portfolio_equity_history else 0.0
    tot_invested = len(active_months) * monthly_sip_amount
    ret_pct = (final_eq - tot_invested) / tot_invested * 100.0

    # Benchmark return
    n_start = nifty_map.get(active_months[0], {}).get("close", 21700.0)
    n_end = nifty_map.get(active_months[-1], {}).get("close", 24000.0)
    benchmark_pct = (n_end - n_start) / n_start * 100.0
    alpha_pct = ret_pct - benchmark_pct

    # XIRR
    last_dt = datetime.strptime(active_months[-1], "%Y-%m-%d").date()
    cf_list = list(cash_flows.items()) + [(last_dt, final_eq)]
    xirr_val = calculate_xirr(cf_list)

    # Max Drawdown
    peak_eq = pd.Series(portfolio_equity_history).cummax()
    max_dd = ((pd.Series(portfolio_equity_history) - peak_eq) / peak_eq * 100.0).min()

    # Payoff Ratio
    wins = [t["gain_pct"] for t in completed_trades if t["gain_pct"] > 0]
    losses = [abs(t["gain_pct"]) for t in completed_trades if t["gain_pct"] <= 0]
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = np.mean(losses) if losses else 0.0
    pr = avg_win / avg_loss if avg_loss > 0 else 1.0

    return {
        "final_equity": round(final_eq, 2),
        "total_invested": round(tot_invested, 2),
        "return_pct": round(ret_pct, 2),
        "benchmark_pct": round(benchmark_pct, 2),
        "alpha_pct": round(alpha_pct, 2),
        "xirr": round(xirr_val, 1),
        "max_dd": round(abs(max_dd), 1),
        "payoff_ratio": round(pr, 2),
        "trades_count": len(completed_trades)
    }


# ─── 3. Build 1,000 Systematic SIP Strategies ─────────────────────────────────
def build_1000_sip_strategies():
    strategies = []
    strat_idx = 1

    asset_modes = [
        "PURE_STOCKS",
        "TACTICAL_MACRO_90_10",
        "TACTICAL_MACRO_80_20",
        "MOMENTUM_ROTATE_DYNAMIC",
        "MULTI_ASSET_BALANCED"
    ] # 5 asset allocation modes

    selection_filters = [
        "CLENOW_MOMENTUM",
        "CLENOW_HIGH_CONVICTION",
        "MOM_HURDLE_20",
        "MOM_HURDLE_30",
        "MOM_HURDLE_40",
        "MULTI_LOOKBACK_BLEND",
        "52W_HIGH_PROXIMITY",
        "SECTOR_LEAD_ALPHA"
    ] # 8 filters

    basket_sizes = [3, 4, 5, 6, 8] # 5 basket sizes

    exit_protocols = [
        "VAN_THARP_3TIER",
        "SMART_STEPLADDER",
        "ADAPTIVE_STRUCTURAL",
        "DYNAMIC_ATR",
        "TIME_DECAY_MOMENTUM"
    ] # 5 exit protocols
    # Total combinations = 5 * 8 * 5 * 5 = exactly 1,000 strategies!

    for am in asset_modes:
        for sf in selection_filters:
            for bs in basket_sizes:
                for ep in exit_protocols:
                    name = f"SIP_{strat_idx:04d}: {am[:11]} | {sf[:14]} | {bs}Stk | {ep[:12]}"
                    strategies.append({
                        "id": f"SIP_{strat_idx:04d}",
                        "name": name,
                        "asset_mode": am,
                        "selection_filter": sf,
                        "basket_size": bs,
                        "exit_protocol": ep,
                        "enable_macro_hedge": (am != "PURE_STOCKS"),
                        "enable_dip_buying": True,
                    })
                    strat_idx += 1

    return strategies


# ─── 4. Main Execution Grid ───────────────────────────────────────────────────
def main():
    print("=" * 125)
    print("🚀 ULTRA-MASSIVE 1,000-STRATEGY QUANTITATIVE EXPLORATION: MONTHLY SIP INVESTING")
    print("   Evaluating 1,000 Systematic Paradigms across Multiple Historical Regimes")
    print("=" * 125)

    nifty_map, etf_map, symbol_records, candidates_by_filter_and_month, monthly_dates = preload_and_precompute_sip_data()
    strategies = build_1000_sip_strategies()
    print(f"📋 Generated {len(strategies)} distinct systematic monthly SIP strategy permutations.")

    sip_regimes = [
        {"id": "CYCLE_2_75YR", "name": "1. Full 2.75-Year Multi-Regime Cycle", "start": "2024-01-01", "end": "2026-09-22", "w": 0.35},
        {"id": "CYCLE_1YR", "name": "2. 1-Year Cycle (Bear/Chop)", "start": "2025-09-22", "end": "2026-09-22", "w": 0.25},
        {"id": "WORST_BEAR", "name": "3. Severe Bear Correction (2024-10 to 2025-03)", "start": "2024-10-01", "end": "2025-03-31", "w": 0.20},
        {"id": "BULL_TRENDING", "name": "4. Trending Bull Market (2024-01 to 2024-09)", "start": "2024-01-01", "end": "2024-09-30", "w": 0.20},
    ]

    results_table = []
    t_start = time.time()
    print(f"\n▶️ Launching SIP grid simulation (1,000 strategies × 4 regimes = 4,000 simulations)...")

    for i, strat in enumerate(strategies):
        reg_metrics = {}
        for reg in sip_regimes:
            res = simulate_sip_strategy(
                strat, reg["start"], reg["end"],
                nifty_map, etf_map, symbol_records,
                candidates_by_filter_and_month, monthly_dates
            )
            reg_metrics[reg["id"]] = res

        full_xirr = reg_metrics["CYCLE_2_75YR"].get("xirr", 0.0)
        full_ret = reg_metrics["CYCLE_2_75YR"].get("return_pct", 0.0)
        full_alpha = reg_metrics["CYCLE_2_75YR"].get("alpha_pct", 0.0)
        full_pr = reg_metrics["CYCLE_2_75YR"].get("payoff_ratio", 1.0)
        full_dd = reg_metrics["CYCLE_2_75YR"].get("max_dd", 10.0)

        one_yr_ret = reg_metrics["CYCLE_1YR"].get("return_pct", 0.0)
        one_yr_alpha = reg_metrics["CYCLE_1YR"].get("alpha_pct", 0.0)
        one_yr_xirr = reg_metrics["CYCLE_1YR"].get("xirr", 0.0)

        bear_ret = reg_metrics["WORST_BEAR"].get("return_pct", 0.0)
        bear_alpha = reg_metrics["WORST_BEAR"].get("alpha_pct", 0.0)
        bear_xirr = reg_metrics["WORST_BEAR"].get("xirr", 0.0)

        bull_ret = reg_metrics["BULL_TRENDING"].get("return_pct", 0.0)

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
            "full_dd": full_dd,
        }
        results_table.append(row)

        if (i + 1) % 100 == 0 or (i + 1) == len(strategies):
            print(f"   • Completed {i + 1}/{len(strategies)} SIP strategies (Elapsed: {time.time() - t_start:.1f}s)...")

    results_df = pd.DataFrame(results_table).sort_values("composite_score", ascending=False).reset_index(drop=True)

    out_csv = BASE_DIR / "scripts" / "sip_1000_strategies_results.csv"
    results_df.to_csv(out_csv, index=False)
    print(f"\n💾 Full 1,000-Strategy SIP Results saved to: {out_csv}")

    print("\n" + "=" * 145)
    print("🏆 TOP 15 CHAMPION MONTHLY SIP STRATEGIES (RANKED BY CROSS-REGIME COMPOSITE SCORE)")
    print("=" * 145)
    headers = f"{'Rank':<4} | {'Strategy Name':<45} | {'Score':<6} | {'Full XIRR':<9} | {'1Yr Alpha':<9} | {'1Yr XIRR':<8} | {'Bear XIRR':<9} | {'Bull Ret':<8} | {'PR':<5} | {'DD':<5}"
    print(headers)
    print("-" * 145)

    for rank, row in enumerate(results_df.head(15).to_dict(orient="records"), start=1):
        print(
            f"{rank:<4} | {row['name']:<45} | {row['composite_score']:+6.1f} | "
            f"{row['full_xirr']:+8.1f}% | {row['one_yr_alpha']:+8.1f}% | "
            f"{row['one_yr_xirr']:+7.1f}% | {row['bear_xirr']:+8.1f}% | "
            f"{row['bull_ret']:+7.1f}% | {row['full_pr']:4.2f}x | {row['full_dd']:4.1f}%"
        )
    print("=" * 145)


if __name__ == "__main__":
    main()
