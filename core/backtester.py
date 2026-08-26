"""
Quantitative Strategy Backtesting Engine
- Multi-Engine Confluence Strategy
- EMA Golden Cross Trend Rider
- RSI Oversold Mean Reversion
- Volume Breakout Momentum
- Performance Analytics: Win Rate, Profit Factor, Sharpe, Max Drawdown, Equity Curve
"""
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


def run_backtest(
    symbol: str,
    strategy_name: str,
    session: Session,
    start_date: str = None,
    end_date: str = None,
    initial_capital: float = 100000.0,
    risk_per_trade_pct: float = 2.0,
) -> Dict:
    """
    Run quantitative backtest on historical OHLCV data.
    """
    # Fetch historical daily prices
    query = """
        SELECT date, open, high, low, close, volume
        FROM daily_prices
        WHERE symbol = :s
    """
    params = {"s": symbol}
    if start_date:
        query += " AND date >= :start"
        params["start"] = start_date
    if end_date:
        query += " AND date <= :end"
        params["end"] = end_date
    query += " ORDER BY date ASC"

    rows = session.execute(text(query), params).fetchall()
    if not rows or len(rows) < 60:
        return {"error": f"Insufficient historical data for {symbol} ({len(rows)} days). Minimum 60 days required."}

    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    # Compute Core Indicators
    close = df["close"]
    high = df["high"]
    low = df["low"]
    vol = df["volume"]

    # EMAs
    df["ema_9"] = close.ewm(span=9, adjust=False).mean()
    df["ema_21"] = close.ewm(span=21, adjust=False).mean()
    df["ema_50"] = close.ewm(span=50, adjust=False).mean()
    df["ema_200"] = close.ewm(span=200, adjust=False).mean()

    # RSI
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-10)
    df["rsi"] = 100 - (100 / (1 + rs))

    # MACD
    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema_12 - ema_26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # Bollinger Bands
    df["bb_mid"] = close.rolling(20).mean()
    df["bb_std"] = close.rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + 2 * df["bb_std"]
    df["bb_lower"] = df["bb_mid"] - 2 * df["bb_std"]

    # ATR
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    df["tr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr"] = df["tr"].rolling(14).mean()

    # Volume SMA
    df["vol_sma"] = vol.rolling(20).mean()

    df = df.dropna().copy()
    if df.empty or len(df) < 30:
        return {"error": f"Insufficient indicator data for {symbol}."}

    # Generate Strategy Buy/Sell Signals
    df["entry_signal"] = False
    df["exit_signal"] = False

    if strategy_name == "Multi-Engine Confluence":
        # Confluence: RSI > 50, EMA-9 > EMA-21, MACD Hist > 0, Vol > SMA
        df["entry_signal"] = (
            (df["rsi"] > 50) &
            (df["ema_9"] > df["ema_21"]) &
            (df["macd_hist"] > 0) &
            (df["volume"] > df["vol_sma"])
        )
        df["exit_signal"] = (df["rsi"] < 45) | (df["ema_9"] < df["ema_21"])

    elif strategy_name == "EMA Golden Cross Trend":
        # Golden cross with 200 EMA trend filter
        df["entry_signal"] = (
            (df["ema_9"] > df["ema_21"]) &
            (df["ema_9"].shift(1) <= df["ema_21"].shift(1)) &
            (df["close"] > df["ema_50"])
        )
        df["exit_signal"] = (df["ema_9"] < df["ema_21"])

    elif strategy_name == "RSI Oversold Mean Reversion":
        # RSI oversold bounce off lower Bollinger band
        df["entry_signal"] = (
            (df["rsi"] < 35) &
            (df["low"] <= df["bb_lower"] * 1.01)
        )
        df["exit_signal"] = (df["rsi"] > 65) | (df["close"] >= df["bb_upper"])

    elif strategy_name == "Volume Breakout Momentum":
        # 20-day high breakout with 1.5x volume surge
        high_20 = df["high"].rolling(20).max().shift(1)
        df["entry_signal"] = (
            (df["close"] > high_20) &
            (df["volume"] > 1.5 * df["vol_sma"])
        )
        df["exit_signal"] = (df["close"] < df["ema_21"])

    else:
        # Default: EMA Cross
        df["entry_signal"] = (df["ema_9"] > df["ema_21"]) & (df["ema_9"].shift(1) <= df["ema_21"].shift(1))
        df["exit_signal"] = (df["ema_9"] < df["ema_21"])

    # ── Simulate Trades ───────────────────────────────────────────────────────
    capital = initial_capital
    position = 0
    entry_price = 0.0
    entry_date = None
    stop_loss = 0.0
    target_price = 0.0
    trade_log = []
    equity_curve = []

    # Benchmark Buy & Hold
    first_close = df["close"].iloc[0]

    for current_date, row in df.iterrows():
        price = row["close"]
        atr = row["atr"] if not pd.isna(row["atr"]) else price * 0.02

        # Check exit if in position
        if position > 0:
            exit_trade = False
            exit_reason = ""
            actual_exit_price = price

            if price <= stop_loss:
                exit_trade = True
                exit_reason = "Stop Loss Hit"
                actual_exit_price = stop_loss
            elif price >= target_price:
                exit_trade = True
                exit_reason = "Target Hit (Take Profit)"
                actual_exit_price = target_price
            elif row["exit_signal"]:
                exit_trade = True
                exit_reason = "Signal Exit (Trend Reversal)"
                actual_exit_price = price

            if exit_trade:
                pnl = position * (actual_exit_price - entry_price)
                return_pct = ((actual_exit_price - entry_price) / entry_price) * 100
                capital += position * actual_exit_price
                holding_days = (current_date - entry_date).days

                trade_log.append({
                    "entry_date": entry_date.strftime("%Y-%m-%d"),
                    "exit_date": current_date.strftime("%Y-%m-%d"),
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(actual_exit_price, 2),
                    "shares": position,
                    "pnl": round(pnl, 2),
                    "return_pct": round(return_pct, 2),
                    "holding_days": max(1, holding_days),
                    "exit_reason": exit_reason,
                    "status": "WIN" if pnl > 0 else "LOSS",
                })
                position = 0

        # Check entry if not in position
        if position == 0 and row["entry_signal"]:
            entry_price = price
            entry_date = current_date
            stop_loss = entry_price - (2.0 * atr)
            target_price = entry_price + (3.5 * atr)

            risk_amount = capital * (risk_per_trade_pct / 100.0)
            risk_per_sh = max(0.1, entry_price - stop_loss)
            position = int(min(capital * 0.95 / entry_price, risk_amount / risk_per_sh))
            position = max(1, position)
            capital -= position * entry_price

        # Track Equity Curve Daily
        current_equity = capital + (position * price)
        benchmark_equity = initial_capital * (price / first_close)
        equity_curve.append({
            "date": current_date.strftime("%Y-%m-%d"),
            "strategy_equity": round(current_equity, 2),
            "benchmark_equity": round(benchmark_equity, 2),
            "strategy_return_pct": round((current_equity - initial_capital) / initial_capital * 100, 2),
            "benchmark_return_pct": round((benchmark_equity - initial_capital) / initial_capital * 100, 2),
        })

    # Close open position at end
    if position > 0:
        last_price = df["close"].iloc[-1]
        pnl = position * (last_price - entry_price)
        return_pct = ((last_price - entry_price) / entry_price) * 100
        capital += position * last_price
        trade_log.append({
            "entry_date": entry_date.strftime("%Y-%m-%d"),
            "exit_date": df.index[-1].strftime("%Y-%m-%d"),
            "entry_price": round(entry_price, 2),
            "exit_price": round(last_price, 2),
            "shares": position,
            "pnl": round(pnl, 2),
            "return_pct": round(return_pct, 2),
            "holding_days": max(1, (df.index[-1] - entry_date).days),
            "exit_reason": "Backtest Period End",
            "status": "WIN" if pnl > 0 else "LOSS",
        })

    final_equity = capital
    total_return_pct = ((final_equity - initial_capital) / initial_capital) * 100
    benchmark_return_pct = ((df["close"].iloc[-1] - first_close) / first_close) * 100

    # ── Performance Metrics ───────────────────────────────────────────────────
    total_trades = len(trade_log)
    winning_trades = [t for t in trade_log if t["pnl"] > 0]
    losing_trades = [t for t in trade_log if t["pnl"] <= 0]
    win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0

    gross_profit = sum(t["pnl"] for t in winning_trades)
    gross_loss = abs(sum(t["pnl"] for t in losing_trades))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)

    # Max Drawdown Calculation
    eq_series = pd.Series([e["strategy_equity"] for e in equity_curve])
    cum_max = eq_series.cummax()
    drawdown = (eq_series - cum_max) / cum_max * 100
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0

    # Sharpe Ratio
    daily_returns = eq_series.pct_change().dropna()
    mean_ret = daily_returns.mean()
    std_ret = daily_returns.std()
    sharpe_ratio = float((mean_ret / std_ret) * np.sqrt(252)) if std_ret > 0 else 0.0

    # Sortino Ratio (downside deviation only)
    downside = daily_returns[daily_returns < 0]
    downside_std = downside.std()
    sortino_ratio = float((mean_ret / downside_std) * np.sqrt(252)) if downside_std > 0 else 0.0

    avg_win_pct = float(np.mean([t["return_pct"] for t in winning_trades])) if winning_trades else 0.0
    avg_loss_pct = float(np.mean([t["return_pct"] for t in losing_trades])) if losing_trades else 0.0
    avg_holding_days = float(np.mean([t["holding_days"] for t in trade_log])) if trade_log else 0.0

    return {
        "symbol": symbol,
        "strategy_name": strategy_name,
        "start_date": df.index[0].strftime("%Y-%m-%d"),
        "end_date": df.index[-1].strftime("%Y-%m-%d"),
        "initial_capital": initial_capital,
        "final_equity": round(final_equity, 2),
        "net_profit": round(final_equity - initial_capital, 2),
        "total_return_pct": round(total_return_pct, 2),
        "benchmark_return_pct": round(benchmark_return_pct, 2),
        "alpha_pct": round(total_return_pct - benchmark_return_pct, 2),
        "total_trades": total_trades,
        "win_rate_pct": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "sharpe_ratio": round(sharpe_ratio, 2),
        "sortino_ratio": round(sortino_ratio, 2),
        "avg_win_pct": round(avg_win_pct, 2),
        "avg_loss_pct": round(avg_loss_pct, 2),
        "avg_holding_days": round(avg_holding_days, 1),
        "trade_log": trade_log,
        "equity_curve": equity_curve,
    }


AVAILABLE_STRATEGIES = [
    "Multi-Engine Confluence",
    "EMA Golden Cross Trend",
    "RSI Oversold Mean Reversion",
    "Volume Breakout Momentum",
]


def find_champion_strategy(symbol: str, session: Session, years: int = 3) -> Dict:
    """
    Run backtest on all strategies and find the #1 champion strategy with highest Risk-Adjusted Alpha.
    """
    start_date = (pd.Timestamp.now() - pd.DateOffset(years=years)).strftime("%Y-%m-%d")
    all_results = []

    for strat in AVAILABLE_STRATEGIES:
        res = run_backtest(symbol, strat, session, start_date=start_date, initial_capital=100000.0)
        if "error" not in res and res.get("total_trades", 0) > 0:
            score = (
                res["total_return_pct"] * 0.4 +
                res["win_rate_pct"] * 0.3 +
                max(0, res["sharpe_ratio"]) * 15 * 0.3
            )
            all_results.append({
                "strategy_name": strat,
                "score": round(score, 2),
                "total_return_pct": res["total_return_pct"],
                "benchmark_return_pct": res["benchmark_return_pct"],
                "alpha_pct": res["alpha_pct"],
                "win_rate_pct": res["win_rate_pct"],
                "profit_factor": res["profit_factor"],
                "max_drawdown_pct": res["max_drawdown_pct"],
                "sharpe_ratio": res["sharpe_ratio"],
                "sortino_ratio": res["sortino_ratio"],
                "total_trades": res["total_trades"],
                "avg_win_pct": res["avg_win_pct"],
                "avg_loss_pct": res["avg_loss_pct"],
            })

    if not all_results:
        return {}

    all_results.sort(key=lambda x: x["score"], reverse=True)
    champion = all_results[0]
    return {
        "champion": champion,
        "all_ranked": all_results,
        "years": years,
    }
