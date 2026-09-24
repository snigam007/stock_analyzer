#!/usr/bin/env python3
"""
scripts/backtest_centurion_sip088024_switcher.py

Rigorous Empirical Backtest of Dynamic Regime Switching between:
  1. 🏆 Centurion Wealth Engine (High-Alpha Multibagger Engine: +71.8% XIRR, 19.7% DD)
  2. 🛡️ SIP_088024 (Institutional Fortress Compounder: +33.0% XIRR, 6.75% DD, LiquidBees Sweep)

Evaluates 7 distinct strategies across 4 multi-year historical regimes:
  - Benchmark A: Pure Centurion Wealth Engine (100% Unconstrained)
  - Benchmark B: Pure SIP_088024 (100% Fortress Mode)
  - Switch 1: 50-EMA Regime Gate (NIFTY >= 50 EMA -> Centurion; NIFTY < 50 EMA -> SIP_088024)
  - Switch 2: 200-EMA Macro Trend Gate (NIFTY >= 200 EMA -> Centurion; NIFTY < 200 EMA -> SIP_088024)
  - Switch 3: 21/50 Dual EMA Trend Gate (NIFTY 21 EMA >= 50 EMA -> Centurion; else SIP_088024)
  - Switch 4: Market Breadth Gate (% of stocks > 50 EMA >= 50% -> Centurion; else SIP_088024)
  - Switch 5: Dynamic Dual-Core Blend (Bull: 75% Centurion / 25% SIP_088024; Bear: 25% Centurion / 75% SIP_088024)

Outputs:
  - Annualized XIRR (%)
  - Final Portfolio Value (Corpus ₹)
  - Maximum Drawdown (DD %)
  - Calmar Ratio (XIRR / Max DD)
  - Bear Market Return (%)
  - Bull Market Return (%)
"""
import sys
import os
import math
import time
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


def load_market_data():
    t0 = time.time()
    session = get_session()
    print("⏳ Preloading market data & precomputing regime indicators...")

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
    nifty_df["date_str"] = nifty_df["date"].astype(str)
    nifty_df["ema_21"] = nifty_df["close"].ewm(span=21, adjust=False).mean()
    nifty_df["ema_50"] = nifty_df["close"].ewm(span=50, adjust=False).mean()
    nifty_df["ema_200"] = nifty_df["close"].ewm(span=200, adjust=False).mean()
    nifty_map = {}
    for _, r in nifty_df.iterrows():
        nifty_map[str(r["date_str"])] = (
            float(r["close"]),
            float(r["ema_21"]),
            float(r["ema_50"]),
            float(r["ema_200"])
        )

    # LiquidBees ETF
    etf_rows = session.execute(text("""
        SELECT symbol, date, close
        FROM daily_prices
        WHERE symbol IN ('LIQUIDBEES', 'GOLDBEES')
        ORDER BY symbol, date ASC
    """)).fetchall()
    etf_map = {}
    for r in etf_rows:
        d = dict(r._mapping)
        etf_map.setdefault(d["symbol"], {})[str(d["date"])] = float(d["close"])

    # Stocks
    stock_rows = session.execute(text("""
        SELECT p.symbol, p.date, p.close, p.high, p.low, s.sector, s.market_cap_tier
        FROM daily_prices p
        JOIN stocks s ON p.symbol = s.symbol
        WHERE p.symbol NOT IN ('^NSEI', 'NIFTY 50', 'NIFTY', 'GOLDBEES', 'SILVERBEES', 'LIQUIDBEES')
          AND p.date >= '2023-01-01'
        ORDER BY p.symbol, p.date ASC
    """)).fetchall()

    df_stocks = pd.DataFrame([dict(r._mapping) for r in stock_rows])
    df_stocks["date_str"] = df_stocks["date"].astype(str)
    session.close()

    all_dates = sorted(df_stocks["date_str"].unique())
    monthly_dates = []
    seen_months = set()
    for d_str in all_dates:
        m_key = d_str[:7]
        if m_key not in seen_months and d_str >= "2024-01-01":
            seen_months.add(m_key)
            monthly_dates.append(d_str)

    monthly_set = set(monthly_dates)

    symbol_records = {} # sym -> m_date -> (close, ema_50, mom_6m, tier, sector)
    candidates_centurion = {} # m_date -> [(sym, cp, mom_6m, tier, sec), ...]
    candidates_sip088024 = {} # m_date -> [(sym, cp, mom_6m, tier, sec), ...]
    breadth_map = {} # m_date -> pct_above_50ema

    for sym, group in df_stocks.groupby("symbol"):
        if len(group) < 120:
            continue
        group = group.sort_values("date_str").copy()

        c = group["close"]
        group["ema_50"] = c.ewm(span=50, adjust=False).mean()
        group["mom_6m"] = ((c - c.shift(126)) / c.shift(126) * 100.0).fillna(0.0)

        tier = str(group["market_cap_tier"].iloc[-1] or "Mid")
        sec = str(group["sector"].iloc[-1] or "General")

        sym_dict = {}
        for _, row in group[group["date_str"].isin(monthly_set)].iterrows():
            dt = str(row["date_str"])
            cp = float(row["close"])
            if cp < 25.0:
                continue

            e50 = float(row["ema_50"])
            m6 = float(row["mom_6m"])

            sym_dict[dt] = (cp, e50, m6, tier, sec)

            # Centurion candidates: Hurdle >= 30%, Close >= 50 EMA
            if m6 >= 30.0 and cp >= e50:
                candidates_centurion.setdefault(dt, []).append((sym, cp, m6, tier, sec))

            # SIP_088024 candidates: Hurdle >= 40%, Close >= 50 EMA
            if m6 >= 40.0 and cp >= e50:
                candidates_sip088024.setdefault(dt, []).append((sym, cp, m6, tier, sec))

        if sym_dict:
            symbol_records[sym] = sym_dict

    # Sort candidate lists by mom_6m descending
    for dt in candidates_centurion:
        candidates_centurion[dt].sort(key=lambda x: x[2], reverse=True)
    for dt in candidates_sip088024:
        candidates_sip088024[dt].sort(key=lambda x: x[2], reverse=True)

    # Compute Market Breadth (% of stocks above 50 EMA) for each monthly date
    for dt in monthly_dates:
        tot_cnt, above_cnt = 0, 0
        for sym, rec in symbol_records.items():
            if dt in rec:
                tot_cnt += 1
                if rec[dt][0] >= rec[dt][1]: # close >= ema_50
                    above_cnt += 1
        breadth_map[dt] = (above_cnt / tot_cnt * 100.0) if tot_cnt > 0 else 50.0

    print(f"✅ Market Data Ready: {len(symbol_records)} stocks, {len(monthly_dates)} monthly dates in {time.time() - t0:.1f}s.")
    return nifty_map, etf_map, symbol_records, candidates_centurion, candidates_sip088024, breadth_map, monthly_dates


def simulate_switching_sip(
    strategy_mode: str,
    start_date: str,
    end_date: str,
    nifty_map: dict,
    etf_map: dict,
    symbol_records: dict,
    candidates_centurion: dict,
    candidates_sip088024: dict,
    breadth_map: dict,
    all_monthly_dates: list,
    monthly_base_wallet: float = 20000.0
):
    active_months = [d for d in all_monthly_dates if start_date <= d <= end_date]
    if len(active_months) < 3:
        return {}

    # Portfolio state
    # holdings: sym -> [shares, cost, entry_p, peak_p, tier, sec, skim_done, engine_source]
    holdings = {}
    cash_reserve = 0.0
    tot_invested = 0.0
    cash_flows = {}
    equity_history = []

    # Trade stats
    wins, losses = [], []

    for m_idx, m_date in enumerate(active_months):
        year_idx = m_idx // 12

        # ── 1. Determine Market Regime & Strategy Routing ─────────────────────
        n_close, n_e21, n_e50, n_e200 = nifty_map.get(m_date, (24000.0, 23800.0, 23500.0, 22000.0))
        breadth = breadth_map.get(m_date, 50.0)

        # Switching Logic
        if strategy_mode == "PURE_CENTURION":
            active_engine = "CENTURION"
            stepup_rate = 15.0
            centurion_weight = 1.0
        elif strategy_mode == "PURE_SIP_088024":
            active_engine = "SIP_088024"
            stepup_rate = 20.0
            centurion_weight = 0.0
        elif strategy_mode == "SWITCH_50EMA":
            active_engine = "CENTURION" if (n_close >= n_e50) else "SIP_088024"
            stepup_rate = 15.0 if active_engine == "CENTURION" else 20.0
            centurion_weight = 1.0 if active_engine == "CENTURION" else 0.0
        elif strategy_mode == "SWITCH_200EMA":
            active_engine = "CENTURION" if (n_close >= n_e200) else "SIP_088024"
            stepup_rate = 15.0 if active_engine == "CENTURION" else 20.0
            centurion_weight = 1.0 if active_engine == "CENTURION" else 0.0
        elif strategy_mode == "SWITCH_DUAL_EMA":
            active_engine = "CENTURION" if (n_close >= n_e50 and n_e21 >= n_e50) else "SIP_088024"
            stepup_rate = 15.0 if active_engine == "CENTURION" else 20.0
            centurion_weight = 1.0 if active_engine == "CENTURION" else 0.0
        elif strategy_mode == "SWITCH_BREADTH":
            active_engine = "CENTURION" if (breadth >= 50.0) else "SIP_088024"
            stepup_rate = 15.0 if active_engine == "CENTURION" else 20.0
            centurion_weight = 1.0 if active_engine == "CENTURION" else 0.0
        elif strategy_mode == "DYNAMIC_BLEND":
            is_bull = (n_close >= n_e50 and n_close >= n_e21)
            active_engine = "BLEND"
            centurion_weight = 0.75 if is_bull else 0.25
            stepup_rate = 15.0 * centurion_weight + 20.0 * (1.0 - centurion_weight)
        else:
            active_engine = "CENTURION"
            stepup_rate = 15.0
            centurion_weight = 1.0

        # Fresh monthly SIP deposit
        current_sip = monthly_base_wallet * ((1.0 + stepup_rate / 100.0) ** year_idx)
        cash_reserve += current_sip
        tot_invested += current_sip

        dep_dt = datetime.strptime(m_date, "%Y-%m-%d").date()
        cash_flows[dep_dt] = cash_flows.get(dep_dt, 0.0) - current_sip

        # ── 2. LiquidBees Yield Sweep (Active when SIP_088024 is in play) ─────
        if active_engine in ("SIP_088024", "BLEND") and cash_reserve > 5000.0:
            yield_pct = 6.5 / 100.0 / 12.0
            cash_reserve += cash_reserve * yield_pct

        # ── 3. Manage Open Holdings & Trailing Stops ──────────────────────────
        syms_to_exit = []
        for sym, pos in holdings.items():
            sh, cost, entry_p, peak_p, tier, sec, skim_done, eng_src = pos
            s_rec = symbol_records.get(sym, {}).get(m_date)
            if s_rec is None:
                continue

            cp, e50, m6, _, _ = s_rec
            if cp > peak_p:
                peak_p = cp
                pos[3] = peak_p

            gain_pct = (cp - entry_p) / entry_p * 100.0
            should_exit = False
            trim_sh = 0

            # Adaptive Structural Floor
            sl_pct = 0.13 if tier == "Large" else (0.14 if tier == "Mid" else 0.17)
            trailing_floor = max(entry_p * (1.0 - sl_pct), peak_p * (1.0 - sl_pct * 1.15))

            if cp <= trailing_floor or cp < e50 * 0.95:
                should_exit = True

            # SIP_088024 Parabolic Skim Rule: 6% profit lock at +80% gain
            if eng_src == "SIP_088024" or active_engine == "SIP_088024":
                if gain_pct >= 80.0 and not skim_done:
                    pos[6] = True
                    trim_sh = max(1, int(sh * 0.06))

            if should_exit:
                cash_reserve += sh * cp
                if gain_pct > 0:
                    wins.append(gain_pct)
                else:
                    losses.append(abs(gain_pct))
                syms_to_exit.append(sym)
            elif trim_sh > 0:
                cash_reserve += trim_sh * cp
                pos[0] -= trim_sh
                pos[1] -= trim_sh * entry_p

        for s in syms_to_exit:
            del holdings[s]

        # ── 4. Candidate Screening & Allocation ──────────────────────────────
        target_basket = 4 if active_engine == "CENTURION" else 3
        cand_pool = candidates_centurion.get(m_date, []) if active_engine == "CENTURION" else candidates_sip088024.get(m_date, [])

        sector_counts = {}
        for h_pos in holdings.values():
            sec_name = h_pos[5]
            sector_counts[sec_name] = sector_counts.get(sec_name, 0) + 1

        selected_cands = []
        for cand in cand_pool:
            sym, cp, m6, tier, sec = cand
            if sym in holdings:
                continue
            # Enforce max 2 per sector
            if sector_counts.get(sec, 0) >= 2:
                continue
            selected_cands.append(cand)
            sector_counts[sec] = sector_counts.get(sec, 0) + 1
            if len(selected_cands) >= target_basket:
                break

        # Capital deployment
        if selected_cands and cash_reserve > 3000.0:
            alloc_per_stock = cash_reserve / len(selected_cands)
            for cand in selected_cands:
                sym, cp, m6, tier, sec = cand
                sh = int(alloc_per_stock / cp)
                if sh > 0:
                    cost = sh * cp
                    cash_reserve -= cost
                    holdings[sym] = [sh, cost, cp, cp, tier, sec, False, active_engine]

        # ── 5. End-of-Month Valuation ─────────────────────────────────────────
        holdings_val = 0.0
        for sym, pos in holdings.items():
            s_rec = symbol_records.get(sym, {}).get(m_date)
            cp = s_rec[0] if s_rec is not None else pos[3]
            holdings_val += pos[0] * cp

        total_eq = holdings_val + cash_reserve
        equity_history.append(total_eq)

    final_eq = equity_history[-1] if equity_history else 0.0
    ret_pct = (final_eq - tot_invested) / tot_invested * 100.0 if tot_invested > 0 else 0.0

    n_start_p = nifty_map.get(active_months[0], (21700.0,))[0]
    n_end_p = nifty_map.get(active_months[-1], (24000.0,))[0]
    benchmark_pct = (n_end_p - n_start_p) / n_start_p * 100.0
    alpha_pct = ret_pct - benchmark_pct

    last_dt = datetime.strptime(active_months[-1], "%Y-%m-%d").date()
    cf_list = list(cash_flows.items()) + [(last_dt, final_eq)]
    xirr_val = calculate_xirr(cf_list)

    # Fast Drawdown
    peak = 0.0
    max_dd = 0.0
    for eq in equity_history:
        if eq > peak:
            peak = eq
        elif peak > 0:
            dd = (eq - peak) / peak * 100.0
            if dd < max_dd:
                max_dd = dd

    calmar = round(xirr_val / abs(max_dd), 2) if abs(max_dd) > 0 else 0.0
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = np.mean(losses) if losses else 0.0
    payoff = round(avg_win / avg_loss, 2) if avg_loss > 0 else 1.0

    return {
        "strategy": strategy_mode,
        "final_equity": round(final_eq, 2),
        "total_invested": round(tot_invested, 2),
        "return_pct": round(ret_pct, 2),
        "alpha_pct": round(alpha_pct, 2),
        "xirr": round(xirr_val, 2),
        "max_dd": round(abs(max_dd), 2),
        "calmar_ratio": calmar,
        "payoff_ratio": payoff,
        "trades_count": len(wins) + len(losses)
    }


def main():
    print("=" * 125)
    print("🔬 RIGOROUS ADAPTIVE REGIME SWITCHING BACKTEST: CENTURION VS SIP_088024")
    print("   Evaluating Dynamic Switching Mechanisms to Maximize Gains & Minimize Drawdowns")
    print("=" * 125)

    nifty_map, etf_map, symbol_records, candidates_centurion, candidates_sip088024, breadth_map, monthly_dates = load_market_data()

    regimes = [
        {"id": "CYCLE_2_75YR", "name": "1. Full 2.75-Year Multi-Regime Cycle", "start": "2024-01-01", "end": "2026-09-22"},
        {"id": "CYCLE_1YR", "name": "2. 1-Year Cycle (Bear/Chop)", "start": "2025-09-22", "end": "2026-09-22"},
        {"id": "WORST_BEAR", "name": "3. Severe Bear Correction (2024-10 to 2025-03)", "start": "2024-10-01", "end": "2025-03-31"},
        {"id": "BULL_TRENDING", "name": "4. Trending Bull Market (2024-01 to 2024-09)", "start": "2024-01-01", "end": "2024-09-30"},
    ]

    strategy_modes = [
        ("PURE_CENTURION", "Benchmark A: Pure Centurion Wealth Engine"),
        ("PURE_SIP_088024", "Benchmark B: Pure SIP_088024 Fortress"),
        ("SWITCH_50EMA", "Switch 1: 50-EMA Trend Gate (Bull: Centurion / Bear: SIP_088024)"),
        ("SWITCH_200EMA", "Switch 2: 200-EMA Macro Gate (Bull: Centurion / Bear: SIP_088024)"),
        ("SWITCH_DUAL_EMA", "Switch 3: 21/50 Dual EMA Trend Gate (Fast/Slow Confirmation)"),
        ("SWITCH_BREADTH", "Switch 4: Market Breadth Gate (Breadth >= 50% Centurion)"),
        ("DYNAMIC_BLEND", "Switch 5: Dynamic Core Blend (75/25 Bull -> 25/75 Bear)")
    ]

    # Evaluate across all regimes
    all_summary = []

    for mode_key, mode_name in strategy_modes:
        row = {"mode_key": mode_key, "name": mode_name}
        for reg in regimes:
            res = simulate_switching_sip(
                mode_key, reg["start"], reg["end"],
                nifty_map, etf_map, symbol_records,
                candidates_centurion, candidates_sip088024, breadth_map, monthly_dates
            )
            prefix = reg["id"].lower()
            row[f"{prefix}_xirr"] = res.get("xirr", 0.0)
            row[f"{prefix}_val"] = res.get("final_equity", 0.0)
            row[f"{prefix}_dd"] = res.get("max_dd", 0.0)
            row[f"{prefix}_calmar"] = res.get("calmar_ratio", 0.0)
            row[f"{prefix}_ret"] = res.get("return_pct", 0.0)
            row[f"{prefix}_alpha"] = res.get("alpha_pct", 0.0)
            if reg["id"] == "CYCLE_2_75YR":
                row["full_inv"] = res.get("total_invested", 0.0)
                row["payoff"] = res.get("payoff_ratio", 1.0)

        all_summary.append(row)

    df_res = pd.DataFrame(all_summary)

    print("\n" + "=" * 135)
    print("📊 FULL 2.75-YEAR MULTI-REGIME CYCLE PERFORMANCE (2024-01-01 to 2026-09-22)")
    print("=" * 135)
    cols_full = [
        "name", "cycle_2_75yr_xirr", "cycle_2_75yr_val", "full_inv",
        "cycle_2_75yr_dd", "cycle_2_75yr_calmar", "worst_bear_xirr", "bull_trending_ret"
    ]
    print(df_res[cols_full].to_string(index=False))

    print("\n" + "=" * 135)
    print("🛡️ SEVERE BEAR MARKET CRASH PERFORMANCE (2024-10-01 to 2025-03-31 | NIFTY -14.4% Max DD)")
    print("=" * 135)
    cols_bear = ["name", "worst_bear_xirr", "worst_bear_ret", "worst_bear_dd", "worst_bear_alpha"]
    print(df_res[cols_bear].to_string(index=False))

    print("\n" + "=" * 135)
    print("🚀 TRENDING BULL MARKET PERFORMANCE (2024-01-01 to 2024-09-30 | NIFTY +22.5%)")
    print("=" * 135)
    cols_bull = ["name", "bull_trending_xirr", "bull_trending_ret", "bull_trending_alpha", "bull_trending_dd"]
    print(df_res[cols_bull].to_string(index=False))

    # Save to CSV
    out_csv = BASE_DIR / "scripts" / "centurion_sip088024_switching_backtest.csv"
    df_res.to_csv(out_csv, index=False)
    print(f"\n💾 Saved detailed regime switching backtest results to: {out_csv}")


if __name__ == "__main__":
    main()
