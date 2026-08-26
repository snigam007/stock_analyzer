"""
Visible Range Volume Profile (VPVR) & On-Chart Target/SL Overlays
- Computes Point of Control (POC) and 70% Value Area (VAH / VAL)
- Generates high-performance Plotly subplots combining Candlesticks, VPVR volume bars,
  and strategic Tranche Targets (T1, T2, T3) and Stop-Loss execution markers.
"""
import logging
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

logger = logging.getLogger(__name__)


def compute_volume_profile(
    df: pd.DataFrame,
    num_bins: int = 40,
    value_area_pct: float = 0.70,
) -> Dict:
    """
    Computes Visible Range Volume Profile (VPVR):
    1. Slices high-low price range into N equal bins.
    2. Sums total volume, bullish volume (close >= open), and bearish volume (close < open).
    3. Finds the Point of Control (POC) - highest volume price node.
    4. Calculates Value Area High (VAH) and Value Area Low (VAL) covering 70% of total volume.
    """
    if df.empty or len(df) < 5:
        return {}

    min_p = float(df["low"].min())
    max_p = float(df["high"].max())

    if max_p <= min_p:
        return {}

    bin_edges = np.linspace(min_p, max_p, num_bins + 1)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
    bin_width = bin_edges[1] - bin_edges[0]

    vol_total = np.zeros(num_bins)
    vol_bull = np.zeros(num_bins)
    vol_bear = np.zeros(num_bins)

    for _, row in df.iterrows():
        c_low = float(row["low"])
        c_high = float(row["high"])
        c_vol = float(row["volume"])
        is_bull = float(row["close"]) >= float(row["open"])

        # Determine overlapping bins
        idx_start = max(0, int((c_low - min_p) / bin_width))
        idx_end = min(num_bins - 1, int((c_high - min_p) / bin_width))
        num_overlap = max(1, idx_end - idx_start + 1)
        vol_per_bin = c_vol / num_overlap

        for b in range(idx_start, idx_end + 1):
            vol_total[b] += vol_per_bin
            if is_bull:
                vol_bull[b] += vol_per_bin
            else:
                vol_bear[b] += vol_per_bin

    # Point of Control (POC)
    poc_idx = int(np.argmax(vol_total))
    poc_price = float(bin_centers[poc_idx])

    # 70% Value Area (VAH & VAL)
    total_volume_sum = np.sum(vol_total)
    target_va_volume = total_volume_sum * value_area_pct

    current_va_vol = vol_total[poc_idx]
    upper_idx = poc_idx
    lower_idx = poc_idx

    while current_va_vol < target_va_volume and (upper_idx < num_bins - 1 or lower_idx > 0):
        next_up_vol = vol_total[upper_idx + 1] if upper_idx < num_bins - 1 else 0
        next_dn_vol = vol_total[lower_idx - 1] if lower_idx > 0 else 0

        if next_up_vol >= next_dn_vol and upper_idx < num_bins - 1:
            upper_idx += 1
            current_va_vol += vol_total[upper_idx]
        elif lower_idx > 0:
            lower_idx -= 1
            current_va_vol += vol_total[lower_idx]
        elif upper_idx < num_bins - 1:
            upper_idx += 1
            current_va_vol += vol_total[upper_idx]
        else:
            break

    vah_price = float(bin_centers[upper_idx])
    val_price = float(bin_centers[lower_idx])

    bins_data = []
    for i in range(num_bins):
        bins_data.append({
            "price": round(float(bin_centers[i]), 2),
            "total_volume": float(vol_total[i]),
            "bull_volume": float(vol_bull[i]),
            "bear_volume": float(vol_bear[i]),
            "is_poc": bool(i == poc_idx),
            "in_value_area": bool(lower_idx <= i <= upper_idx),
        })

    return {
        "poc_price": round(poc_price, 2),
        "vah_price": round(vah_price, 2),
        "val_price": round(val_price, 2),
        "total_volume": float(total_volume_sum),
        "bins": bins_data,
    }


def create_vpvr_candlestick_chart(
    df: pd.DataFrame,
    symbol: str,
    stock_name: str,
    target_1: Optional[float] = None,
    target_2: Optional[float] = None,
    target_3: Optional[float] = None,
    stop_loss: Optional[float] = None,
    buy_price: Optional[float] = None,
) -> go.Figure:
    """
    Creates an interactive 2-column chart:
    - Left Column (82% width): Candlesticks, EMAs, and On-Chart Execution Target Lines
    - Right Column (18% width): Horizontal VPVR Volume Bars with POC and Value Area
    """
    vp = compute_volume_profile(df)
    
    fig = make_subplots(
        rows=2, cols=2,
        shared_xaxes=True,
        column_widths=[0.82, 0.18],
        row_heights=[0.75, 0.25],
        horizontal_spacing=0.015,
        vertical_spacing=0.03,
        specs=[
            [{"type": "xy"}, {"type": "xy"}],
            [{"type": "xy"}, {"type": "xy"}],
        ]
    )

    # 1. Main Candlestick Chart (Row 1, Col 1)
    fig.add_trace(
        go.Candlestick(
            x=df["date"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Price",
            increasing_line_color="#00c875",
            decreasing_line_color="#ff4b4b",
        ),
        row=1, col=1
    )

    # Add EMAs if available
    for ema_col, color in [("ema_21", "#00a8ff"), ("ema_50", "#ffaa00"), ("ema_200", "#ff3366")]:
        if ema_col in df.columns and df[ema_col].dropna().any():
            fig.add_trace(
                go.Scatter(
                    x=df["date"], y=df[ema_col],
                    mode="lines", name=ema_col.upper(),
                    line=dict(color=color, width=1.2)
                ),
                row=1, col=1
            )

    # Add On-Chart Target & Stop Loss Lines
    if buy_price and buy_price > 0:
        fig.add_hline(y=buy_price, line=dict(color="#00e5ff", width=1.5, dash="dash"),
                      annotation_text=f"BUY Entry: ₹{buy_price:,.2f}", annotation_position="top left", row=1, col=1)
    if target_1 and target_1 > 0:
        fig.add_hline(y=target_1, line=dict(color="#00c875", width=1.5, dash="dot"),
                      annotation_text=f"🎯 T1 (Tranche 1): ₹{target_1:,.2f}", annotation_position="top left", row=1, col=1)
    if target_2 and target_2 > 0:
        fig.add_hline(y=target_2, line=dict(color="#00c875", width=1.5, dash="dot"),
                      annotation_text=f"🎯 T2 (Tranche 2): ₹{target_2:,.2f}", annotation_position="top left", row=1, col=1)
    if target_3 and target_3 > 0:
        fig.add_hline(y=target_3, line=dict(color="#00ffcc", width=1.5, dash="dot"),
                      annotation_text=f"🎯 T3 Runner: ₹{target_3:,.2f}", annotation_position="top left", row=1, col=1)
    if stop_loss and stop_loss > 0:
        fig.add_hline(y=stop_loss, line=dict(color="#ff4b4b", width=1.5, dash="dash"),
                      annotation_text=f"🛑 Stop Loss: ₹{stop_loss:,.2f}", annotation_position="bottom left", row=1, col=1)

    # 2. Daily Volume Bars (Row 2, Col 1)
    vol_colors = ["#00c875" if c >= o else "#ff4b4b" for c, o in zip(df["close"], df["open"])]
    fig.add_trace(
        go.Bar(
            x=df["date"], y=df["volume"],
            name="Daily Volume",
            marker_color=vol_colors,
            opacity=0.6,
        ),
        row=2, col=1
    )

    # 3. Horizontal VPVR Volume Profile Bars (Row 1, Col 2)
    if vp and "bins" in vp:
        prices = [b["price"] for b in vp["bins"]]
        bull_vols = [b["bull_volume"] for b in vp["bins"]]
        bear_vols = [b["bear_volume"] for b in vp["bins"]]

        # Bullish Volume (Green)
        fig.add_trace(
            go.Bar(
                y=prices, x=bull_vols,
                orientation="h",
                name="Bull VPVR",
                marker_color="#00c875",
                opacity=0.55,
                showlegend=False,
            ),
            row=1, col=2
        )
        # Bearish Volume (Red)
        fig.add_trace(
            go.Bar(
                y=prices, x=bear_vols,
                orientation="h",
                name="Bear VPVR",
                marker_color="#ff4b4b",
                opacity=0.55,
                showlegend=False,
            ),
            row=1, col=2
        )

        # Highlight Point of Control (POC) on VPVR
        fig.add_hline(
            y=vp["poc_price"],
            line=dict(color="#ffd700", width=2, dash="solid"),
            annotation_text=f"⭐ POC: ₹{vp['poc_price']:,.2f}",
            annotation_position="right",
            row=1, col=2
        )
        # Value Area High & Low
        fig.add_hline(y=vp["vah_price"], line=dict(color="#00a8ff", width=1.2, dash="dash"), annotation_text="VAH (70%)", annotation_position="right", row=1, col=2)
        fig.add_hline(y=vp["val_price"], line=dict(color="#00a8ff", width=1.2, dash="dash"), annotation_text="VAL (70%)", annotation_position="right", row=1, col=2)

    fig.update_layout(
        title=f"🕯️ {symbol} — {stock_name} | Price Action, On-Chart Targets & Visible Range Volume Profile (VPVR)",
        barmode="stack",
        height=620,
        paper_bgcolor="#0e1117",
        plot_bgcolor="#161b22",
        font=dict(color="#e0e8f0"),
        xaxis_rangeslider_visible=False,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )

    fig.update_xaxes(gridcolor="#2d3139")
    fig.update_yaxes(gridcolor="#2d3139")
    fig.update_xaxes(showticklabels=False, row=1, col=2)

    return fig