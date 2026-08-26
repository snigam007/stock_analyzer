"""
Page 7: Quantitative Strategy Backtesting
- Test algorithmic strategies on historical data
- Compare Strategy Equity vs Buy & Hold Benchmark
- Win Rate, Profit Factor, Max Drawdown, Sharpe, Sortino
- Detailed Trade-by-Trade Execution Log & Equity Curve
"""
import sys
from pathlib import Path
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
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
st.set_page_config(page_title="Strategy Backtesting", page_icon="🧪", layout="wide")

import importlib
import core.backtester
importlib.reload(core.backtester)

from db.database import get_global_engine, get_session
from sqlalchemy import text
from core.backtester import run_backtest

engine = get_global_engine()


def format_price(p): return f"₹{p:,.2f}" if p else "—"


@st.cache_data(ttl=30)
def get_available_stocks():
    session = get_session(engine)
    result = session.execute(text("""
        SELECT s.symbol, s.name, s.sector
        FROM stocks s
        JOIN daily_prices p ON s.symbol = p.symbol
        GROUP BY s.symbol
        HAVING COUNT(p.id) >= 60
        ORDER BY s.sector, s.symbol
    """)).fetchall()
    session.close()
    return result


st.title("🧪 Quantitative Strategy Backtesting Engine")
st.caption("Verify and stress-test algorithmic trading strategies against historical Indian market data")

# ── Sidebar Controls ──────────────────────────────────────────────────────────
st.sidebar.title("⚙️ Backtest Settings")

stock_list = get_available_stocks()
if not stock_list:
    st.warning("No historical price data available. Please download stock data first.")
    st.stop()

symbols = [s[0] for s in stock_list]
labels = [f"{s[0]} — {s[1][:30]} ({s[2]})" for s in stock_list]

selected_idx = st.sidebar.selectbox("Select Stock / Asset", range(len(labels)), format_func=lambda i: labels[i])
selected_symbol = symbols[selected_idx]

strategy = st.sidebar.selectbox(
    "Select Strategy",
    [
        "Multi-Engine Confluence",
        "EMA Golden Cross Trend",
        "RSI Oversold Mean Reversion",
        "Volume Breakout Momentum",
    ],
    help="Algorithmic trading model to execute historically."
)

time_horizon = st.sidebar.selectbox(
    "Backtest Period",
    ["Last 1 Year", "Last 3 Years", "Last 5 Years", "Full Complete History"],
    index=1,
)

initial_capital = st.sidebar.number_input(
    "Initial Portfolio Capital (₹)",
    min_value=10000.0,
    max_value=100000000.0,
    value=100000.0,
    step=10000.0,
)

risk_pct = st.sidebar.slider("Risk Per Trade (% of Capital)", 0.5, 5.0, 2.0, 0.5)

# Calculate start date based on selection
today = pd.Timestamp.now()
if time_horizon == "Last 1 Year":
    start_date = (today - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
elif time_horizon == "Last 3 Years":
    start_date = (today - pd.DateOffset(years=3)).strftime("%Y-%m-%d")
elif time_horizon == "Last 5 Years":
    start_date = (today - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
else:
    start_date = None

# Run Backtest Button
if st.sidebar.button("🚀 Run Quantitative Backtest", type="primary", use_container_width=True):
    st.rerun()

# ── Execute Backtest ──────────────────────────────────────────────────────────
session = get_session(engine)
results = run_backtest(
    symbol=selected_symbol,
    strategy_name=strategy,
    session=session,
    start_date=start_date,
    end_date=None,
    initial_capital=initial_capital,
    risk_per_trade_pct=risk_pct,
)
session.close()

if "error" in results:
    st.error(results["error"])
    st.stop()

# ── Top KPI Metrics ───────────────────────────────────────────────────────────
st.header(f"📊 Backtest Results: {selected_symbol} | {strategy}")
st.caption(f"🗓️ Period: **{results['start_date']}** to **{results['end_date']}** | Initial Capital: **₹{initial_capital:,.0f}**")

kpi1, kpi2, kpi3, kpi4, kpi5, kpi6 = st.columns(6)

strat_ret = results["total_return_pct"]
bench_ret = results["benchmark_return_pct"]
alpha = results["alpha_pct"]

kpi1.metric("Final Portfolio", f"₹{results['final_equity']:,.0f}", f"Profit: ₹{results['net_profit']:+,.0f}")
kpi2.metric("Strategy Return", f"{strat_ret:+.2f}%", f"Alpha: {alpha:+.2f}% vs Buy&Hold", delta_color="normal")
kpi3.metric("Buy & Hold Return", f"{bench_ret:+.2f}%")
kpi4.metric("Win Rate", f"{results['win_rate_pct']:.1f}%", f"{results['total_trades']} Total Trades")
kpi5.metric("Profit Factor", f"{results['profit_factor']:.2f}", "Gross Win / Loss")
kpi6.metric("Max Drawdown", f"{results['max_drawdown_pct']:.2f}%", delta_color="inverse")

st.markdown("---")

# ── Equity Curve Chart ────────────────────────────────────────────────────────
st.subheader("📈 Equity Curve vs Buy & Hold Benchmark")

eq_df = pd.DataFrame(results["equity_curve"])
if not eq_df.empty:
    fig_eq = go.Figure()

    fig_eq.add_trace(go.Scatter(
        x=eq_df["date"],
        y=eq_df["strategy_equity"],
        mode="lines",
        name=f"Strategy: {strategy}",
        line=dict(color="#00c875", width=2.5),
    ))

    fig_eq.add_trace(go.Scatter(
        x=eq_df["date"],
        y=eq_df["benchmark_equity"],
        mode="lines",
        name="Buy & Hold Benchmark",
        line=dict(color="#6c757d", width=1.5, dash="dot"),
    ))

    fig_eq.update_layout(
        height=450,
        paper_bgcolor="#0e1117",
        plot_bgcolor="#1a1d23",
        font=dict(color="#e0e0e0"),
        xaxis=dict(gridcolor="#2d3139", title="Date"),
        yaxis=dict(gridcolor="#2d3139", title="Portfolio Value (₹)"),
        legend=dict(orientation="h", y=1.05),
        margin=dict(l=40, r=40, t=30, b=40),
    )
    st.plotly_chart(fig_eq, use_container_width=True)

# ── Advanced Statistical Ratios ───────────────────────────────────────────────
st.subheader("📐 Risk-Adjusted Return Metrics")
r1, r2, r3, r4, r5 = st.columns(5)
r1.metric("Sharpe Ratio", f"{results['sharpe_ratio']:.2f}", help="Risk-adjusted return vs volatility (>1.0 is solid, >2.0 is elite)")
r2.metric("Sortino Ratio", f"{results['sortino_ratio']:.2f}", help="Downside risk-adjusted return")
r3.metric("Avg Winning Trade", f"{results['avg_win_pct']:+.2f}%")
r4.metric("Avg Losing Trade", f"{results['avg_loss_pct']:+.2f}%")
r5.metric("Avg Holding Period", f"{results['avg_holding_days']:.0f} Days")

st.markdown("---")

# ── Detailed Trade Log ────────────────────────────────────────────────────────
st.subheader(f"📋 Complete Trade-by-Trade Execution Log ({len(results['trade_log'])} Trades)")

trade_log = results["trade_log"]
if trade_log:
    trades_df = pd.DataFrame(trade_log)

    def color_pnl(val):
        try:
            v = float(val)
            if v > 0: return "color: #00c875; font-weight: bold"
            elif v < 0: return "color: #e04b4b; font-weight: bold"
        except: pass
        return ""

    def color_status(val):
        if val == "WIN": return "background-color: #1a4d2e; color: #00c875"
        elif val == "LOSS": return "background-color: #4d1a1a; color: #ff6b6b"
        return ""

    display_trades = trades_df[[
        "status", "entry_date", "exit_date", "entry_price", "exit_price",
        "shares", "pnl", "return_pct", "holding_days", "exit_reason"
    ]].rename(columns={
        "status": "Result",
        "entry_date": "Entry Date",
        "exit_date": "Exit Date",
        "entry_price": "Entry Price (₹)",
        "exit_price": "Exit Price (₹)",
        "shares": "Quantity",
        "pnl": "Net P&L (₹)",
        "return_pct": "Return %",
        "holding_days": "Days Held",
        "exit_reason": "Exit Trigger"
    })

    st.dataframe(
        display_trades.style
            .map(color_status, subset=["Result"])
            .map(color_pnl, subset=["Net P&L (₹)", "Return %"])
            .format({
                "Entry Price (₹)": "₹{:,.2f}",
                "Exit Price (₹)": "₹{:,.2f}",
                "Quantity": "{:,}",
                "Net P&L (₹)": "₹{:+,.2f}",
                "Return %": "{:+.2f}%",
                "Days Held": "{:.0f}",
            }),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No trades were triggered during this historical timeframe under the selected strategy rules.")
