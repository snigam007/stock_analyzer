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

st.set_page_config(page_title="Trading Terminal Matrix", page_icon="⚡", layout="wide")

from db.database import get_global_engine, get_session
from sqlalchemy import text
from core.broker_gateway import generate_broker_order_payload, dispatch_broker_simulation, SUPPORTED_BROKERS
from core.portfolio_optimizer import execute_paper_buy, get_paper_portfolio

engine = get_global_engine()


def format_price(p): return f"₹{p:,.2f}" if p else "—"


st.title("⚡ Institutional Multi-Asset Trading Terminal & Matrix Grid")
st.caption("Multi-chart widescreen execution terminal: Monitor key index anchors and high-conviction momentum leaders simultaneously with 1-click broker routing.")

# ── Terminal Configuration ───────────────────────────────────────────────────
session_t = get_session(engine)
stocks_all = session_t.execute(text("SELECT symbol, name, sector FROM stocks WHERE is_active=1 ORDER BY symbol")).fetchall()
session_t.close()

stock_symbols = [s[0] for s in stocks_all]

t_c1, t_c2, t_c3 = st.columns([1.5, 1.5, 1])

with t_c1:
    grid_layout = st.selectbox("Terminal Chart Layout", ["4-Up Matrix (2x2)", "6-Up Matrix (2x3)"], index=0)

with t_c2:
    default_tickers = ["^NSEI", "^NSEBANK", "RELIANCE", "HDFCBANK", "TCS", "INFY"]
    if grid_layout == "4-Up Matrix (2x2)":
        active_grid = st.multiselect("Active Grid Assets (Select 4)", ["^NSEI", "^NSEBANK"] + stock_symbols, default=["^NSEI", "^NSEBANK", "RELIANCE", "HDFCBANK"])[:4]
    else:
        active_grid = st.multiselect("Active Grid Assets (Select 6)", ["^NSEI", "^NSEBANK"] + stock_symbols, default=["^NSEI", "^NSEBANK", "RELIANCE", "HDFCBANK", "TCS", "INFY"])[:6]

with t_c3:
    chart_lookback = st.selectbox("Lookback Window", [30, 60, 90, 180], index=1, format_func=lambda x: f"{x} Trading Days")

# Helper to plot compact candlestick
def render_compact_chart(symbol: str, lookback_days: int):
    session = get_session(engine)
    if symbol.startswith("^"):
        rows = session.execute(text("SELECT date, open, high, low, close, volume FROM index_prices WHERE symbol = :s ORDER BY date DESC LIMIT :lim"), {"s": symbol, "lim": lookback_days}).fetchall()
    else:
        rows = session.execute(text("SELECT date, open, high, low, close, volume FROM daily_prices WHERE symbol = :s ORDER BY date DESC LIMIT :lim"), {"s": symbol, "lim": lookback_days}).fetchall()
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
    fig.add_trace(go.Candlestick(x=df_p["date"], open=df_p["open"], high=df_p["high"], low=df_p["low"], close=df_p["close"], name=symbol, increasing_line_color="#00c875", decreasing_line_color="#ff4b4b"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_p["date"], y=df_p["ema20"], mode="lines", line=dict(color="#38bdf8", width=1.5), name="20 EMA"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_p["date"], y=df_p["ema50"], mode="lines", line=dict(color="#f0a500", width=1.5), name="50 EMA"), row=1, col=1)
    
    colors_vol = ["#00c875" if c >= o else "#ff4b4b" for c, o in zip(df_p["close"], df_p["open"])]
    fig.add_trace(go.Bar(x=df_p["date"], y=df_p["volume"], marker_color=colors_vol, name="Volume"), row=2, col=1)

    fig.update_layout(
        title=f"<b>{symbol}</b> • ₹{cur_p:,.2f} ({ret_d:+.2f}%)",
        height=280,
        margin=dict(l=10, r=10, t=30, b=10),
        xaxis_rangeslider_visible=False,
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e0e0e0", size=10)
    )
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
st.caption("Route orders directly to live Indian broker APIs (Zerodha Kite, Angel One, Dhan, Upstox, Fyers) or your live Paper Trading Ledger")

ex_col1, ex_col2, ex_col3, ex_col4, ex_col5 = st.columns([1.5, 1.2, 1.2, 1.2, 1.5])

with ex_col1:
    exec_symbol = st.selectbox("Execution Asset", stock_symbols, index=0)

# Fetch latest price
session_p = get_session(engine)
p_last = session_p.execute(text("SELECT close FROM daily_prices WHERE symbol = :s ORDER BY date DESC LIMIT 1"), {"s": exec_symbol}).fetchone()
session_p.close()
exec_price = float(p_last[0]) if p_last else 1500.0

with ex_col2:
    exec_side = st.selectbox("Order Side", ["BUY (Long)", "SELL (Short)"])

with ex_col3:
    exec_qty = st.number_input("Shares / Quantity", min_value=1, max_value=50000, value=50, step=10)

with ex_col4:
    exec_broker = st.selectbox("Execution Gateway", ["PAPER_LEDGER", "ZERODHA", "ANGEL_ONE", "DHAN", "UPSTOX", "FYERS"])

with ex_col5:
    st.markdown(f"**Est. Order Value:**<br><span style='font-size: 1.2em; font-weight: bold; color: #38bdf8;'>₹{exec_price * exec_qty:,.2f}</span>", unsafe_allow_html=True)

# 3-Stage Bracket Parameters
st.markdown(f"**Automated Bracket Levels:** Target 1 (+4%): **₹{exec_price*1.04:,.2f}** | Target 2 (+8%): **₹{exec_price*1.08:,.2f}** | Stop Loss (-4%): **₹{exec_price*0.96:,.2f}**")

if st.button(f"⚡ Send {exec_side.split(' ')[0]} Order to {exec_broker}", type="primary", use_container_width=True):
    if exec_broker == "PAPER_LEDGER":
        session_ex = get_session(engine)
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