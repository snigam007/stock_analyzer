"""
Main Streamlit App — Indian Stock Market Analyzer
Landing page: Market overview cards, top movers, and navigation.
"""
import sys
from pathlib import Path

import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config.settings import APP_TITLE, APP_VERSION, DISCLAIMER

# ─── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title=APP_TITLE,
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": f"Indian Stock Market Analyzer v{APP_VERSION}",
    },
)

# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Dark professional theme */
    [data-testid="stSidebar"] { background-color: #0e1117; }
    .main { background-color: #0e1117; }

    /* Metric cards */
    div[data-testid="metric-container"] {
        background-color: #1e2329;
        border: 1px solid #2d3139;
        border-radius: 8px;
        padding: 12px 16px;
    }

    /* Signal badges */
    .signal-buy {
        background-color: #00c875; color: #000;
        padding: 4px 12px; border-radius: 20px;
        font-weight: bold; font-size: 0.85em;
    }
    .signal-sell {
        background-color: #e04b4b; color: #fff;
        padding: 4px 12px; border-radius: 20px;
        font-weight: bold; font-size: 0.85em;
    }
    .signal-watch {
        background-color: #f0a500; color: #000;
        padding: 4px 12px; border-radius: 20px;
        font-weight: bold; font-size: 0.85em;
    }
    .risk-safe {
        background-color: #1a6b3c; color: #fff;
        padding: 2px 10px; border-radius: 12px; font-size: 0.75em;
    }
    .risk-moderate {
        background-color: #8b6914; color: #fff;
        padding: 2px 10px; border-radius: 12px; font-size: 0.75em;
    }
    .risk-risky {
        background-color: #6b1a1a; color: #fff;
        padding: 2px 10px; border-radius: 12px; font-size: 0.75em;
    }

    /* Disclaimer */
    .disclaimer-box {
        background-color: #1a1a2e; border-left: 4px solid #f0a500;
        padding: 10px 16px; border-radius: 4px; font-size: 0.8em; color: #aaa;
    }

    /* Trend pattern */
    .trend-up { color: #00c875; font-weight: bold; }
    .trend-down { color: #e04b4b; font-weight: bold; }

    /* Section headers */
    .section-header {
        font-size: 1.1em; font-weight: 600; color: #e0e0e0;
        border-bottom: 1px solid #2d3139; padding-bottom: 6px; margin-bottom: 12px;
    }
</style>
""", unsafe_allow_html=True)


def render_signal_badge(signal: str) -> str:
    cls = {"BUY": "signal-buy", "SELL": "signal-sell", "WATCH": "signal-watch"}.get(signal, "signal-watch")
    icon = {"BUY": "🟢", "SELL": "🔴", "WATCH": "🟡"}.get(signal, "🟡")
    return f'<span class="{cls}">{icon} {signal}</span>'


def render_risk_badge(risk: str) -> str:
    cls = {"SAFE": "risk-safe", "MODERATE": "risk-moderate", "RISKY": "risk-risky"}.get(risk, "risk-moderate")
    icon = {"SAFE": "🛡️", "MODERATE": "⚖️", "RISKY": "⚡"}.get(risk, "⚖️")
    return f'<span class="{cls}">{icon} {risk}</span>'


def format_price(price) -> str:
    if price is None:
        return "—"
    return f"₹{price:,.2f}"


def format_pct(pct) -> str:
    if pct is None:
        return "—"
    color = "green" if pct > 0 else "red"
    sign = "+" if pct > 0 else ""
    return f'<span style="color:{color}">{sign}{pct:.2f}%</span>'


# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"## 📊 {APP_TITLE}")
    st.markdown(f"*Version {APP_VERSION}*")
    st.markdown("---")

    st.markdown("### 🗂️ Navigation")
    st.page_link("main.py", label="🏠 Market Overview")
    st.page_link("pages/1_Dashboard.py", label="📈 Live Dashboard")
    st.page_link("pages/2_Stock_Analysis.py", label="🔍 Stock Analysis")
    st.page_link("pages/3_Sector_Analysis.py", label="🏭 Sector Analysis")
    st.page_link("pages/4_Daily_Top_Stocks.py", label="🏆 Daily Top Stocks")
    st.page_link("pages/5_Trends.py", label="📉 Trend Forecasts")
    st.page_link("pages/6_Strategies.py", label="💼 Strategies")
    st.page_link("pages/7_Backtesting.py", label="🧪 Strategy Backtesting")

    st.markdown("---")
    st.markdown(f'<div class="disclaimer-box">{DISCLAIMER}</div>', unsafe_allow_html=True)


# ─── Main Page ────────────────────────────────────────────────────────────────
st.title("📊 Indian Stock Market Analyzer")
st.markdown("*Comprehensive BSE/NSE Analysis — Stocks · Sectors · Commodities · Indexes*")

# Disclaimer
st.markdown(f'<div class="disclaimer-box">{DISCLAIMER}</div>', unsafe_allow_html=True)
st.markdown("")

# Check if DB is initialized
try:
    from db.database import get_global_engine, get_session
    from sqlalchemy import text

    engine = get_global_engine()
    session = get_session(engine)

    stock_count = session.execute(text("SELECT COUNT(*) FROM stocks WHERE is_active=1")).scalar()
    price_count = session.execute(text("SELECT COUNT(*) FROM daily_prices")).scalar()
    signal_count = session.execute(text("SELECT COUNT(*) FROM signals WHERE date = (SELECT MAX(date) FROM signals)")).scalar()

    if stock_count == 0:
        st.warning("⚠️ Database not initialized. Please run `python initialize.py` first.")
        st.code("python initialize.py", language="bash")
        st.stop()

    # ── Data Summary Cards ────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📋 Stocks Tracked", f"{stock_count:,}")
    with col2:
        st.metric("📅 Price Records", f"{price_count:,.0f}")
    with col3:
        st.metric("🚦 Today's Signals", f"{signal_count:,}")
    with col4:
        last_date = session.execute(text("SELECT MAX(date) FROM daily_prices")).scalar()
        st.metric("🕐 Last Updated", str(last_date) if last_date else "Never")

    st.markdown("---")

    # ── Quick Market Snapshot ─────────────────────────────────────────────────
    st.subheader("🌐 Market Snapshot")

    col1, col2, col3 = st.columns(3)

    indexes = [
        ("^NSEI", "NIFTY 50"),
        ("^BSESN", "BSE SENSEX"),
        ("^NSEBANK", "NIFTY Bank"),
    ]

    for col, (sym, name) in zip([col1, col2, col3], indexes):
        with col:
            result = session.execute(text("""
                SELECT close, daily_return FROM index_prices
                WHERE symbol = :s ORDER BY date DESC LIMIT 1
            """), {"s": sym}).fetchone()
            if result:
                close, ret = result
                delta_str = f"{ret:+.2f}%" if ret else "N/A"
                st.metric(label=name, value=f"₹{close:,.0f}" if close else "N/A", delta=delta_str)
            else:
                st.metric(label=name, value="No data")

    st.markdown("")

    # ── Today's Top Signals ───────────────────────────────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown('<p class="section-header">🟢 Top BUY Signals Today</p>', unsafe_allow_html=True)
        top_buys = session.execute(text("""
            SELECT sig.symbol, s.name, s.sector, sig.current_price,
                   sig.target_price_1, sig.stop_loss, sig.risk_level, sig.key_reason,
                   cs.composite_score, ind.trend_pattern
            FROM signals sig
            JOIN stocks s ON sig.symbol = s.symbol
            JOIN composite_scores cs ON sig.symbol = cs.symbol AND sig.date = cs.date
            LEFT JOIN technical_indicators ind ON sig.symbol = ind.symbol AND sig.date = ind.date
            WHERE sig.signal = 'BUY'
            AND sig.date = (SELECT MAX(date) FROM signals)
            ORDER BY cs.composite_score DESC
            LIMIT 8
        """)).fetchall()

        for row in top_buys:
            sym, name, sector, price, t1, sl, risk, reason, score, trend = row
            with st.expander(f"**{sym}** — {name[:30]} | Score: {score:.0f}"):
                c1, c2, c3 = st.columns(3)
                c1.metric("Price", format_price(price))
                c2.metric("Target 1", format_price(t1))
                c3.metric("Stop Loss", format_price(sl))
                st.markdown(f"**Trend:** {trend or '—'} | {render_risk_badge(risk or 'MODERATE')}", unsafe_allow_html=True)
                st.caption(f"💡 {reason or 'N/A'}")

    with col_right:
        st.markdown('<p class="section-header">🔴 Top SELL Signals Today</p>', unsafe_allow_html=True)
        top_sells = session.execute(text("""
            SELECT sig.symbol, s.name, s.sector, sig.current_price,
                   sig.target_price_1, sig.stop_loss, sig.risk_level, sig.key_reason,
                   cs.composite_score, ind.trend_pattern
            FROM signals sig
            JOIN stocks s ON sig.symbol = s.symbol
            JOIN composite_scores cs ON sig.symbol = cs.symbol AND sig.date = cs.date
            LEFT JOIN technical_indicators ind ON sig.symbol = ind.symbol AND sig.date = ind.date
            WHERE sig.signal = 'SELL'
            AND sig.date = (SELECT MAX(date) FROM signals)
            ORDER BY cs.composite_score ASC
            LIMIT 8
        """)).fetchall()

        for row in top_sells:
            sym, name, sector, price, t1, sl, risk, reason, score, trend = row
            with st.expander(f"**{sym}** — {name[:30]} | Score: {score:.0f}"):
                c1, c2, c3 = st.columns(3)
                c1.metric("Price", format_price(price))
                c2.metric("Target (Down)", format_price(t1))
                c3.metric("Stop Loss", format_price(sl))
                st.markdown(f"**Trend:** {trend or '—'} | {render_risk_badge(risk or 'MODERATE')}", unsafe_allow_html=True)
                st.caption(f"💡 {reason or 'N/A'}")

    st.markdown("---")

    # ── Commodity Snapshot ────────────────────────────────────────────────────
    st.subheader("🏅 Commodities")
    comm_cols = st.columns(6)
    commodities = [
        ("GC=F", "Gold"), ("SI=F", "Silver"), ("CL=F", "Crude"),
        ("NG=F", "Nat Gas"), ("HG=F", "Copper"), ("GOLDBEES.NS", "Gold ETF")
    ]
    for col, (sym, name) in zip(comm_cols, commodities):
        with col:
            result = session.execute(text("""
                SELECT close, daily_return FROM commodity_prices
                WHERE symbol=:s ORDER BY date DESC LIMIT 1
            """), {"s": sym}).fetchone()
            if result:
                close, ret = result
                col.metric(name, f"${close:,.1f}" if close else "—",
                           f"{ret:+.2f}%" if ret else None)

    session.close()

except Exception as e:
    st.error(f"❌ Database error: {e}")
    st.info("Run `python initialize.py` to set up the database.")
    st.code("python initialize.py", language="bash")
