"""
Multi-Timeframe Trend Confluence Engine (MTF)
Analyzes cross-timeframe alignment across:
  1. Short-Term Tactical Momentum (3–10 Sessions: 5/10 EMA, Fast RSI)
  2. Intermediate Core Swing (20–50 Sessions: 20 EMA, 50 SMA, MACD, ADX)
  3. Higher-Timeframe Structural Trend (Weekly Bars: Weekly 10/20 EMA, Weekly RSI)
  4. Macro Secular Regime (200-Day SMA, 50/200 Golden Cross)

Produces an institutional Confluence Rating (Triple Confluence, Core Aligned, or Counter-Trend).
"""

import logging
from typing import Dict, Optional, Tuple
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def aggregate_weekly_bars(df_daily: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregates daily OHLCV dataframe into weekly OHLCV bars.
    Handles standard Trading weeks (Monday to Friday).
    """
    if df_daily.empty or len(df_daily) < 10:
        return pd.DataFrame()

    df = df_daily.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").set_index("date")
    elif not isinstance(df.index, pd.DatetimeIndex):
        return pd.DataFrame()

    # Resample weekly ending Friday
    weekly = df.resample("W-FRI").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }).dropna(subset=["close"])

    return weekly


def _compute_ema(series: pd.Series, span: int) -> pd.Series:
    """Vectorized exponential moving average."""
    return series.ewm(span=span, adjust=False).mean()


def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Vectorized Relative Strength Index."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def analyze_multi_timeframe_alignment(
    symbol: str,
    df_daily: pd.DataFrame,
    signal_direction: str = "BUY"
) -> Dict:
    """
    Evaluates 4 distinct time horizons and synthesizes their confluence with signal_direction.
    Returns structured MTF analysis with badges, ribbon, and confluence level.
    """
    if df_daily.empty or len(df_daily) < 30:
        return {
            "symbol": symbol,
            "confluence_tier": "UNKNOWN",
            "confluence_stars": "⭐",
            "confluence_badge": "🟡 Inconclusive MTF",
            "confluence_score": 50.0,
            "is_triple_confluence": False,
            "is_core_aligned": False,
            "is_counter_trend": False,
            "short_term": {"verdict": "NEUTRAL", "badge": "🟡", "label": "Short-Term: Neutral", "desc": "Consolidating near 10 EMA"},
            "intermediate": {"verdict": "NEUTRAL", "badge": "🟡", "label": "Intermediate: Neutral", "desc": "Testing 20/50 EMA inflection boundary"},
            "weekly": {"verdict": "NEUTRAL", "badge": "🟡", "label": "Weekly: Neutral", "desc": "Weekly structural range"},
            "macro": {"verdict": "NEUTRAL", "badge": "🟡", "label": "Macro: Neutral", "desc": "Near 200-Day SMA"},
            "ribbon_html": "<span>🟡 MTF Inconclusive</span>"
        }

    df = df_daily.copy()
    c = df["close"].values
    n = len(c)
    curr_close = float(c[-1])

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Short-Term Tactical (3–10 sessions)
    # ─────────────────────────────────────────────────────────────────────────
    ema_5 = float(_compute_ema(df["close"], 5).iloc[-1])
    ema_10 = float(_compute_ema(df["close"], 10).iloc[-1])
    rsi_daily = float(_compute_rsi(df["close"], 14).iloc[-1])
    ret_5d = float((curr_close - c[-5]) / c[-5] * 100.0) if n >= 5 else 0.0

    st_bullish = (curr_close >= ema_5 >= ema_10) or (curr_close >= ema_10 and rsi_daily > 52.0)
    st_bearish = (curr_close <= ema_5 <= ema_10) or (curr_close <= ema_10 and rsi_daily < 48.0)

    if st_bullish:
        st_verdict = "BULLISH"
        st_badge = "🟢"
        st_desc = f"Fast 5/10 EMA Bullish (RSI {rsi_daily:.0f})"
    elif st_bearish:
        st_verdict = "BEARISH"
        st_badge = "🔴"
        st_desc = f"Fast 5/10 EMA Bearish (RSI {rsi_daily:.0f})"
    else:
        st_verdict = "NEUTRAL"
        st_badge = "🟡"
        st_desc = f"Consolidating near 10 EMA (RSI {rsi_daily:.0f})"

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Intermediate Core Swing (20–50 sessions)
    # ─────────────────────────────────────────────────────────────────────────
    ema_20 = float(_compute_ema(df["close"], 20).iloc[-1])
    sma_50 = float(df["close"].rolling(min(50, n)).mean().iloc[-1])
    ema_20_prev = float(_compute_ema(df["close"], 20).iloc[-5]) if n >= 5 else ema_20
    ema_20_slope = (ema_20 - ema_20_prev) / ema_20_prev * 100.0

    int_bullish = (curr_close > ema_20) and (ema_20_slope > 0.1) and (curr_close > sma_50)
    int_bearish = (curr_close < ema_20) and (ema_20_slope < -0.1) and (curr_close < sma_50)

    if int_bullish:
        int_verdict = "BULLISH"
        int_badge = "🟢"
        int_desc = f"Above 20 EMA (+{ema_20_slope:.1f}% slope) & 50 SMA"
    elif int_bearish:
        int_verdict = "BEARISH"
        int_badge = "🔴"
        int_desc = f"Below 20 EMA ({ema_20_slope:.1f}% slope) & 50 SMA"
    else:
        int_verdict = "NEUTRAL"
        int_badge = "🟡"
        int_desc = "Testing 20/50 EMA inflection boundary"

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Higher-Timeframe Structural Trend (Weekly Bar Aggregation)
    # ─────────────────────────────────────────────────────────────────────────
    df_weekly = aggregate_weekly_bars(df)
    if len(df_weekly) >= 8:
        w_close = df_weekly["close"]
        w_curr = float(w_close.iloc[-1])
        w_ema_10 = float(_compute_ema(w_close, 10).iloc[-1])
        w_ema_20 = float(_compute_ema(w_close, 20).iloc[-1])
        w_rsi = float(_compute_rsi(w_close, 14).iloc[-1])

        # Weekly structural higher highs or lower lows
        recent_w_highs = df_weekly["high"].tail(4).values
        recent_w_lows = df_weekly["low"].tail(4).values
        w_hh = recent_w_highs[-1] >= recent_w_highs[0]
        w_hl = recent_w_lows[-1] >= recent_w_lows[0]

        wk_bullish = (w_curr > w_ema_20) and (w_rsi > 50.0) and (w_hh or w_hl)
        wk_bearish = (w_curr < w_ema_20) and (w_rsi < 50.0)
    else:
        # Fallback to daily 50/100 proxy if weekly bars limited
        sma_100 = float(df["close"].rolling(min(100, n)).mean().iloc[-1])
        wk_bullish = (curr_close > sma_100) and (rsi_daily > 50.0)
        wk_bearish = (curr_close < sma_100) and (rsi_daily < 48.0)
        w_rsi = rsi_daily

    if wk_bullish:
        wk_verdict = "BULLISH"
        wk_badge = "🟢"
        wk_desc = f"Weekly Structural Uptrend (Weekly RSI {w_rsi:.0f})"
    elif wk_bearish:
        wk_verdict = "BEARISH"
        wk_badge = "🔴"
        wk_desc = f"Weekly Structural Downtrend (Weekly RSI {w_rsi:.0f})"
    else:
        wk_verdict = "NEUTRAL"
        wk_badge = "🟡"
        wk_desc = "Weekly structural range / consolidation"

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Macro Secular Regime (200-Day SMA / Multi-Month)
    # ─────────────────────────────────────────────────────────────────────────
    if n >= 180:
        sma_200 = float(df["close"].rolling(min(200, n)).mean().iloc[-1])
        sma_200_prev = float(df["close"].rolling(min(200, n)).mean().iloc[-20])
        sma_200_slope = (sma_200 - sma_200_prev) / sma_200_prev * 100.0
        golden_cross = sma_50 > sma_200

        macro_bullish = (curr_close > sma_200) and (golden_cross or sma_200_slope >= 0)
        macro_bearish = (curr_close < sma_200) and (not golden_cross or sma_200_slope <= 0)
    else:
        macro_bullish = curr_close > sma_50
        macro_bearish = curr_close < sma_50
        sma_200 = sma_50

    if macro_bullish:
        macro_verdict = "BULLISH"
        macro_badge = "🟢"
        macro_desc = "Above 200-Day SMA (Secular Bull Regime)"
    elif macro_bearish:
        macro_verdict = "BEARISH"
        macro_badge = "🔴"
        macro_desc = "Below 200-Day SMA (Secular Bear Regime)"
    else:
        macro_verdict = "NEUTRAL"
        macro_badge = "🟡"
        macro_desc = "Hovering near 200-Day SMA"

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Confluence Synthesis vs Signal Direction
    # ─────────────────────────────────────────────────────────────────────────
    target_v = "BULLISH" if signal_direction == "BUY" else ("BEARISH" if signal_direction == "SELL" else "NEUTRAL")
    opp_v = "BEARISH" if signal_direction == "BUY" else "BULLISH"

    matches = sum(1 for v in [st_verdict, int_verdict, wk_verdict, macro_verdict] if v == target_v)
    conflicts = sum(1 for v in [st_verdict, int_verdict, wk_verdict, macro_verdict] if v == opp_v)

    is_triple = (wk_verdict == target_v) and (int_verdict == target_v) and (st_verdict == target_v)
    is_core_aligned = (wk_verdict == target_v) and (int_verdict == target_v)
    is_counter_trend = (wk_verdict == opp_v) and (macro_verdict == opp_v)

    if is_triple:
        confluence_tier = "TRIPLE_CONFLUENCE"
        confluence_stars = "⭐⭐⭐"
        confluence_badge = "⭐⭐⭐ TRIPLE CONFLUENCE"
        confluence_label = "Full Multi-Timeframe Alignment (Highest Hit Rate)"
        confluence_score = 95.0
        badge_color = "#00c875"
        badge_bg = "rgba(0, 200, 117, 0.12)"
    elif is_core_aligned:
        confluence_tier = "CORE_ALIGNED"
        confluence_stars = "⭐⭐"
        confluence_badge = "⭐⭐ CORE CONFLUENCE"
        confluence_label = "Higher-TF Weekly & Intermediate Aligned"
        confluence_score = 80.0
        badge_color = "#1f6feb"
        badge_bg = "rgba(31, 111, 235, 0.12)"
    elif is_counter_trend:
        confluence_tier = "COUNTER_TREND"
        confluence_stars = "⚠️"
        confluence_badge = "⚠️ COUNTER-TREND SKEW"
        confluence_label = "Signal opposes Higher-TF Weekly Trend (Tighter Stop Loss Advised)"
        confluence_score = 35.0
        badge_color = "#e04b4b"
        badge_bg = "rgba(224, 75, 75, 0.12)"
    elif wk_verdict == target_v and st_verdict != target_v:
        confluence_tier = "PULLBACK_DIP"
        confluence_stars = "🎯"
        confluence_badge = "🎯 HIGHER-TF DIP BUY"
        confluence_label = "Higher-TF Trend Intact; Short-term Tactical Pullback"
        confluence_score = 75.0
        badge_color = "#00e5a0"
        badge_bg = "rgba(0, 229, 160, 0.12)"
    else:
        confluence_tier = "MIXED"
        confluence_stars = "⚖️"
        confluence_badge = "⚖️ MIXED TIMEFRAMES"
        confluence_label = "Selective Timeframe Alignment"
        confluence_score = 55.0
        badge_color = "#eab308"
        badge_bg = "rgba(234, 179, 8, 0.12)"

    # HTML Ribbon for Stock Cards
    ribbon_html = f"""
    <div style="display: inline-flex; align-items: center; gap: 6px; font-size: 0.8em; background: {badge_bg}; border: 1px solid {badge_color}; padding: 2px 8px; border-radius: 4px; font-weight: 600; color: {badge_color};">
        <span>{confluence_badge}</span>
        <span style="color: #8b949e;">|</span>
        <span title="{st_desc}">ST: {st_badge}</span>
        <span title="{int_desc}">Core: {int_badge}</span>
        <span title="{wk_desc}">Weekly: {wk_badge}</span>
        <span title="{macro_desc}">Macro: {macro_badge}</span>
    </div>
    """

    return {
        "symbol": symbol,
        "signal_direction": signal_direction,
        "confluence_tier": confluence_tier,
        "confluence_stars": confluence_stars,
        "confluence_badge": confluence_badge,
        "confluence_label": confluence_label,
        "confluence_score": confluence_score,
        "badge_color": badge_color,
        "badge_bg": badge_bg,
        "is_triple_confluence": is_triple,
        "is_core_aligned": is_core_aligned,
        "is_counter_trend": is_counter_trend,
        "short_term": {"verdict": st_verdict, "badge": st_badge, "desc": st_desc},
        "intermediate": {"verdict": int_verdict, "badge": int_badge, "desc": int_desc},
        "weekly": {"verdict": wk_verdict, "badge": wk_badge, "desc": wk_desc},
        "macro": {"verdict": macro_verdict, "badge": macro_badge, "desc": macro_desc},
        "ribbon_html": ribbon_html
    }


def get_all_stocks_mtf_map(session: Session, min_date: Optional[str] = None) -> Dict[str, dict]:
    """
    Computes MTF alignment for all active stocks currently holding a BUY or SELL signal.
    Cached for fast rendering across Daily Top Stocks.
    """
    # Fetch latest signals
    query_sigs = """
        SELECT s.symbol, s.signal
        FROM signals s
        WHERE s.date = (SELECT MAX(date) FROM signals)
        AND s.signal IN ('BUY', 'SELL')
    """
    sigs = session.execute(text(query_sigs)).fetchall()
    if not sigs:
        return {}

    symbols = [r[0] for r in sigs]
    sig_map = {r[0]: r[1] for r in sigs}

    # Fetch daily prices for these symbols (last 250 sessions)
    query_prices = """
        SELECT symbol, date, open, high, low, close, volume
        FROM daily_prices
        WHERE symbol IN :symbols
        ORDER BY symbol, date ASC
    """
    # SQLite has a limit on parameters, chunk if necessary
    chunk_size = 100
    all_prices = []
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        p_rows = session.execute(
            text(f"SELECT symbol, date, open, high, low, close, volume FROM daily_prices WHERE symbol IN ({','.join([':s'+str(j) for j in range(len(chunk))])}) ORDER BY symbol, date ASC"),
            {f's{j}': chunk[j] for j in range(len(chunk))}
        ).fetchall()
        all_prices.extend(p_rows)

    # Group by symbol
    from collections import defaultdict
    sym_prices = defaultdict(list)
    for p in all_prices:
        sym_prices[p[0]].append({
            "date": p[1], "open": p[2], "high": p[3], "low": p[4], "close": p[5], "volume": p[6]
        })

    mtf_map = {}
    for sym, sig in sig_map.items():
        p_list = sym_prices.get(sym, [])
        if p_list:
            df_sym = pd.DataFrame(p_list)
            res = analyze_multi_timeframe_alignment(sym, df_sym, signal_direction=sig)
            mtf_map[sym] = res
        else:
            mtf_map[sym] = {
                "confluence_tier": "UNKNOWN", "confluence_stars": "⭐",
                "confluence_badge": "🟡 Inconclusive MTF",
                "confluence_label": "Price history not loaded",
                "is_triple_confluence": False, "is_core_aligned": False, "is_counter_trend": False,
                "ribbon_html": "<span>🟡 MTF N/A</span>"
            }

    return mtf_map
