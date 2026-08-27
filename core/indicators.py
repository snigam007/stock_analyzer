"""
Technical Indicators Engine
Computes all 10 technical indicators using pure vectorized Pandas/NumPy operations
and saves them to the database.
Also computes trend patterns (↑↑↓↑), trend direction, and volume analysis.
Zero C-extension / JIT compilation build dependencies for maximum portability.
"""
import logging
import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Optional
import sys

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (
    RSI_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL, BB_PERIOD, BB_STD,
    ATR_PERIOD, ADX_PERIOD, CCI_PERIOD, STOCH_K, STOCH_D, OBV_SMOOTH,
    EMA_PERIODS, VOLUME_SPIKE_MULTIPLIER, TREND_LOOKBACK_DAYS
)
from db.database import get_global_engine, get_session, Stock, TechnicalIndicator

logger = logging.getLogger(__name__)


# ─── Trend Pattern Utilities ──────────────────────────────────────────────────
ARROW_UP = "↑"
ARROW_DOWN = "↓"
ARROW_FLAT = "→"


def build_trend_pattern(prices: pd.Series, lookback: int = TREND_LOOKBACK_DAYS) -> str:
    """
    Build a human-readable trend pattern string.
    Example: "↑↑↓↑↑↓↑↑↑↑" for last 10 days.
    """
    if prices is None or len(prices) < 2:
        return "—"

    changes = prices.pct_change().dropna().tail(lookback)
    pattern = ""
    for change in changes:
        if pd.isna(change):
            continue
        if change > 0.002:          # > 0.2% = up
            pattern += ARROW_UP
        elif change < -0.002:       # < -0.2% = down
            pattern += ARROW_DOWN
        else:
            pattern += ARROW_FLAT
    return pattern if pattern else "—"


def classify_trend_direction(prices: pd.Series, window: int = 20) -> tuple:
    """
    Classify overall trend direction and strength.
    Returns: (direction, strength 0-100)
    """
    if prices is None or len(prices) < window:
        return "SIDEWAYS", 50.0

    recent = prices.tail(window)

    # Linear regression slope
    x = np.arange(len(recent))
    y = recent.values
    if np.any(np.isnan(y)):
        return "SIDEWAYS", 50.0

    slope = np.polyfit(x, y, 1)[0]
    slope_pct = (slope / y[0]) * 100 if y[0] != 0 else 0

    # R² for strength
    y_pred = np.poly1d(np.polyfit(x, y, 1))(x)
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
    strength = abs(r2) * 100

    if slope_pct > 0.2:
        direction = "UP"
    elif slope_pct < -0.2:
        direction = "DOWN"
    else:
        direction = "SIDEWAYS"

    return direction, round(strength, 1)


# ─── Core Indicator Computation ───────────────────────────────────────────────
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all technical indicators for a DataFrame with OHLCV data using
    fast vectorized Pandas/NumPy operations without requiring external C extensions.
    Returns the enriched DataFrame with indicator columns added.
    """
    if df is None or df.empty or len(df) < 50:
        return df

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df.get("volume", pd.Series(index=df.index, dtype=float))

    # ── 1. RSI (Wilder's Smoothing) ───────────────────────────────────────────
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi_14"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)

    # ── 2. MACD ───────────────────────────────────────────────────────────────
    ema_fast = close.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=MACD_SLOW, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=MACD_SIGNAL, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # ── 3. Bollinger Bands ────────────────────────────────────────────────────
    bb_middle = close.rolling(window=BB_PERIOD).mean()
    bb_std = close.rolling(window=BB_PERIOD).std()
    df["bb_upper"] = bb_middle + (BB_STD * bb_std)
    df["bb_middle"] = bb_middle
    df["bb_lower"] = bb_middle - (BB_STD * bb_std)
    band_diff = df["bb_upper"] - df["bb_lower"]
    df["bb_width"] = (band_diff / bb_middle.replace(0, np.nan)) * 100.0
    df["bb_pct"] = (close - df["bb_lower"]) / band_diff.replace(0, np.nan)

    # ── 4. EMAs ───────────────────────────────────────────────────────────────
    for period in EMA_PERIODS:
        df[f"ema_{period}"] = close.ewm(span=period, adjust=False).mean()

    # ── 5. ATR & ADX / DMI ────────────────────────────────────────────────────
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / ATR_PERIOD, min_periods=ATR_PERIOD, adjust=False).mean()
    df["atr_14"] = atr

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm_series = pd.Series(plus_dm, index=df.index).ewm(alpha=1.0 / ADX_PERIOD, min_periods=ADX_PERIOD, adjust=False).mean()
    minus_dm_series = pd.Series(minus_dm, index=df.index).ewm(alpha=1.0 / ADX_PERIOD, min_periods=ADX_PERIOD, adjust=False).mean()
    df["di_plus"] = (plus_dm_series / atr.replace(0, np.nan)) * 100.0
    df["di_minus"] = (minus_dm_series / atr.replace(0, np.nan)) * 100.0
    di_sum = df["di_plus"] + df["di_minus"]
    dx = ((df["di_plus"] - df["di_minus"]).abs() / di_sum.replace(0, np.nan)) * 100.0
    df["adx"] = dx.ewm(alpha=1.0 / ADX_PERIOD, min_periods=ADX_PERIOD, adjust=False).mean().fillna(20.0)

    # ── 6. Stochastic Oscillator ──────────────────────────────────────────────
    lowest_low = low.rolling(window=STOCH_K).min()
    highest_high = high.rolling(window=STOCH_K).max()
    stoch_range = highest_high - lowest_low
    df["stoch_k"] = ((close - lowest_low) / stoch_range.replace(0, np.nan)) * 100.0
    df["stoch_d"] = df["stoch_k"].rolling(window=STOCH_D).mean()

    # ── 7. CCI ────────────────────────────────────────────────────────────────
    tp = (high + low + close) / 3.0
    sma_tp = tp.rolling(window=CCI_PERIOD).mean()
    mad = tp.rolling(window=CCI_PERIOD).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
    df["cci_20"] = (tp - sma_tp) / (0.015 * mad.replace(0, np.nan))

    # ── 8. OBV ────────────────────────────────────────────────────────────────
    if not volume.isna().all():
        direction = np.sign(close.diff()).fillna(0)
        df["obv"] = (direction * volume).cumsum()
        df["obv_sma"] = df["obv"].rolling(window=OBV_SMOOTH).mean()

    # ── 9. Volume Analysis ───────────────────────────────────────────────────
    if not volume.isna().all():
        df["volume_sma_20"] = volume.rolling(window=20).mean()
        df["volume_ratio"] = volume / df["volume_sma_20"].replace(0, np.nan)
        df["volume_spike"] = df["volume_ratio"] > VOLUME_SPIKE_MULTIPLIER

    # ── 10. Trend Pattern ─────────────────────────────────────────────────────
    df["trend_pattern"] = build_trend_pattern(close)
    trend_dir, trend_str = classify_trend_direction(close)
    df["trend_direction"] = trend_dir
    df["trend_strength"] = trend_str

    return df


def get_latest_indicators(symbol: str, session: Session) -> Optional[dict]:
    """Get the most recent indicator row for a symbol."""
    result = session.execute(
        text("""
            SELECT * FROM technical_indicators
            WHERE symbol = :symbol
            ORDER BY date DESC
            LIMIT 1
        """),
        {"symbol": symbol}
    ).mappings().first()
    return dict(result) if result else None


def compute_and_save_indicators(
    symbol: str,
    df: pd.DataFrame,
    stock_id: int,
    session: Session,
) -> int:
    """
    Compute indicators for a full price DataFrame and save to DB.
    Returns number of rows saved.
    """
    if df.empty or len(df) < 50:
        logger.debug(f"{symbol}: Not enough data for indicators ({len(df)} rows)")
        return 0

    try:
        enriched = compute_indicators(df)
    except Exception as e:
        logger.error(f"{symbol}: Indicator computation failed: {e}")
        return 0

    # Only save latest row (update daily)
    latest = enriched.tail(1)
    saved = 0

    for dt, row in latest.iterrows():
        ind_date = dt.date() if hasattr(dt, "date") else dt

        ind_dict = {
            "stock_id": stock_id,
            "symbol": symbol,
            "date": str(ind_date),
            "rsi_14": _safe(row.get("rsi_14")),
            "macd": _safe(row.get("macd")),
            "macd_signal": _safe(row.get("macd_signal")),
            "macd_hist": _safe(row.get("macd_hist")),
            "bb_upper": _safe(row.get("bb_upper")),
            "bb_middle": _safe(row.get("bb_middle")),
            "bb_lower": _safe(row.get("bb_lower")),
            "bb_width": _safe(row.get("bb_width")),
            "bb_pct": _safe(row.get("bb_pct")),
            "ema_9": _safe(row.get("ema_9")),
            "ema_21": _safe(row.get("ema_21")),
            "ema_50": _safe(row.get("ema_50")),
            "ema_200": _safe(row.get("ema_200")),
            "adx": _safe(row.get("adx")),
            "di_plus": _safe(row.get("di_plus")),
            "di_minus": _safe(row.get("di_minus")),
            "stoch_k": _safe(row.get("stoch_k")),
            "stoch_d": _safe(row.get("stoch_d")),
            "cci_20": _safe(row.get("cci_20")),
            "obv": _safe(row.get("obv")),
            "obv_sma": _safe(row.get("obv_sma")),
            "atr_14": _safe(row.get("atr_14")),
            "volume_sma_20": _safe(row.get("volume_sma_20")),
            "volume_ratio": _safe(row.get("volume_ratio")),
            "volume_spike": int(bool(row.get("volume_spike", False))),
            "trend_pattern": str(row.get("trend_pattern", "—")),
            "trend_direction": str(row.get("trend_direction", "SIDEWAYS")),
            "trend_strength": _safe(row.get("trend_strength")),
        }

        try:
            session.execute(text("""
                INSERT OR REPLACE INTO technical_indicators (
                    stock_id, symbol, date, rsi_14, macd, macd_signal, macd_hist,
                    bb_upper, bb_middle, bb_lower, bb_width, bb_pct,
                    ema_9, ema_21, ema_50, ema_200, adx, di_plus, di_minus,
                    stoch_k, stoch_d, cci_20, obv, obv_sma, atr_14,
                    volume_sma_20, volume_ratio, volume_spike, trend_pattern,
                    trend_direction, trend_strength
                ) VALUES (
                    :stock_id, :symbol, :date, :rsi_14, :macd, :macd_signal, :macd_hist,
                    :bb_upper, :bb_middle, :bb_lower, :bb_width, :bb_pct,
                    :ema_9, :ema_21, :ema_50, :ema_200, :adx, :di_plus, :di_minus,
                    :stoch_k, :stoch_d, :cci_20, :obv, :obv_sma, :atr_14,
                    :volume_sma_20, :volume_ratio, :volume_spike, :trend_pattern,
                    :trend_direction, :trend_strength
                )
            """), ind_dict)
            session.commit()
            saved += 1
        except Exception as e:
            session.rollback()
            logger.error(f"{symbol}: Failed to save indicator on {ind_date}: {e}")

    return saved


def _safe(val) -> Optional[float]:
    """Safely convert value to float, returning None for NaN."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) or np.isinf(f) else round(f, 4)
    except (TypeError, ValueError):
        return None


def compute_all_indicators(session: Session, progress_callback=None):
    """Run indicator computation for all active stocks."""
    from core.data_fetcher import get_all_prices_dataframe

    stocks = session.query(Stock).filter(Stock.is_active == True).all()
    total = len(stocks)
    logger.info(f"Computing indicators for {total} stocks...")

    for i, stock in enumerate(stocks):
        try:
            df = get_all_prices_dataframe(stock.symbol, session)
            if not df.empty:
                compute_and_save_indicators(stock.symbol, df, stock.id, session)
        except Exception as e:
            logger.error(f"{stock.symbol}: {e}")

        if progress_callback:
            progress_callback(i + 1, total, stock.symbol)

    logger.info("✅ Indicator computation complete")
