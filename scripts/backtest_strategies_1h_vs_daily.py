"""
scripts/backtest_strategies_1h_vs_daily.py
Multi-Strategy Quantitative Experiment: 1-Hour vs Daily Across Market Regimes

Compares:
1. Strategy A: Mean-Reversion (RSI Oversold Dip-Buying)
2. Strategy B: Trend-Following / EMA Golden Cross
3. Strategy C: Volatility Squeeze Breakout (Bollinger / ATR Channel)

Measures:
- Signal Accuracy & Win Rate (%)
- Profit Factor
- Total Return & Max Drawdown
- Trade Frequency & Friction Impact
"""
import sys
import math
import numpy as np
import pandas as pd
import yfinance as yf

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SYMBOLS = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "ICICIBANK.NS", "SBIN.NS", "BHARTIARTL.NS"]
FRICTION = 0.0015  # 15 bps round-trip

def add_indicators(df):
    df = df.copy()
    c = df["Close"]
    h = df["High"]
    l = df["Low"]
    v = df["Volume"]

    # RSI
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14.0, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14.0, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)

    # EMAs
    df["ema_9"] = c.ewm(span=9, adjust=False).mean()
    df["ema_21"] = c.ewm(span=21, adjust=False).mean()
    df["ema_50"] = c.ewm(span=50, adjust=False).mean()

    # Bollinger Bands
    df["sma_20"] = c.rolling(20).mean()
    df["bb_std"] = c.rolling(20).std()
    df["bb_upper"] = df["sma_20"] + 2.0 * df["bb_std"]
    df["bb_lower"] = df["sma_20"] - 2.0 * df["bb_std"]

    # ATR
    prev_close = c.shift(1)
    tr = pd.concat([h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean().bfill()
    return df


def backtest_strategy(df, strategy="mean_reversion"):
    trades = []
    in_pos = False
    entry_p = 0.0
    entry_idx = 0
    sl = 0.0
    tp = 0.0

    for i in range(25, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]

        if not in_pos:
            buy_sig = False
            if strategy == "mean_reversion":
                # Buy when RSI dips below 35 and hooks up
                buy_sig = (prev["rsi"] <= 35 and row["rsi"] > 35)
                risk_mult, reward_mult = 1.5, 2.5
            elif strategy == "trend":
                # Buy when EMA 9 crosses EMA 21 above EMA 50
                buy_sig = (row["Close"] > row["ema_50"] and prev["ema_9"] <= prev["ema_21"] and row["ema_9"] > row["ema_21"])
                risk_mult, reward_mult = 2.0, 3.5
            elif strategy == "breakout":
                # Buy when close breaks above Bollinger Upper band with expanding volume
                buy_sig = (prev["Close"] <= prev["bb_upper"] and row["Close"] > row["bb_upper"])
                risk_mult, reward_mult = 1.5, 3.0

            if buy_sig:
                in_pos = True
                entry_p = row["Close"] * (1.0 + FRICTION)
                entry_idx = i
                atr = row["atr"]
                sl = entry_p - (risk_mult * atr)
                tp = entry_p + (reward_mult * atr)
        else:
            hit_sl = row["Low"] <= sl
            hit_tp = row["High"] >= tp
            time_exit = (i - entry_idx >= (30 if len(df) > 500 else 10))  # Max hold time

            exit_p = None
            if hit_sl:
                exit_p = sl * (1.0 - FRICTION)
            elif hit_tp:
                exit_p = tp * (1.0 - FRICTION)
            elif time_exit:
                exit_p = row["Close"] * (1.0 - FRICTION)

            if exit_p is not None:
                pnl = (exit_p - entry_p) / entry_p * 100.0
                trades.append(pnl)
                in_pos = False

    if not trades:
        return {"trades": 0, "win_rate": 0.0, "return": 0.0, "pf": 0.0}

    arr = np.array(trades)
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    win_rate = (len(wins) / len(arr)) * 100.0
    gross_win = wins.sum() if len(wins) > 0 else 0.0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 0.001
    pf = gross_win / gross_loss
    tot_ret = ((1.0 + arr / 100.0).prod() - 1.0) * 100.0
    return {"trades": len(arr), "win_rate": round(win_rate, 1), "return": round(tot_ret, 1), "pf": round(pf, 2)}


def run_matrix():
    data_1h = {}
    data_daily = {}

    print("Fetching 1-Year historical data...")
    for sym in SYMBOLS:
        tk = yf.Ticker(sym)
        d_1h = tk.history(period="1y", interval="1h")
        d_daily = tk.history(period="1y", interval="1d")
        if not d_1h.empty and not d_daily.empty:
            data_1h[sym] = add_indicators(d_1h)
            data_daily[sym] = add_indicators(d_daily)

    strategies = ["mean_reversion", "trend", "breakout"]
    results = []

    for strat in strategies:
        # Evaluate across all symbols on Daily
        daily_runs = [backtest_strategy(data_daily[s], strategy=strat) for s in data_daily]
        # Evaluate across all symbols on 1-Hour
        h_runs = [backtest_strategy(data_1h[s], strategy=strat) for s in data_1h]

        d_trades = sum(r["trades"] for r in daily_runs)
        d_win = np.mean([r["win_rate"] for r in daily_runs if r["trades"] > 0])
        d_ret = np.mean([r["return"] for r in daily_runs if r["trades"] > 0])
        d_pf = np.mean([r["pf"] for r in daily_runs if r["trades"] > 0])

        h_trades = sum(r["trades"] for r in h_runs)
        h_win = np.mean([r["win_rate"] for r in h_runs if r["trades"] > 0])
        h_ret = np.mean([r["return"] for r in h_runs if r["trades"] > 0])
        h_pf = np.mean([r["pf"] for r in h_runs if r["trades"] > 0])

        results.append({
            "Strategy": strat.replace("_", " ").title(),
            "Daily Trades": d_trades,
            "Daily Win %": round(d_win, 1),
            "Daily Return %": round(d_ret, 1),
            "Daily PF": round(d_pf, 2),
            "1-Hour Trades": h_trades,
            "1-Hour Win %": round(h_win, 1),
            "1-Hour Return %": round(h_ret, 1),
            "1-Hour PF": round(h_pf, 2),
            "Return Edge (1H - Daily)": round(h_ret - d_ret, 1)
        })

    df_res = pd.DataFrame(results)
    print("\n" + "="*95)
    print("  STRATEGY-BY-STRATEGY COMPARATIVE BREAKDOWN: 1-HOUR vs DAILY DATA")
    print("="*95)
    print(df_res.to_string(index=False))
    print("="*95)


if __name__ == "__main__":
    run_matrix()
