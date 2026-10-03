"""
Page 12: Institutional Multi-Asset Trading Terminal & Matrix Grid
- 4-Up / 6-Up / 9-Up Multi-Chart Grid for simultaneous monitoring of Indexes & Watchlist Stocks
- Quick 1-Click Execution Cockpit with Broker Webhook Gateway & Paper Ledger Dispatch
- Live Order Book & Real-Time Open Positions Monitor
"""
import sys
from pathlib import Path
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

# Universal Root Directory Finder
_curr = Path(__file__).resolve()
while _curr != _curr.parent:
    if (_curr / "core").exists() and (_curr / "db").exists():
        break
    _curr = _curr.parent
BASE_DIR = _curr
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    st.set_page_config(page_title="Trading Terminal Matrix", page_icon="⚡", layout="wide")
except Exception:
    pass

from db.database import get_global_engine, get_session
from sqlalchemy import text
from core.broker_gateway import generate_broker_order_payload, dispatch_broker_simulation, SUPPORTED_BROKERS
from core.portfolio_optimizer import execute_paper_buy, get_paper_portfolio

import importlib
import core.ui_components
importlib.reload(core.ui_components)
from core.ui_components import render_clean_html, fmt_inr, generate_broker_order_clipboard

engine = get_global_engine()


st.title("⚡ Institutional Multi-Asset Trading Terminal & Matrix Grid")
st.caption("Multi-chart widescreen execution terminal: Monitor key index anchors and high-conviction momentum leaders simultaneously with 1-click broker routing.")

# ── Preset Universe Selector ──────────────────────────────────────────────────
st.markdown("##### 🧭 Quick Setup Presets")
p_col1, p_col2, p_col3, p_col4 = st.columns(4)
if "active_matrix_tickers" not in st.session_state:
    st.session_state["active_matrix_tickers"] = ["^NSEI", "^NSEBANK", "RELIANCE", "HDFCBANK"]

with p_col1:
    if st.button("🏛️ Core Benchmarks & Mega-Caps", use_container_width=True):
        st.session_state["active_matrix_tickers"] = ["^NSEI", "^NSEBANK", "RELIANCE", "HDFCBANK", "TCS", "INFY"]
        st.rerun()
with p_col2:
    if st.button("⚡ High-Beta Momentum Leaders", use_container_width=True):
        st.session_state["active_matrix_tickers"] = ["TRENT", "BEL", "DIXON", "HAL", "ZOMATO", "BSE"]
        st.rerun()
with p_col3:
    if st.button("🏦 Financial Titans", use_container_width=True):
        st.session_state["active_matrix_tickers"] = ["^NSEBANK", "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK"]
        st.rerun()
with p_col4:
    if st.button("💻 Technology & IT Giants", use_container_width=True):
        st.session_state["active_matrix_tickers"] = ["^CNXIT", "TCS", "INFY", "HCLTECH", "WIPRO", "TECHM"]
        st.rerun()

# ── Terminal Configuration ───────────────────────────────────────────────────
session_t = get_session(engine)
try:
    stocks_all = session_t.execute(text("SELECT symbol, name, sector FROM stocks WHERE is_active=1 ORDER BY symbol")).fetchall()
finally:
    session_t.close()

stock_symbols = [s[0] for s in stocks_all]
all_available = ["^NSEI", "^NSEBANK", "^CNXIT"] + stock_symbols

t_c1, t_c2, t_c3 = st.columns([1.5, 2.5, 1])

with t_c1:
    grid_layout = st.selectbox("Terminal Chart Layout", ["4-Up Matrix (2x2)", "6-Up Matrix (2x3)"], index=0)

target_count = 4 if grid_layout == "4-Up Matrix (2x2)" else 6
current_selection = [s for s in st.session_state["active_matrix_tickers"] if s in all_available][:target_count]
if len(current_selection) < target_count:
    for s in ["^NSEI", "^NSEBANK", "RELIANCE", "HDFCBANK", "TCS", "INFY"]:
        if s not in current_selection:
            current_selection.append(s)
            if len(current_selection) == target_count:
                break

with t_c2:
    active_grid = st.multiselect(
        f"Active Grid Assets (Select up to {target_count})",
        options=all_available,
        default=current_selection,
        key="ms_active_grid"
    )[:target_count]
    st.session_state["active_matrix_tickers"] = active_grid

with t_c3:
    chart_lookback = st.selectbox("Lookback Window", [30, 60, 90, 180], index=1, format_func=lambda x: f"{x} Trading Days")

# Helper to plot compact candlestick
def render_compact_chart(symbol: str, lookback_days: int):
    session = get_session(engine)
    try:
        if symbol.startswith("^"):
            rows = session.execute(text("SELECT date, open, high, low, close, volume FROM index_prices WHERE symbol = :s ORDER BY date DESC LIMIT :lim"), {"s": symbol, "lim": lookback_days}).fetchall()
        else:
            rows = session.execute(text("SELECT date, open, high, low, close, volume FROM daily_prices WHERE symbol = :s ORDER BY date DESC LIMIT :lim"), {"s": symbol, "lim": lookback_days}).fetchall()
    finally:
        session.close()

    if not rows:
        st.info(f"No price data for {symbol}")
        return

    df_p = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"]).sort_values("date")
    df_p["ema20"] = df_p["close"].ewm(span=20, adjust=False).mean()
    df_p["ema50"] = df_p["close"].ewm(span=50, adjust=False).mean()

    cur_p = float(df_p["close"].iloc[-1])
    ret_d = float(df_p["close"].pct_change().iloc[-1] * 100.0) if len(df_p) > 1 else 0.0

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=df_p["date"], open=df_p["open"], high=df_p["high"], low=df_p["low"], close=df_p["close"], name=symbol, increasing_line_color="#00ff66", decreasing_line_color="#ff2a5f"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_p["date"], y=df_p["ema20"], mode="lines", line=dict(color="#00eefc", width=1.5), name="20 EMA"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_p["date"], y=df_p["ema50"], mode="lines", line=dict(color="#f59e0b", width=1.5), name="50 EMA"), row=1, col=1)
    
    colors_vol = ["#00ff66" if c >= o else "#ff2a5f" for c, o in zip(df_p["close"], df_p["open"])]
    fig.add_trace(go.Bar(x=df_p["date"], y=df_p["volume"], marker_color=colors_vol, name="Volume"), row=2, col=1)

    delta_color = "#00ff66" if ret_d >= 0 else "#ff2a5f"
    fig.update_layout(
        title=f"<b>{symbol}</b> • ₹{cur_p:,.2f} (<span style='color:{delta_color}'>{ret_d:+.2f}%</span>)",
        height=280,
        margin=dict(l=10, r=10, t=30, b=10),
        xaxis_rangeslider_visible=False,
        showlegend=False,
        paper_bgcolor="#10141e",
        plot_bgcolor="#171b26",
        font=dict(color="#e0e8f0", size=10)
    )
    fig.update_xaxes(gridcolor="#1e293b")
    fig.update_yaxes(gridcolor="#1e293b")
    st.plotly_chart(fig, use_container_width=True)


# ── Render Multi-Chart Grid ──────────────────────────────────────────────────
st.markdown("---")

if grid_layout == "4-Up Matrix (2x2)":
    g_row1_col1, g_row1_col2 = st.columns(2)
    g_row2_col1, g_row2_col2 = st.columns(2)

    with g_row1_col1:
        if len(active_grid) > 0: render_compact_chart(active_grid[0], chart_lookback)
    with g_row1_col2:
        if len(active_grid) > 1: render_compact_chart(active_grid[1], chart_lookback)
    with g_row2_col1:
        if len(active_grid) > 2: render_compact_chart(active_grid[2], chart_lookback)
    with g_row2_col2:
        if len(active_grid) > 3: render_compact_chart(active_grid[3], chart_lookback)

else: # 6-Up Matrix (2x3)
    g1, g2, g3 = st.columns(3)
    g4, g5, g6 = st.columns(3)

    cols_list = [g1, g2, g3, g4, g5, g6]
    for i, col in enumerate(cols_list):
        with col:
            if i < len(active_grid):
                render_compact_chart(active_grid[i], chart_lookback)

st.markdown("---")

# ── 1-Click Quick Execution Cockpit & Broker Gateway ─────────────────────────
st.subheader("🎯 1-Click Execution Cockpit & Broker Gateway")
st.caption("Route orders directly to live Indian broker APIs (Zerodha Kite, Angel One, Dhan, Upstox, Fyers) or your live Paper Trading Ledger.")

ex_col1, ex_col2, ex_col3, ex_col4, ex_col5 = st.columns([1.5, 1.2, 1.2, 1.2, 1.5])

with ex_col1:
    exec_symbol = st.selectbox("Execution Asset", stock_symbols, index=0)

# Fetch latest price
session_p = get_session(engine)
try:
    p_last = session_p.execute(text("SELECT close FROM daily_prices WHERE symbol = :s ORDER BY date DESC LIMIT 1"), {"s": exec_symbol}).fetchone()
finally:
    session_p.close()
exec_price = float(p_last[0]) if p_last else 1500.0

with ex_col2:
    exec_side = st.selectbox("Order Side", ["BUY (Long)", "SELL (Short)"])

with ex_col3:
    exec_qty = st.number_input("Shares / Quantity", min_value=1, max_value=50000, value=50, step=10)

with ex_col4:
    exec_broker = st.selectbox("Execution Gateway", ["PAPER_LEDGER", "ZERODHA", "ANGEL_ONE", "DHAN", "UPSTOX", "FYERS"])

with ex_col5:
    render_clean_html(f"""
    <div style="background: #171b26; border: 1px solid #1e293b; padding: 10px 14px; border-radius: 6px;">
        <span style="font-size: 0.8em; color: #94a3b8;">Est. Order Value</span><br>
        <span style="font-size: 1.2em; font-weight: 800; color: #00eefc; font-family: 'JetBrains Mono';">₹{exec_price * exec_qty:,.2f}</span>
    </div>
    """)

# 3-Stage Bracket Parameters
st.markdown(f"**Automated Bracket Levels:** Target 1 (+4%): **₹{exec_price*1.04:,.2f}** | Target 2 (+8%): **₹{exec_price*1.08:,.2f}** | Stop Loss (-4%): **₹{exec_price*0.96:,.2f}**")

if st.button(f"⚡ Send {exec_side.split(' ')[0]} Order to {exec_broker}", type="primary", use_container_width=True):
    if exec_broker == "PAPER_LEDGER":
        session_ex = get_session(engine)
        try:
            execute_paper_buy(
                session=session_ex,
                symbol=exec_symbol,
                shares=exec_qty,
                buy_price=exec_price,
                stop_loss=exec_price * 0.96,
                target_1=exec_price * 1.04,
                target_2=exec_price * 1.08,
                target_3=exec_price * 1.15
            )
        finally:
            session_ex.close()
        st.success(f"🎉 Paper Trade Executed: Bought {exec_qty} shares of {exec_symbol} at ₹{exec_price:,.2f}!")
    else:
        payload = generate_broker_order_payload(
            broker_key=exec_broker,
            symbol=exec_symbol,
            quantity=exec_qty,
            order_side=exec_side.split(' ')[0],
            limit_price=exec_price,
            stop_loss=exec_price * 0.96,
            target_price=exec_price * 1.04
        )
        ack = dispatch_broker_simulation(payload)
        st.success(f"🚀 Broker Webhook Dispatched to **{ack['broker']}** (Order ID: `{ack['order_id']}`)\n\n{ack['message']}")

# One-Click Zerodha/Groww Order Clipboard Generator
with st.expander("📋 One-Click Zerodha Kite / Groww Whole-Share Batch Clipboard", expanded=False):
    order_items = [{"symbol": exec_symbol, "qty": exec_qty, "price": exec_price, "action": exec_side.split(' ')[0]}]
    generate_broker_order_clipboard(order_items, key_prefix="terminal_matrix_exec")

# Live Open Positions Ledger
st.markdown("---")
st.subheader("📑 Live Paper Portfolio Open Positions")
session_pos = get_session(engine)
try:
    pos_rows = session_pos.execute(text("""
        SELECT symbol, shares, avg_entry_price, investment_amount, unrealized_pnl_pct, stop_loss, target_1
        FROM paper_portfolio_positions
        WHERE shares > 0
        ORDER BY investment_amount DESC
    """)).fetchall()
finally:
    session_pos.close()

if pos_rows:
    df_pos = pd.DataFrame(pos_rows, columns=["Symbol", "Shares", "Entry Price (₹)", "Current Value (₹)", "P&L %", "Stop Loss (₹)", "Target 1 (₹)"])
    st.dataframe(
        df_pos.style.format({
            "Entry Price (₹)": "₹{:,.2f}",
            "Current Value (₹)": "₹{:,.2f}",
            "P&L %": "{:+.2f}%",
            "Stop Loss (₹)": "₹{:,.2f}",
            "Target 1 (₹)": "₹{:,.2f}"
        }),
        use_container_width=True,
        hide_index=True
    )
else:
    st.info("No active open positions in paper ledger.")