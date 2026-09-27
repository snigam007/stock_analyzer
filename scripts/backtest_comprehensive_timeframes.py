"""
scripts/backtest_comprehensive_timeframes.py
Deep Quantitative Comparison of All 4 Timeframes:
1-Hour vs Daily vs Weekly vs Monthly (+ Multi-Timeframe Confluence)

Evaluates:
1. Standalone Single-Timeframe Performance across 1-Hour, Daily, Weekly, Monthly
2. Timeframe-Appropriate Indicator Calibration (e.g., Faber 10-Month Rule, Weinstein 30-Week Stage Analysis, Daily Swing, 1H Intraday Momentum)
3. Multi-Timeframe Hierarchical Confluence:
   - Macro Anchor (Monthly/Weekly Regime Filter)
   - Setup Trigger (Daily Swing Breakout / Pullback)
   - Sniper Execution (1-Hour Momentum / Stop Tightening)
4. Realistic Friction & Slippage Model (10 bps Monthly to 20 bps 1-Hour)
"""

import sys
import math
import numpy as np
import pandas as pd
import yfinance as yf

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SYMBOLS = [
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "ICICIBANK.NS",
    "SBIN.NS",
    "BHARTIARTL.NS",
    "SUNPHARMA.NS",
    "ITC.NS"
]

def resample_bars(df_daily: pd.DataFrame, freq: str) -> pd.DataFrame:
    df = df_daily.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    agg_rules = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }
    return df.resample(freq).agg(agg_rules).dropna(subset=["Close"])


def compute_metrics(pnl_list, bars_held_list, tf_name):
    if not pnl_list:
        return {
            "tf": tf_name,
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_return": 0.0,
            "max_dd": 0.0,
            "sharpe": 0.0,
            "avg_bars": 0.0
        }
    pnl = np.array(pnl_list)
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    win_rate = (len(wins) / len(pnl)) * 100.0
    gw = wins.sum() if len(wins) > 0 else 0.0
    gl = abs(losses.sum()) if len(losses) > 0 else 0.001
    pf = gw / gl

    # Equity curve & Max Drawdown
    equity = np.cumprod(1.0 + pnl / 100.0)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak * 100.0
    max_dd = abs(dd.min()) if len(dd) > 0 else 0.0
    tot_ret = (equity[-1] - 1.0) * 100.0

    # Annualization factor
    ann_factor = {"1-Hour": 252*6.25, "Daily": 252, "Weekly": 52, "Monthly": 12}.get(tf_name, 252)
    avg_bars = np.mean(bars_held_list) if bars_held_list else 1.0
    std = np.std(pnl)
    sharpe = (np.mean(pnl) / std * math.sqrt(ann_factor / max(1, avg_bars))) if std > 0 else 0.0

    return {
        "tf": tf_name,
        "trades": len(pnl),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(pf, 2),
        "total_return": round(tot_ret, 1),
        "max_dd": round(max_dd, 1),
        "sharpe": round(sharpe, 2),
        "avg_bars": round(avg_bars, 1)
    }


def test_timeframe_strategies():
    print("=" * 100)
    print("   DEEP CROSS-GRANULARITY BACKTEST: 1-HOUR vs DAILY vs WEEKLY vs MONTHLY")
    print("=" * 100)
    print(f"Testing {len(SYMBOLS)} NSE Equities across all sectors.")
    print("Using realistic exchange STT + statutory taxes + slippage: 1H (20 bps), 1D (15 bps), 1W (12 bps), 1M (10 bps)\n")

    # Fetch data
    # 1. 2-Year Unified Window (Allows direct comparison of 1-Hour against 1D, 1W, 1M)
    # 2. 10-Year Long Horizon (Evaluates statistical edge of 1D, 1W, 1M over complete bull/bear cycles)
    
    data_2y_1h = {}
    data_2y_1d = {}
    data_10y_1d = {}

    print("Fetching historical datasets from Yahoo Finance...")
    for sym in SYMBOLS:
        tk = yf.Ticker(sym)
        try:
            d1h = tk.history(period="2y", interval="1h")
            d2d = tk.history(period="2y", interval="1d")
            d10d = tk.history(period="10y", interval="1d")
            if not d1h.empty and not d2d.empty and not d10d.empty:
                data_2y_1h[sym] = d1h
                data_2y_1d[sym] = d2d
                data_10y_1d[sym] = d10d
                print(f"  ✓ {sym:12s} Loaded (2Y 1H: {len(d1h)} bars, 10Y Daily: {len(d10d)} bars)")
        except Exception as e:
            print(f"  ❌ {sym}: {e}")

    # =========================================================================
    # PART 1: 2-YEAR UNIFIED PERIOD (1-Hour vs Daily vs Weekly vs Monthly)
    # =========================================================================
    print("\n" + "=" * 100)
    print("  PART 1: 2-YEAR UNIFIED HORIZON (2024–2026) — DIRECT HEAD-TO-HEAD")
    print("=" * 100)
    
    results_2y = {"1-Hour": [], "Daily": [], "Weekly": [], "Monthly": []}

    for sym, d1h in data_2y_1h.items():
        d1d = data_2y_1d[sym]
        d1w = resample_bars(d1d, "W-FRI")
        d1m = resample_bars(d1d, "ME")

        # 1-Hour Trend & Momentum
        # Using 20/50 EMA cross + ATR stops
        c_1h = d1h["Close"]
        ema20_1h = c_1h.ewm(span=20, adjust=False).mean()
        ema50_1h = c_1h.ewm(span=50, adjust=False).mean()
        atr_1h = (d1h["High"] - d1h["Low"]).rolling(14).mean().bfill()
        
        pnl_1h, bars_1h = [], []
        in_pos = False
        ep, sl, tp, e_idx = 0, 0, 0, 0
        fric = 0.0020
        for i in range(50, len(d1h)):
            row = d1h.iloc[i]
            prev = d1h.iloc[i-1]
            if not in_pos:
                if ema20_1h.iloc[i] > ema50_1h.iloc[i] and ema20_1h.iloc[i-1] <= ema50_1h.iloc[i-1] and row["Close"] > ema20_1h.iloc[i]:
                    in_pos = True
                    ep = row["Close"] * (1 + fric/2)
                    sl = ep - 2.0 * atr_1h.iloc[i]
                    tp = ep + 3.5 * atr_1h.iloc[i]
                    e_idx = i
            else:
                hit_sl = row["Low"] <= sl
                hit_tp = row["High"] >= tp
                exit_sig = row["Close"] < ema20_1h.iloc[i]
                if hit_sl or hit_tp or exit_sig:
                    xp = sl if hit_sl else (tp if hit_tp else row["Close"])
                    xp = xp * (1 - fric/2)
                    ret = (xp - ep) / ep * 100.0 - (fric * 100)
                    pnl_1h.append(ret)
                    bars_1h.append(i - e_idx)
                    in_pos = False
        results_2y["1-Hour"].append(compute_metrics(pnl_1h, bars_1h, "1-Hour"))

        # Daily Trend (Swing 20/50 EMA + ATR)
        c_1d = d1d["Close"]
        ema20_1d = c_1d.ewm(span=20, adjust=False).mean()
        ema50_1d = c_1d.ewm(span=50, adjust=False).mean()
        atr_1d = (d1d["High"] - d1d["Low"]).rolling(14).mean().bfill()
        pnl_1d, bars_1d = [], []
        in_pos = False
        ep, sl, tp, e_idx = 0, 0, 0, 0
        fric = 0.0015
        for i in range(50, len(d1d)):
            row = d1d.iloc[i]
            if not in_pos:
                if ema20_1d.iloc[i] > ema50_1d.iloc[i] and ema20_1d.iloc[i-1] <= ema50_1d.iloc[i-1] and row["Close"] > ema20_1d.iloc[i]:
                    in_pos = True
                    ep = row["Close"] * (1 + fric/2)
                    sl = ep - 2.0 * atr_1d.iloc[i]
                    tp = ep + 3.5 * atr_1d.iloc[i]
                    e_idx = i
            else:
                hit_sl = row["Low"] <= sl
                hit_tp = row["High"] >= tp
                exit_sig = row["Close"] < ema20_1d.iloc[i]
                if hit_sl or hit_tp or exit_sig:
                    xp = sl if hit_sl else (tp if hit_tp else row["Close"])
                    xp = xp * (1 - fric/2)
                    ret = (xp - ep) / ep * 100.0 - (fric * 100)
                    pnl_1d.append(ret)
                    bars_1d.append(i - e_idx)
                    in_pos = False
        results_2y["Daily"].append(compute_metrics(pnl_1d, bars_1d, "Daily"))

        # Weekly Trend (10-Week / 30-Week Weinstein Stage 2 Breakout)
        c_1w = d1w["Close"]
        ema10_1w = c_1w.ewm(span=10, adjust=False).mean()
        ema30_1w = c_1w.ewm(span=30, adjust=False).mean()
        atr_1w = (d1w["High"] - d1w["Low"]).rolling(10).mean().bfill()
        pnl_1w, bars_1w = [], []
        in_pos = False
        ep, sl, tp, e_idx = 0, 0, 0, 0
        fric = 0.0012
        for i in range(30, len(d1w)):
            row = d1w.iloc[i]
            if not in_pos:
                if ema10_1w.iloc[i] > ema30_1w.iloc[i] and ema10_1w.iloc[i-1] <= ema30_1w.iloc[i-1] and row["Close"] > ema10_1w.iloc[i]:
                    in_pos = True
                    ep = row["Close"] * (1 + fric/2)
                    sl = ep - 2.0 * atr_1w.iloc[i]
                    tp = ep + 4.0 * atr_1w.iloc[i]
                    e_idx = i
            else:
                hit_sl = row["Low"] <= sl
                hit_tp = row["High"] >= tp
                exit_sig = row["Close"] < ema10_1w.iloc[i]
                if hit_sl or hit_tp or exit_sig:
                    xp = sl if hit_sl else (tp if hit_tp else row["Close"])
                    xp = xp * (1 - fric/2)
                    ret = (xp - ep) / ep * 100.0 - (fric * 100)
                    pnl_1w.append(ret)
                    bars_1w.append(i - e_idx)
                    in_pos = False
        results_2y["Weekly"].append(compute_metrics(pnl_1w, bars_1w, "Weekly"))

        # Monthly Trend (Mebane Faber 10-Month Momentum Rule)
        c_1m = d1m["Close"]
        sma10_1m = c_1m.rolling(10).mean()
        pnl_1m, bars_1m = [], []
        in_pos = False
        ep, e_idx = 0, 0
        fric = 0.0010
        for i in range(10, len(d1m)):
            row = d1m.iloc[i]
            prev = d1m.iloc[i-1]
            if not in_pos:
                if row["Close"] > sma10_1m.iloc[i] and prev["Close"] <= sma10_1m.iloc[i-1]:
                    in_pos = True
                    ep = row["Close"] * (1 + fric/2)
                    e_idx = i
            else:
                if row["Close"] < sma10_1m.iloc[i]:
                    xp = row["Close"] * (1 - fric/2)
                    ret = (xp - ep) / ep * 100.0 - (fric * 100)
                    pnl_1m.append(ret)
                    bars_1m.append(i - e_idx)
                    in_pos = False
        results_2y["Monthly"].append(compute_metrics(pnl_1m, bars_1m, "Monthly"))

    # Summary table for 2Y
    def summarize(res_dict):
        rows = []
        for tf, items in res_dict.items():
            df_i = pd.DataFrame(items)
            rows.append({
                "Timeframe": tf,
                "Total Trades": int(df_i["trades"].sum()),
                "Trades/Stock": round(df_i["trades"].mean(), 1),
                "Win Rate (%)": round(df_i["win_rate"].mean(), 1),
                "Profit Factor": round(df_i["profit_factor"].mean(), 2),
                "Avg Return (%)": round(df_i["total_return"].mean(), 1),
                "Max Drawdown (%)": round(df_i["max_dd"].mean(), 1),
                "Sharpe Ratio": round(df_i["sharpe"].mean(), 2),
                "Avg Holding Period": f"{df_i['avg_bars'].mean():.1f} bars"
            })
        return pd.DataFrame(rows)

    df_summary_2y = summarize(results_2y)
    print(df_summary_2y.to_string(index=False))

    # =========================================================================
    # PART 2: 10-YEAR MACRO CYCLE HORIZON (Daily vs Weekly vs Monthly)
    # =========================================================================
    print("\n" + "=" * 100)
    print("  PART 2: 10-YEAR MACRO CYCLE HORIZON (2016–2026: DAILY vs WEEKLY vs MONTHLY)")
    print("=" * 100)
    results_10y = {"Daily": [], "Weekly": [], "Monthly": []}

    for sym, d10d in data_10y_1d.items():
        d10w = resample_bars(d10d, "W-FRI")
        d10m = resample_bars(d10d, "ME")

        # Daily Trend (10 Years)
        c_1d = d10d["Close"]
        ema50_1d = c_1d.ewm(span=50, adjust=False).mean()
        ema200_1d = c_1d.ewm(span=200, adjust=False).mean()
        atr_1d = (d10d["High"] - d10d["Low"]).rolling(14).mean().bfill()
        pnl_1d, bars_1d = [], []
        in_pos = False
        ep, sl, tp, e_idx = 0, 0, 0, 0
        fric = 0.0015
        for i in range(200, len(d10d)):
            row = d10d.iloc[i]
            if not in_pos:
                if ema50_1d.iloc[i] > ema200_1d.iloc[i] and ema50_1d.iloc[i-1] <= ema200_1d.iloc[i-1] and row["Close"] > ema50_1d.iloc[i]:
                    in_pos = True
                    ep = row["Close"] * (1 + fric/2)
                    sl = ep - 2.5 * atr_1d.iloc[i]
                    tp = ep + 5.0 * atr_1d.iloc[i]
                    e_idx = i
            else:
                hit_sl = row["Low"] <= sl
                hit_tp = row["High"] >= tp
                exit_sig = row["Close"] < ema50_1d.iloc[i]
                if hit_sl or hit_tp or exit_sig:
                    xp = sl if hit_sl else (tp if hit_tp else row["Close"])
                    xp = xp * (1 - fric/2)
                    pnl_1d.append((xp - ep) / ep * 100.0 - (fric * 100))
                    bars_1d.append(i - e_idx)
                    in_pos = False
        results_10y["Daily"].append(compute_metrics(pnl_1d, bars_1d, "Daily"))

        # Weekly Trend (10 Years: 30-Week Stage Analysis)
        c_1w = d10w["Close"]
        ema10_1w = c_1w.ewm(span=10, adjust=False).mean()
        ema30_1w = c_1w.ewm(span=30, adjust=False).mean()
        atr_1w = (d10w["High"] - d10w["Low"]).rolling(10).mean().bfill()
        pnl_1w, bars_1w = [], []
        in_pos = False
        ep, sl, tp, e_idx = 0, 0, 0, 0
        fric = 0.0012
        for i in range(30, len(d10w)):
            row = d10w.iloc[i]
            if not in_pos:
                if ema10_1w.iloc[i] > ema30_1w.iloc[i] and ema10_1w.iloc[i-1] <= ema30_1w.iloc[i-1] and row["Close"] > ema10_1w.iloc[i]:
                    in_pos = True
                    ep = row["Close"] * (1 + fric/2)
                    sl = ep - 2.5 * atr_1w.iloc[i]
                    tp = ep + 5.0 * atr_1w.iloc[i]
                    e_idx = i
            else:
                hit_sl = row["Low"] <= sl
                hit_tp = row["High"] >= tp
                exit_sig = row["Close"] < ema10_1w.iloc[i]
                if hit_sl or hit_tp or exit_sig:
                    xp = sl if hit_sl else (tp if hit_tp else row["Close"])
                    xp = xp * (1 - fric/2)
                    pnl_1w.append((xp - ep) / ep * 100.0 - (fric * 100))
                    bars_1w.append(i - e_idx)
                    in_pos = False
        results_10y["Weekly"].append(compute_metrics(pnl_1w, bars_1w, "Weekly"))

        # Monthly Trend (10 Years: 10-Month SMA Rule)
        c_1m = d10m["Close"]
        sma10_1m = c_1m.rolling(10).mean()
        pnl_1m, bars_1m = [], []
        in_pos = False
        ep, e_idx = 0, 0
        fric = 0.0010
        for i in range(10, len(d10m)):
            row = d10m.iloc[i]
            prev = d10m.iloc[i-1]
            if not in_pos:
                if row["Close"] > sma10_1m.iloc[i] and prev["Close"] <= sma10_1m.iloc[i-1]:
                    in_pos = True
                    ep = row["Close"] * (1 + fric/2)
                    e_idx = i
            else:
                if row["Close"] < sma10_1m.iloc[i]:
                    xp = row["Close"] * (1 - fric/2)
                    pnl_1m.append((xp - ep) / ep * 100.0 - (fric * 100))
                    bars_1m.append(i - e_idx)
                    in_pos = False
        results_10y["Monthly"].append(compute_metrics(pnl_1m, bars_1m, "Monthly"))

    df_summary_10y = summarize(results_10y)
    print(df_summary_10y.to_string(index=False))

    # =========================================================================
    # PART 3: MULTI-TIMEFRAME CONFLUENCE (The Holy Grail)
    # Weekly Macro Trend Filter + Daily Pullback + 1-Hour Sniper Entry
    # =========================================================================
    print("\n" + "=" * 100)
    print("  PART 3: MULTI-TIMEFRAME CONFLUENCE SYSTEM (WEEKLY REGIME + DAILY SETUP + 1-HOUR SNIPER)")
    print("=" * 100)
    mtf_results = []
    
    for sym, d1h in data_2y_1h.items():
        d1d = data_2y_1d[sym]
        d1w = resample_bars(d1d, "W-FRI")
        
        # Weekly regime: Close > 30-Week EMA (Institutional Uptrend)
        w_ema30 = d1w["Close"].ewm(span=30, adjust=False).mean()
        w_bull = (d1w["Close"] > w_ema30).reindex(d1d.index, method="ffill").fillna(False)
        
        # Daily setup: RSI between 40 and 65 (Not overbought, recovering from dip)
        delta_d = d1d["Close"].diff()
        gain_d = delta_d.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        loss_d = (-delta_d.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
        rsi_d = (100 - (100 / (1 + gain_d / loss_d.replace(0, np.nan)))).fillna(50)
        d_setup = (rsi_d >= 40) & (rsi_d <= 65) & w_bull
        d_setup_1h = d_setup.reindex(d1h.index, method="ffill").fillna(False)
        
        # 1-Hour Sniper Entry: EMA 9 crosses above EMA 21 while d_setup is True
        c_1h = d1h["Close"]
        ema9_1h = c_1h.ewm(span=9, adjust=False).mean()
        ema21_1h = c_1h.ewm(span=21, adjust=False).mean()
        atr_1h = (d1h["High"] - d1h["Low"]).rolling(14).mean().bfill()
        
        pnl_mtf, bars_mtf = [], []
        in_pos = False
        ep, sl, tp, e_idx = 0, 0, 0, 0
        fric = 0.0020
        
        for i in range(30, len(d1h)):
            row = d1h.iloc[i]
            prev = d1h.iloc[i-1]
            if not in_pos:
                if d_setup_1h.iloc[i] and ema9_1h.iloc[i] > ema21_1h.iloc[i] and ema9_1h.iloc[i-1] <= ema21_1h.iloc[i-1]:
                    in_pos = True
                    ep = row["Close"] * (1 + fric/2)
                    sl = ep - 1.8 * atr_1h.iloc[i]   # Tighter stop loss enabled by 1H precision!
                    tp = ep + 4.5 * atr_1h.iloc[i]   # Higher reward:risk because riding weekly tailwind!
                    e_idx = i
            else:
                hit_sl = row["Low"] <= sl
                hit_tp = row["High"] >= tp
                exit_sig = ema9_1h.iloc[i] < ema21_1h.iloc[i]
                if hit_sl or hit_tp or exit_sig:
                    xp = sl if hit_sl else (tp if hit_tp else row["Close"])
                    xp = xp * (1 - fric/2)
                    ret = (xp - ep) / ep * 100.0 - (fric * 100)
                    pnl_mtf.append(ret)
                    bars_mtf.append(i - e_idx)
                    in_pos = False
                    
        mtf_results.append(compute_metrics(pnl_mtf, bars_mtf, "MTF-Confluence"))
        
    df_mtf_summary = summarize({"MTF-Confluence (W+D+1H)": mtf_results})
    print(df_mtf_summary.to_string(index=False))
    print("=" * 100 + "\n")


if __name__ == "__main__":
    test_timeframe_strategies()
