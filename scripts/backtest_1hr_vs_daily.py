"""
scripts/backtest_1hr_vs_daily.py
Empirical Quantitative Backtest & Comparative Alpha Study:
Pure Daily vs Pure 1-Hour vs Hybrid Dual-Timeframe (Daily Filter + 1-Hour Sniper Execution)

Tests on 8 liquid NSE equities over 1 full year (1,700+ hourly bars):
RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, SBIN, TATAMOTORS, BHARTIARTL
"""
import sys
import os
import math
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from pathlib import Path

# Setup Path & Windows UTF-8 stdout encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

SYMBOLS = [
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "SBIN.NS",
    "TATAMOTORS.NS",
    "BHARTIARTL.NS"
]

FRICTION_BPS = 15  # 0.15% round-trip (STT, exchange, slippage)
SLIPPAGE_RATE = 0.0015

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["Close"]
    h = df["High"]
    l = df["Low"]
    v = df["Volume"]

    # EMAs
    df["ema_9"] = c.ewm(span=9, adjust=False).mean()
    df["ema_21"] = c.ewm(span=21, adjust=False).mean()
    df["ema_50"] = c.ewm(span=50, adjust=False).mean()
    df["sma_20"] = c.rolling(window=20).mean()

    # RSI (14)
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0/14.0, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0/14.0, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi_14"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)

    # ATR (14)
    prev_close = c.shift(1)
    tr = pd.concat([
        h - l,
        (h - prev_close).abs(),
        (l - prev_close).abs()
    ], axis=1).max(axis=1)
    df["atr_14"] = tr.rolling(window=14).mean().bfill()

    # 20-period High / Low for breakouts
    df["high_20"] = h.rolling(window=20).max()
    df["low_20"] = l.rolling(window=20).min()
    df["vol_sma_20"] = v.rolling(window=20).mean()

    return df


def backtest_daily(df_daily: pd.DataFrame) -> dict:
    """
    Paradigm A: Pure Daily Swing Trading
    Signal: EMA 9 > EMA 21, Close > EMA 50, RSI > 50, Volume > 1.0x Vol SMA.
    Exit: Close < EMA 21 or Stop Loss (2.0 x ATR) or Target (3.5 x ATR).
    """
    df = compute_indicators(df_daily)
    trades = []
    in_pos = False
    entry_price = 0.0
    entry_idx = None
    stop_loss = 0.0
    target_price = 0.0

    for i in range(50, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i-1]

        if not in_pos:
            # Entry condition on daily close, enter on next day open (approximated as row Close)
            signal_buy = (
                row["Close"] > row["ema_50"] and
                row["ema_9"] > row["ema_21"] and
                prev_row["ema_9"] <= prev_row["ema_21"] and
                row["rsi_14"] >= 50 and
                row["Volume"] >= 0.8 * row["vol_sma_20"]
            )
            if signal_buy:
                in_pos = True
                entry_price = row["Close"] * (1.0 + SLIPPAGE_RATE)
                entry_idx = i
                atr = row["atr_14"]
                stop_loss = entry_price - (2.0 * atr)
                target_price = entry_price + (3.5 * atr)
        else:
            # Check exit
            curr_low = row["Low"]
            curr_high = row["High"]
            curr_close = row["Close"]

            exit_price = None
            exit_reason = None

            if curr_low <= stop_loss:
                exit_price = stop_loss * (1.0 - SLIPPAGE_RATE)
                exit_reason = "STOP_LOSS"
            elif curr_high >= target_price:
                exit_price = target_price * (1.0 - SLIPPAGE_RATE)
                exit_reason = "TARGET"
            elif curr_close < row["ema_21"]:
                exit_price = curr_close * (1.0 - SLIPPAGE_RATE)
                exit_reason = "EMA_CROSS"

            if exit_price is not None:
                pnl_pct = (exit_price - entry_price) / entry_price * 100.0 - (FRICTION_BPS / 100.0)
                bars_held = i - entry_idx
                trades.append({
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                    "bars_held": bars_held,
                    "exit_reason": exit_reason,
                    "win": pnl_pct > 0
                })
                in_pos = False

    return _summarize_trades(trades, timeframe="Daily")


def backtest_1hr_standalone(df_1h: pd.DataFrame) -> dict:
    """
    Paradigm B: Pure 1-Hour Trading
    Evaluates signals independently on 1-hour candles without daily context.
    Signal: Hourly EMA 9 > EMA 21, Close > EMA 50, RSI > 50, Vol > Vol SMA.
    Exit: Hourly Close < EMA 21 or Stop Loss (2.0 x Hourly ATR) or Target (3.5 x Hourly ATR).
    """
    df = compute_indicators(df_1h)
    trades = []
    in_pos = False
    entry_price = 0.0
    entry_idx = None
    stop_loss = 0.0
    target_price = 0.0

    for i in range(50, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i-1]

        if not in_pos:
            signal_buy = (
                row["Close"] > row["ema_50"] and
                row["ema_9"] > row["ema_21"] and
                prev_row["ema_9"] <= prev_row["ema_21"] and
                row["rsi_14"] >= 50 and
                row["Volume"] >= 0.8 * row["vol_sma_20"]
            )
            if signal_buy:
                in_pos = True
                entry_price = row["Close"] * (1.0 + SLIPPAGE_RATE)
                entry_idx = i
                atr = row["atr_14"]
                stop_loss = entry_price - (2.0 * atr)
                target_price = entry_price + (3.5 * atr)
        else:
            curr_low = row["Low"]
            curr_high = row["High"]
            curr_close = row["Close"]

            exit_price = None
            exit_reason = None

            if curr_low <= stop_loss:
                exit_price = stop_loss * (1.0 - SLIPPAGE_RATE)
                exit_reason = "STOP_LOSS"
            elif curr_high >= target_price:
                exit_price = target_price * (1.0 - SLIPPAGE_RATE)
                exit_reason = "TARGET"
            elif curr_close < row["ema_21"]:
                exit_price = curr_close * (1.0 - SLIPPAGE_RATE)
                exit_reason = "EMA_CROSS"

            if exit_price is not None:
                pnl_pct = (exit_price - entry_price) / entry_price * 100.0 - (FRICTION_BPS / 100.0)
                bars_held = i - entry_idx
                trades.append({
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                    "bars_held": bars_held,
                    "exit_reason": exit_reason,
                    "win": pnl_pct > 0
                })
                in_pos = False

    return _summarize_trades(trades, timeframe="1-Hour (Pure)")


def backtest_hybrid_mtf(df_daily: pd.DataFrame, df_1h: pd.DataFrame) -> dict:
    """
    Paradigm C: Hybrid Dual-Timeframe (Daily Filter + 1-Hour Sniper Execution)
    Rule 1 (Macro Filter): Daily Close > Daily 50 EMA and Daily RSI >= 45 (Only trade in secular uptrends).
    Rule 2 (1-Hour Trigger): Enter when 1-Hour RSI crosses above 48 and 1-Hour 9 EMA > 21 EMA.
    Rule 3 (1-Hour Dynamic SL): Stop-loss anchored to 1-Hour ATR (1.8x ATR), dynamic trailing SL after 1.5R.
    """
    df_d = compute_indicators(df_daily)
    df_h = compute_indicators(df_1h)

    # Align Daily dates to 1-Hour timestamps
    df_d["date_only"] = pd.to_datetime(df_d.index).date
    df_h["date_only"] = pd.to_datetime(df_h.index).date

    # Merge daily trend indicator into hourly data
    daily_map = df_d.set_index("date_only")[["Close", "ema_50", "rsi_14"]].to_dict(orient="index")

    trades = []
    in_pos = False
    entry_price = 0.0
    entry_idx = None
    stop_loss = 0.0
    target_price = 0.0
    highest_price = 0.0

    for i in range(50, len(df_h)):
        row = df_h.iloc[i]
        prev_row = df_h.iloc[i-1]
        dt = row["date_only"]

        daily_info = daily_map.get(dt)
        if not daily_info:
            continue

        daily_uptrend = (daily_info["Close"] > daily_info["ema_50"]) and (daily_info["rsi_14"] >= 45)

        if not in_pos:
            # Sniper entry: Must satisfy Daily uptrend AND 1-hour momentum trigger
            hourly_trigger = (
                row["ema_9"] > row["ema_21"] and
                prev_row["ema_9"] <= prev_row["ema_21"] and
                row["rsi_14"] >= 48 and
                row["Volume"] >= 0.9 * row["vol_sma_20"]
            )

            if daily_uptrend and hourly_trigger:
                in_pos = True
                entry_price = row["Close"] * (1.0 + SLIPPAGE_RATE)
                entry_idx = i
                highest_price = entry_price
                atr_1h = row["atr_14"]
                stop_loss = entry_price - (1.8 * atr_1h)
                target_price = entry_price + (4.0 * atr_1h)
        else:
            curr_low = row["Low"]
            curr_high = row["High"]
            curr_close = row["Close"]

            if curr_high > highest_price:
                highest_price = curr_high

            # Dynamic trailing stop-loss: If profit > 2.0R, move SL to breakeven + 1R
            risk_unit = entry_price - (entry_price - 1.8 * row["atr_14"])
            if (highest_price - entry_price) >= (2.0 * risk_unit):
                stop_loss = max(stop_loss, entry_price + (0.5 * risk_unit))

            exit_price = None
            exit_reason = None

            if curr_low <= stop_loss:
                exit_price = stop_loss * (1.0 - SLIPPAGE_RATE)
                exit_reason = "TRAILING_STOP" if stop_loss > entry_price else "STOP_LOSS"
            elif curr_high >= target_price:
                exit_price = target_price * (1.0 - SLIPPAGE_RATE)
                exit_reason = "TARGET"
            elif curr_close < row["ema_21"] and (curr_close - entry_price) < 0:
                # Early cut if hourly momentum breaks down before profit
                exit_price = curr_close * (1.0 - SLIPPAGE_RATE)
                exit_reason = "HOURLY_MOMENTUM_FAIL"

            if exit_price is not None:
                pnl_pct = (exit_price - entry_price) / entry_price * 100.0 - (FRICTION_BPS / 100.0)
                bars_held = i - entry_idx
                trades.append({
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                    "bars_held": bars_held,
                    "exit_reason": exit_reason,
                    "win": pnl_pct > 0
                })
                in_pos = False

    return _summarize_trades(trades, timeframe="Hybrid (Daily+1H)")


def _summarize_trades(trades: list, timeframe: str) -> dict:
    if not trades:
        return {
            "timeframe": timeframe,
            "total_trades": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "total_return_pct": 0.0,
            "avg_trade_pnl": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "avg_bars_held": 0.0,
            "win_loss_ratio": 0.0
        }

    df_tr = pd.DataFrame(trades)
    n = len(df_tr)
    wins = df_tr[df_tr["win"]]
    losses = df_tr[~df_tr["win"]]
    win_rate = (len(wins) / n) * 100.0 if n > 0 else 0.0

    gross_gains = wins["pnl_pct"].sum() if len(wins) > 0 else 0.0
    gross_losses = abs(losses["pnl_pct"].sum()) if len(losses) > 0 else 0.0
    pf = (gross_gains / gross_losses) if gross_losses > 0 else (99.0 if gross_gains > 0 else 0.0)

    # Equity curve and Max Drawdown
    equity = (1.0 + df_tr["pnl_pct"] / 100.0).cumprod()
    peak = equity.cummax()
    dd = (equity - peak) / peak * 100.0
    max_dd = abs(dd.min()) if len(dd) > 0 else 0.0

    tot_ret = (equity.iloc[-1] - 1.0) * 100.0 if len(equity) > 0 else 0.0
    avg_pnl = df_tr["pnl_pct"].mean()

    # Sharpe approximation
    std_pnl = df_tr["pnl_pct"].std()
    sharpe = (avg_pnl / std_pnl * math.sqrt(252 / (max(1, df_tr['bars_held'].mean()) if timeframe=='Daily' else (252*6 / max(1, df_tr['bars_held'].mean()))))) if std_pnl > 0 else 0.0

    avg_win = wins["pnl_pct"].mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses["pnl_pct"].mean()) if len(losses) > 0 else 1.0
    wl_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0

    return {
        "timeframe": timeframe,
        "total_trades": n,
        "win_rate_pct": round(win_rate, 1),
        "profit_factor": round(pf, 2),
        "total_return_pct": round(tot_ret, 2),
        "avg_trade_pnl": round(avg_pnl, 2),
        "max_drawdown_pct": round(max_dd, 1),
        "sharpe_ratio": round(sharpe, 2),
        "avg_bars_held": round(df_tr["bars_held"].mean(), 1),
        "win_loss_ratio": round(wl_ratio, 2)
    }


def run_comprehensive_study():
    print("=" * 80)
    print("  EMPIRICAL QUANTITATIVE BACKTEST: DAILY vs 1-HOUR vs HYBRID DUAL-TIMEFRAME")
    print("=" * 80)
    print(f"  Assets: {len(SYMBOLS)} Bluechips | Window: 1-Year (730d 1H / Daily)")
    print(f"  Execution Friction: {FRICTION_BPS} bps per trade | Slippage: {SLIPPAGE_RATE*100:.2f}%")
    print("=" * 80 + "\n")

    all_daily_results = []
    all_1h_results = []
    all_hybrid_results = []

    for sym in SYMBOLS:
        print(f"📥 Downloading data for {sym}...")
        tk = yf.Ticker(sym)
        df_1h = tk.history(period="1y", interval="1h")
        df_daily = tk.history(period="1y", interval="1d")

        if df_1h.empty or df_daily.empty:
            print(f"⚠️ Missing data for {sym}, skipping.")
            continue

        res_d = backtest_daily(df_daily)
        res_d["symbol"] = sym
        all_daily_results.append(res_d)

        res_h = backtest_1hr_standalone(df_1h)
        res_h["symbol"] = sym
        all_1h_results.append(res_h)

        res_hyb = backtest_hybrid_mtf(df_daily, df_1h)
        res_hyb["symbol"] = sym
        all_hybrid_results.append(res_hyb)

        print(f"  -> {sym:12s} | Daily: Win={res_d['win_rate_pct']}% Ret={res_d['total_return_pct']:+.1f}% PF={res_d['profit_factor']:.2f}")
        print(f"  -> {' ':12s} | 1H:    Win={res_h['win_rate_pct']}% Ret={res_h['total_return_pct']:+.1f}% PF={res_h['profit_factor']:.2f}")
        print(f"  -> {' ':12s} | Hybrid:Win={res_hyb['win_rate_pct']}% Ret={res_hyb['total_return_pct']:+.1f}% PF={res_hyb['profit_factor']:.2f}\n")

    # Aggregate summaries
    def _agg(results, label):
        df_res = pd.DataFrame(results)
        return {
            "Timeframe Model": label,
            "Total Trades": int(df_res["total_trades"].sum()),
            "Avg Win Rate": round(df_res["win_rate_pct"].mean(), 1),
            "Avg Profit Factor": round(df_res["profit_factor"].mean(), 2),
            "Avg Total Return": round(df_res["total_return_pct"].mean(), 1),
            "Avg Max Drawdown": round(df_res["max_drawdown_pct"].mean(), 1),
            "Avg Sharpe": round(df_res["sharpe_ratio"].mean(), 2),
            "Avg Win/Loss Ratio": round(df_res["win_loss_ratio"].mean(), 2),
        }

    summary = [
        _agg(all_daily_results, "1. Pure Daily (Baseline)"),
        _agg(all_1h_results, "2. Pure 1-Hour (Standalone)"),
        _agg(all_hybrid_results, "3. Hybrid Dual-Timeframe (Daily + 1H)")
    ]

    df_summary = pd.DataFrame(summary)
    print("=" * 85)
    print("  EXECUTIVE QUANTITATIVE RESULTS SUMMARY (ACROSS ALL 8 BLUECHIP EQUITIES)")
    print("=" * 85)
    print(df_summary.to_string(index=False))
    print("=" * 85 + "\n")

    return all_daily_results, all_1h_results, all_hybrid_results, summary


if __name__ == "__main__":
    run_comprehensive_study()
