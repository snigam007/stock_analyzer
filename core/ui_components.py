"""
core/ui_components.py
=====================
Universal UI components and helpers for the Retro Quant design system:
- HTML Sanitization (replaces CommonMark leak vulnerabilities)
- Indian Rupee Currency Formatting (avoids ellipsis truncation on metric cards)
- Interactive Plotly Speedometer Gauge for Macro Regimes
- Mini Sparklines for Indices and Watchlist Cards
- High-Aesthetic Defensive Empty States (when Risk-Off locks trading)
- One-Click Broker Order Exporter (Zerodha/Groww/Angel One format)
"""
import re
import math
from typing import List, Dict, Optional, Any
import streamlit as st
import plotly.graph_objects as go
import pandas as pd


def render_clean_html(html_str: str) -> None:
    """
    Renders HTML cleanly in Streamlit by stripping raw HTML comments and leading indentation.
    Prevents Streamlit's CommonMark parser from treating indented blocks as <pre><code>.
    """
    cleaned = re.sub(r'<!--.*?-->', '', html_str, flags=re.DOTALL)
    cleaned = "\n".join([line.lstrip() for line in cleaned.split("\n")])
    st.markdown(cleaned, unsafe_allow_html=True)


def fmt_inr(v: Any, precision: int = 2) -> str:
    """
    Formats numbers into clean Indian rupee denominations:
    - >= 1 Crore (10M): ₹X.XX Cr
    - >= 1 Lakh (100k): ₹X.X L
    - Else: ₹X,XXX
    """
    if v is None:
        return "₹0"
    try:
        val = float(v)
    except (ValueError, TypeError):
        return str(v)

    sign = "-" if val < 0 else ""
    abs_v = abs(val)

    if abs_v >= 1e7:
        return f"{sign}₹{abs_v / 1e7:.{precision}f} Cr"
    elif abs_v >= 1e5:
        p = min(precision, 1)
        return f"{sign}₹{abs_v / 1e5:.{p}f} L"
    elif abs_v >= 1e3:
        return f"{sign}₹{abs_v:,.0f}"
    else:
        return f"{sign}₹{abs_v:.{precision}f}"


def render_macro_gauge(score: float, regime_name: str = "RISK-OFF", height: int = 190) -> go.Figure:
    """
    Renders a semi-circular Plotly speedometer gauge (0 to 100) for Macro Regime sentiment.
    """
    score = max(0.0, min(100.0, float(score)))

    # Determine needle and text color
    if score >= 65:
        bar_color = "#00ff66"  # Arcade Green
        status_label = "RISK-ON (AGGRESSIVE ALPHA)"
    elif score >= 35:
        bar_color = "#f59e0b"  # Amber Neutral
        status_label = "NEUTRAL / SELECTIVE CONSOLIDATION"
    else:
        bar_color = "#ff2a5f"  # Crimson Risk-Off
        status_label = "RISK-OFF (CAPITAL PRESERVATION)"

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number={"suffix": "/100", "font": {"family": "Space Grotesk, sans-serif", "size": 26, "color": bar_color}},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#849581", "tickfont": {"size": 10, "color": "#849581"}},
            "bar": {"color": bar_color, "thickness": 0.3},
            "bgcolor": "#171b26",
            "borderwidth": 2,
            "bordercolor": "#313540",
            "steps": [
                {"range": [0, 35], "color": "rgba(255, 42, 95, 0.18)"},
                {"range": [35, 65], "color": "rgba(245, 158, 11, 0.18)"},
                {"range": [65, 100], "color": "rgba(0, 255, 102, 0.18)"},
            ],
            "threshold": {
                "line": {"color": bar_color, "width": 4},
                "thickness": 0.75,
                "value": score
            }
        }
    ))

    fig.update_layout(
        height=height,
        margin=dict(l=15, r=15, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#dfe2f1", family="JetBrains Mono, monospace")
    )
    return fig


def render_sparkline(prices: List[float], color: str = "#00ff66", height: int = 50) -> go.Figure:
    """
    Renders an ultra-compact mini sparkline for metric cards and index tiles.
    """
    fig = go.Figure()
    if len(prices) >= 2:
        x = list(range(len(prices)))
        fig.add_trace(go.Scatter(
            x=x, y=prices,
            mode="lines",
            line=dict(color=color, width=2),
            fill="tozeroy",
            fillcolor=f"rgba{tuple(list(bytes.fromhex(color.lstrip('#')))+[0.12])}" if color.startswith('#') and len(color)==7 else "rgba(0, 255, 102, 0.12)",
            hoverinfo="y"
        ))

    fig.update_layout(
        height=height,
        margin=dict(l=0, r=0, t=2, b=2),
        xaxis=dict(visible=False, showgrid=False),
        yaxis=dict(visible=False, showgrid=False),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)"
    )
    return fig


def render_empty_defensive_state(
    title: str = "Active Capital Preservation Lock",
    reason: Optional[str] = None,
    action_note: Optional[str] = None,
    message: Optional[str] = None,
    action_text: Optional[str] = None,
    **kwargs
) -> None:
    """
    Renders an institutional-grade defensive state notice when risk gates prevent trade generation.
    Supports flexible arguments: reason/message and action_note/action_text.
    """
    final_reason = reason or message or "Macro Market Regime is currently RISK-OFF (Score < 35.0/100)."
    final_action = action_note or action_text or "Zero speculative breakout entries permitted. Capital is 100% protected in LiquidBees (6.5% APY) while waiting for institutional capitulation."

    render_clean_html(f"""
    <div style="background-color: #171b26; border: 2px solid #ff2a5f; border-left: 6px solid #ff2a5f; box-shadow: 4px 4px 0px #030712; padding: 18px 22px; margin: 16px 0;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
            <span style="font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.1rem; color: #ff2a5f; letter-spacing: 0.05em;">
                🛡️ {title.upper()}
            </span>
            <span style="background: rgba(255, 42, 95, 0.2); color: #ff2a5f; border: 1px solid #ff2a5f; padding: 2px 8px; font-size: 0.72rem; font-weight: 700; font-family: 'JetBrains Mono', monospace;">
                ZERO DRAWDOWN MODE
            </span>
        </div>
        <p style="font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; color: #dfe2f1; margin: 4px 0 8px 0; line-height: 1.45;">
            {final_reason}
        </p>
        <div style="background: #0f131d; border: 1px solid #313540; padding: 10px 14px; font-family: 'JetBrains Mono', monospace; font-size: 0.78rem; color: #00eefc;">
            💡 <strong>Capital Action:</strong> {final_action}
        </div>
    </div>
    """)


class BrokerOrderResult(str):
    """Universal return type that behaves as a string and unpacks into (csv_data, json_data)."""
    def __new__(cls, text_val: str, csv_val: str = "", json_val: str = ""):
        obj = super().__new__(cls, text_val)
        obj.csv_val = csv_val
        obj.json_val = json_val
        return obj

    def __iter__(self):
        return iter((self.csv_val, self.json_val))


def generate_broker_order_clipboard(
    orders: List[Dict[str, Any]],
    label: str = "📋 Copy Broker Orders (Zerodha / Groww)",
    key_prefix: str = "broker_clip",
    render: Optional[bool] = None
) -> BrokerOrderResult:
    """
    Generates a copy-paste ready order block for Indian retail brokers (Zerodha Kite / Groww / Angel One).
    Supports:
    1. string output: st.code(generate_broker_order_clipboard(orders))
    2. tuple unpacking: csv_data, json_data = generate_broker_order_clipboard(orders)
    3. direct Streamlit UI rendering: generate_broker_order_clipboard(orders, key_prefix="...")
    """
    import json
    lines = []
    csv_rows = ["Symbol,Quantity,Price,Action,Product,Exchange,StopLoss"]
    json_items = []

    for o in orders:
        sym = o.get("symbol", "").replace(".NS", "")
        qty = o.get("qty", o.get("shares", 1))
        price = o.get("price", o.get("current_price", 0.0))
        sl = o.get("sl", o.get("stop_loss", 0.0))
        act = o.get("action", "BUY").upper()
        limit_txt = f"LIMIT/MKT: ₹ {price:,.2f}" if price > 0 else "MARKET"
        sl_txt = f"| TRAILING SL: ₹{sl:,.2f}" if sl > 0 else ""
        lines.append(f"{act:<4}  {sym:<12} | QTY: {qty:<3} | EXCHANGE: NSE | PRODUCT: CNC | {limit_txt} {sl_txt}")
        csv_rows.append(f"{sym},{qty},{price},{act},CNC,NSE,{sl}")
        json_items.append({"symbol": sym, "quantity": qty, "price": price, "action": act, "stop_loss": sl})

    text_out = "\n".join(lines)
    csv_out = "\n".join(csv_rows)
    json_out = json.dumps(json_items, indent=2)

    should_render = render if render is not None else (key_prefix != "broker_clip" or label != "📋 Copy Broker Orders (Zerodha / Groww)")

    if should_render:
        try:
            st.code(text_out, language="text")
            st.download_button(
                label="📥 Download Broker Orders CSV",
                data=csv_out,
                file_name=f"{key_prefix}_orders.csv",
                mime="text/csv",
                key=f"{key_prefix}_dl_btn"
            )
        except Exception:
            pass

    return BrokerOrderResult(text_out, csv_out, json_out)
