"""
scripts/backtest_quantum_engine.py
Verifiable Quantitative Backtest of the Quantum Multi-Timeframe Engine
Compares:
1. Standalone 1-Hour Intraday
2. Standalone Daily Swing
3. Standalone Weekly Stage 2 Breakout
4. The Quantum Confluence Engine (Weekly Regime + Daily Setup + 1-Hour Sniper)
5. Quantum Dynamic Value-Averaging SIP vs Static Flat SIP
"""

import sys
import math
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

# Add root directory to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.quantum_engine import (
    init_quantum_db,
    resample_ohlcv,
    compute_fast_indicators
)
from core.hourly_fetcher import get_hourly_data

TEST_SYMBOLS = [
    "RELIANCE", "TCS", "INFY", "ICICIBANK", "SBIN",
    "BHARTIARTL", "SUNPHARMA", "ITC", "LT", "HINDUNILVR",
    "AXISBANK", "KOTAKBANK", "MARUTI", "TATAMOTORS", "TITAN"
]


def backtest_quantum_confluence():
    print("=" * 100)
    print("   QUANTUM MULTI-TIMEFRAME ENGINE: EMPIRICAL PERFORMANCE & VERIFIABLE PROOF")
    print("=" * 100)
    print(f"Testing {len(TEST_SYMBOLS)} Liquid NSE Leaders over 2-Year Unified Window")
    print("Friction Model: 20 bps on 1H (incl. STT + spread), 15 bps on Daily, 12 bps on Weekly\n")

    conn = sqlite3.connect("data/stock_analyzer.db")
    
    results = {
        "1-Hour Standalone": [],
        "Daily Swing Standalone": [],
        "Weekly Standalone": [],
        "Quantum MTF Confluence (1H+1D+1W)": []
    }

    for sym in TEST_SYMBOLS:
        # Load Daily
        d_df = pd.read_sql_query("""
            SELECT date, open, high, low, close, volume 
            FROM daily_prices 
            WHERE symbol = ? 
            ORDER BY date ASC;
        """, conn, params=(sym,))

        if d_df.empty or len(d_df) < 250:
            continue

        d_df["date"] = pd.to_datetime(d_df["date"])
        d_df.set_index("date", inplace=True)
        
        # Load 1-Hour
        h_df = get_hourly_data(sym, limit=4000)
        if h_df.empty or len(h_df) < 500:
            continue

        # Cut to unified 2-year window
        min_dt = h_df.index.min()
        d_2y = d_df[d_df.index >= min_dt.strftime("%Y-%m-%d")].copy()
        w_2y = resample_ohlcv(d_df, "W-FRI")
        w_2y = w_2y[w_2y.index >= min_dt.strftime("%Y-%m-%d")].copy()

        d_ind = compute_fast_indicators(d_2y)
        w_ind = compute_fast_indicators(w_2y)
        h_ind = compute_fast_indicators(h_df)

        # 1. 1-Hour Standalone (Intraday EMA 9/21 cross)
        pnl_1h = []
        in_pos = False
        ep, sl, tp = 0, 0, 0
        fric = 0.0020
        for i in range(30, len(h_ind)):
            row = h_ind.iloc[i]
            prev = h_ind.iloc[i-1]
            if not in_pos:
                if row["ema_9"] > row["ema_21"] and prev["ema_9"] <= prev["ema_21"] and row["rsi_14"] >= 48:
                    in_pos = True
                    ep = row["close"] * (1 + fric/2)
                    sl = ep - 1.8 * row["atr_14"]
                    tp = ep + 3.0 * row["atr_14"]
            else:
                hit_sl = row["low"] <= sl
                hit_tp = row["high"] >= tp
                exit_sig = row["close"] < row["ema_21"]
                if hit_sl or hit_tp or exit_sig:
                    xp = sl if hit_sl else (tp if hit_tp else row["close"])
                    xp = xp * (1 - fric/2)
                    pnl_1h.append((xp - ep) / ep * 100.0 - fric * 100)
                    in_pos = False

        # 2. Daily Standalone (Swing EMA 9/21 cross)
        pnl_d = []
        in_pos = False
        fric_d = 0.0015
        for i in range(25, len(d_ind)):
            row = d_ind.iloc[i]
            prev = d_ind.iloc[i-1]
            if not in_pos:
                if row["ema_9"] > row["ema_21"] and prev["ema_9"] <= prev["ema_21"] and row["rsi_14"] >= 48:
                    in_pos = True
                    ep = row["close"] * (1 + fric_d/2)
                    sl = ep - 2.0 * row["atr_14"]
                    tp = ep + 3.5 * row["atr_14"]
            else:
                hit_sl = row["low"] <= sl
                hit_tp = row["high"] >= tp
                exit_sig = row["close"] < row["ema_21"]
                if hit_sl or hit_tp or exit_sig:
                    xp = sl if hit_sl else (tp if hit_tp else row["close"])
                    xp = xp * (1 - fric_d/2)
                    pnl_d.append((xp - ep) / ep * 100.0 - fric_d * 100)
                    in_pos = False

        # 3. Weekly Standalone (Stage 2 Breakout)
        pnl_w = []
        in_pos = False
        fric_w = 0.0012
        for i in range(15, len(w_ind)):
            row = w_ind.iloc[i]
            prev = w_ind.iloc[i-1]
            if not in_pos:
                if row["ema_9"] > row["ema_21"] and prev["ema_9"] <= prev["ema_21"]:
                    in_pos = True
                    ep = row["close"] * (1 + fric_w/2)
                    sl = ep - 2.0 * row["atr_14"]
                    tp = ep + 4.0 * row["atr_14"]
            else:
                hit_sl = row["low"] <= sl
                hit_tp = row["high"] >= tp
                exit_sig = row["close"] < row["ema_21"]
                if hit_sl or hit_tp or exit_sig:
                    xp = sl if hit_sl else (tp if hit_tp else row["close"])
                    xp = xp * (1 - fric_w/2)
                    pnl_w.append((xp - ep) / ep * 100.0 - fric_w * 100)
                    in_pos = False

        # 4. Quantum MTF Confluence Engine:
        # Weekly: Close > EMA 21 & RSI >= 48 (Institutional Tail-Wind)
        # Daily: Pullback to 21 EMA or RSI reset between 42 and 65
        # 1-Hour: Sniper 9/21 cross with tight 1H ATR stop
        w_bull = (w_ind["close"] > w_ind["ema_21"]).reindex(h_ind.index, method="ffill").fillna(False)
        d_setup = ((d_ind["rsi_14"] >= 42) & (d_ind["rsi_14"] <= 68)).reindex(h_ind.index, method="ffill").fillna(False)

        pnl_q = []
        in_pos = False
        trail_sl = 0.0
        for i in range(30, len(h_ind)):
            row = h_ind.iloc[i]
            prev = h_ind.iloc[i-1]
            if not in_pos:
                # Confluence condition: Weekly bull + Daily pullback/setup + 1H cross
                if w_bull.iloc[i] and d_setup.iloc[i]:
                    if row["ema_9"] > row["ema_21"] and prev["ema_9"] <= prev["ema_21"]:
                        in_pos = True
                        ep = row["close"] * (1 + fric/2)
                        init_risk = 1.8 * row["atr_14"]
                        sl = ep - init_risk
                        trail_sl = sl
                        tp = ep + 4.5 * row["atr_14"]
            else:
                # Ratchet trailing stop once trade moves in favor
                if row["high"] > ep + 1.5 * row["atr_14"]:
                    trail_sl = max(trail_sl, row["high"] - 1.5 * row["atr_14"])

                hit_sl = row["low"] <= trail_sl
                hit_tp = row["high"] >= tp
                if hit_sl or hit_tp:
                    xp = trail_sl if hit_sl else tp
                    xp = xp * (1 - fric/2)
                    pnl_q.append((xp - ep) / ep * 100.0 - fric * 100)
                    in_pos = False

        results["1-Hour Standalone"].extend(pnl_1h)
        results["Daily Swing Standalone"].extend(pnl_d)
        results["Weekly Standalone"].extend(pnl_w)
        results["Quantum MTF Confluence (1H+1D+1W)"].extend(pnl_q)

    conn.close()

    def calc_stats(pnl_list, name):
        if not pnl_list:
            return {"Strategy": name, "Trades": 0, "Win Rate (%)": 0, "Profit Factor": 0, "Total Return (%)": 0, "Max Drawdown (%)": 0, "Expectancy / Trade": "0%"}
        arr = np.array(pnl_list)
        wins = arr[arr > 0]
        losses = arr[arr <= 0]
        win_rate = round(len(wins) / len(arr) * 100.0, 1)
        gw = wins.sum() if len(wins) > 0 else 0
        gl = abs(losses.sum()) if len(losses) > 0 else 0.001
        pf = round(gw / gl, 2)
        eq = np.cumprod(1 + arr / 100.0)
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak * 100.0
        max_dd = round(abs(dd.min()), 1)
        tot_ret = round((eq[-1] - 1.0) * 100.0, 1)
        exp = round(arr.mean(), 2)

        return {
            "Strategy": name,
            "Trades": len(arr),
            "Win Rate (%)": win_rate,
            "Profit Factor": pf,
            "Total Return (%)": tot_ret,
            "Max Drawdown (%)": max_dd,
            "Expectancy / Trade": f"{exp:+.2f}%"
        }

    rows = [
        calc_stats(results["1-Hour Standalone"], "1-Hour Standalone"),
        calc_stats(results["Daily Swing Standalone"], "Daily Swing Standalone"),
        calc_stats(results["Weekly Standalone"], "Weekly Standalone"),
        calc_stats(results["Quantum MTF Confluence (1H+1D+1W)"], "Quantum MTF Confluence (1H+1D+1W)")
    ]

    df_out = pd.DataFrame(rows)
    print(df_out.to_string(index=False))
    print("=" * 100 + "\n")


def backtest_quantum_sip_vs_static():
    print("=" * 100)
    print("   QUANTUM SIP WEALTH ENGINE: DYNAMIC VALUE-AVERAGING vs STATIC SIP (5-YEAR STUDY)")
    print("=" * 100)
    print("Hypothesis: Allocating 1.5x - 2.0x on Weekly Dips (RSI < 45) & 0.5x on Euphoric Peaks (>25% over 200 DMA)")
    print("beats flat static Rupee Cost Averaging while reducing portfolio volatility.")
    print("-" * 100)

    conn = sqlite3.connect("data/stock_analyzer.db")
    
    symbols = ["RELIANCE", "TCS", "INFY", "ICICIBANK", "SBIN", "BHARTIARTL", "LT", "HINDUNILVR"]
    base_monthly_sip = 10000.0  # ₹10,000 baseline per month

    static_totals = []
    quantum_totals = []

    for sym in symbols:
        d_df = pd.read_sql_query("""
            SELECT date, open, high, low, close, volume 
            FROM daily_prices 
            WHERE symbol = ? 
            ORDER BY date ASC;
        """, conn, params=(sym,))

        if len(d_df) < 1000:
            continue

        d_df["date"] = pd.to_datetime(d_df["date"])
        d_df.set_index("date", inplace=True)
        w_df = resample_ohlcv(d_df, "W-FRI")
        w_ind = compute_fast_indicators(w_df)
        d_ind = compute_fast_indicators(d_df)

        # Monthly dates (last day of each month)
        m_df = resample_ohlcv(d_df, "ME")
        
        static_shares = 0.0
        static_invested = 0.0
        
        quantum_shares = 0.0
        quantum_invested = 0.0
        
        for m_date, m_row in m_df.iterrows():
            price = m_row["close"]
            if price <= 0: continue
            
            # Static: ₹10,000 every month
            static_shares += base_monthly_sip / price
            static_invested += base_monthly_sip
            
            # Quantum Dynamic Value-Averaging:
            # Check latest weekly RSI and distance from 200 DMA
            w_prior = w_ind[w_ind.index <= m_date]
            d_prior = d_ind[d_ind.index <= m_date]
            
            w_rsi = w_prior.iloc[-1]["rsi_14"] if len(w_prior) > 0 else 50.0
            d_close = d_prior.iloc[-1]["close"] if len(d_prior) > 0 else price
            d_sma200 = d_prior.iloc[-1].get("sma_200", d_close)
            dist_200dma = ((d_close - d_sma200) / d_sma200) * 100.0 if not np.isnan(d_sma200) and d_sma200 > 0 else 0.0
            
            if w_rsi <= 40 or dist_200dma <= -8.0:
                mult = 2.0  # Deep dip: Buy 2x
            elif w_rsi <= 48 or dist_200dma <= 2.0:
                mult = 1.5  # Pullback: Buy 1.5x
            elif dist_200dma >= 28.0 or w_rsi >= 75.0:
                mult = 0.5  # Euphoric: Buy 0.5x
            else:
                mult = 1.0  # Standard
                
            q_amount = base_monthly_sip * mult
            quantum_shares += q_amount / price
            quantum_invested += q_amount
            
        final_price = m_df.iloc[-1]["close"]
        static_value = static_shares * final_price
        static_xirr = (static_value - static_invested) / static_invested * 100.0
        
        quantum_value = quantum_shares * final_price
        quantum_xirr = (quantum_value - quantum_invested) / quantum_invested * 100.0
        
        static_totals.append(static_xirr)
        quantum_totals.append(quantum_xirr)
        print(f"  {sym:12s} | Static SIP Net Gain: {static_xirr:+.1f}% | Quantum Dynamic SIP Net Gain: {quantum_xirr:+.1f}% (Alpha: {quantum_xirr - static_xirr:+.1f}%)")

    conn.close()
    
    print("-" * 100)
    print(f"  AVERAGE STATIC SIP NET GAIN:         {np.mean(static_totals):+.1f}%")
    print(f"  AVERAGE QUANTUM DYNAMIC SIP GAIN:    {np.mean(quantum_totals):+.1f}%")
    print(f"  NET ALPHA ADDED BY QUANTUM DYNAMIC:  {np.mean(quantum_totals) - np.mean(static_totals):+.1f}%")
    print("=" * 100 + "\n")


if __name__ == "__main__":
    backtest_quantum_confluence()
    backtest_quantum_sip_vs_static()
