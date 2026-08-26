"""
Technical Indicators Engine
Computes all 10 technical indicators using pandas-ta and saves to database.
Also computes trend patterns (↑↑↓↑), trend direction, and volume analysis.
"""
import logging
import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Optional
import sys

import numpy as np
import pandas as pd
import pandas_ta as ta
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
    Compute all technical indicators for a DataFrame with OHLCV data.
    Returns the enriched DataFrame with indicator columns added.
    """
    if df is None or df.empty or len(df) < 50:
        return df

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df.get("volume", pd.Series(index=df.index))

    # ── 1. RSI ────────────────────────────────────────────────────────────────
    df["rsi_14"] = ta.rsi(close, length=RSI_PERIOD)

    # ── 2. MACD ───────────────────────────────────────────────────────────────
    macd_df = ta.macd(close, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
    if macd_df is not None:
        macd_cols = macd_df.columns.tolist()
        df["macd"] = macd_df.iloc[:, 0]           # MACD line
        df["macd_signal"] = macd_df.iloc[:, 2]    # Signal line
        df["macd_hist"] = macd_df.iloc[:, 1]      # Histogram

    # ── 3. Bollinger Bands ────────────────────────────────────────────────────
    bb_df = ta.bbands(close, length=BB_PERIOD, std=BB_STD)
    if bb_df is not None:
        df["bb_lower"] = bb_df.iloc[:, 0]
        df["bb_middle"] = bb_df.iloc[:, 1]
        df["bb_upper"] = bb_df.iloc[:, 2]
        df["bb_width"] = bb_df.iloc[:, 3]
        df["bb_pct"] = bb_df.iloc[:, 4]           # %B: position within bands

    # ── 4. EMAs ───────────────────────────────────────────────────────────────
    for period in EMA_PERIODS:
        df[f"ema_{period}"] = ta.ema(close, length=period)

    # ── 5. ADX ────────────────────────────────────────────────────────────────
    adx_df = ta.adx(high, low, close, length=ADX_PERIOD)
    if adx_df is not None:
        df["adx"] = adx_df.iloc[:, 0]
        df["di_plus"] = adx_df.iloc[:, 1]
        df["di_minus"] = adx_df.iloc[:, 2]

    # ── 6. Stochastic ─────────────────────────────────────────────────────────
    stoch_df = ta.stoch(high, low, close, k=STOCH_K, d=STOCH_D)
    if stoch_df is not None:
        df["stoch_k"] = stoch_df.iloc[:, 0]
        df["stoch_d"] = stoch_df.iloc[:, 1]

    # ── 7. CCI ────────────────────────────────────────────────────────────────
    df["cci_20"] = ta.cci(high, low, close, length=CCI_PERIOD)

    # ── 8. OBV ────────────────────────────────────────────────────────────────
    if not volume.isna().all():
        df["obv"] = ta.obv(close, volume)
        df["obv_sma"] = ta.sma(df["obv"], length=OBV_SMOOTH)

    # ── 9. ATR ────────────────────────────────────────────────────────────────
    df["atr_14"] = ta.atr(high, low, close, length=ATR_PERIOD)

    # ── 10. Volume Analysis ───────────────────────────────────────────────────
    if not volume.isna().all():
        df["volume_sma_20"] = ta.sma(volume, length=20)
        df["volume_ratio"] = volume / df["volume_sma_20"].replace(0, np.nan)
        df["volume_spike"] = df["volume_ratio"] > VOLUME_SPIKE_MULTIPLIER

    # ── 11. Trend Pattern ─────────────────────────────────────────────────────
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
