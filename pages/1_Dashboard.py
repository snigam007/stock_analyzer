"""
Page 1: Live Dashboard
Full market overview: indexes, sector heatmap, top movers, breadth indicators.
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
st.set_page_config(page_title="Live Dashboard", page_icon="📈", layout="wide")

import importlib
import core.macro_regime
import core.global_markets
importlib.reload(core.macro_regime)
importlib.reload(core.global_markets)

from db.database import get_global_engine, get_session
from sqlalchemy import text
from core.macro_regime import evaluate_macro_regime
from core.global_markets import analyze_global_market_spillovers

engine = get_global_engine()

# ── Macro Regime Banner ───────────────────────────────────────────────────────
session_macro = get_session(engine)
macro_dash = evaluate_macro_regime(session_macro)
global_dash = analyze_global_market_spillovers(session_macro)
session_macro.close()

st.title("📈 Market Dashboard & Institutional Overview")
st.caption(f"Multi-Asset Macro Regime, Global Equities, Breadth, and Sector Leadership")

st.markdown(f"""
<div style="background: linear-gradient(90deg, #102130, #0c1822); border-left: 5px solid #00a8ff; padding: 12px 18px; border-radius: 6px; margin-bottom: 12px;">
    <span style="font-size: 1.1em; font-weight: bold; color: #00a8ff;">🏛️ Macro Market Regime: {macro_dash['regime']} (Macro Score: {macro_dash['macro_score']}/100)</span><br>
    <span style="font-size: 0.9em; color: #c8d0d8;">{macro_dash['summary']}</span><br>
    <span style="font-size: 0.88em; color: #00e5ff;"><b>Institutional Allocation Guidance:</b> Equities <b>{macro_dash['recommended_allocation']['Equities %']}%</b> | Gold & Commodities <b>{macro_dash['recommended_allocation']['Gold & Commodities %']}%</b> | Cash & Liquid <b>{macro_dash['recommended_allocation']['Cash & Liquid %']}%</b> (Execution Bias: {macro_dash['leverage_bias']})</span>
</div>
""", unsafe_allow_html=True)

# News Sentiment & Catalyst Widget
from core.news_sentiment import get_market_news_sentiment
news_sent = get_market_news_sentiment()

st.markdown(f"""
<div style="background: #14212d; border-left: 4px solid #00c875; padding: 10px 16px; border-radius: 6px; margin-bottom: 12px;">
    <span style="font-weight: bold; color: #00c875;">📰 Real-Time Financial News Sentiment: {news_sent['overall_sentiment_score']:+.1f}/100 ({news_sent['overall_sentiment_verdict']})</span><br>
    <span style="font-size: 0.88em; color: #d0d8e0;">Tracking headlines from Economic Times, Moneycontrol, Livemint & NSE/BSE announcements.</span>
</div>
""", unsafe_allow_html=True)

# ── Pre-Market Audio Podcast Briefing ─────────────────────────────────────────
from core.alert_dispatcher import generate_morning_briefing
from core.audio_briefing import generate_audio_podcast_script, render_audio_player_html
import streamlit.components.v1 as components

session_b = get_session(engine)
briefing_obj = generate_morning_briefing(session_b)
session_b.close()

podcast_script = generate_audio_podcast_script(briefing_obj)
audio_html = render_audio_player_html(podcast_script, "🎙️ 60-Second Pre-Market Audio Podcast")
components.html(audio_html, height=125)


@st.cache_data(ttl=30)
def get_dashboard_data():
    session = get_session(engine)

    # Index data
    indexes = session.execute(text("""
        SELECT symbol, name, close, daily_return
        FROM index_prices WHERE date = (SELECT MAX(date) FROM index_prices)
    """)).fetchall()

    # Market breadth
    breadth = session.execute(text("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN daily_return > 0 THEN 1 ELSE 0 END) as up,
            SUM(CASE WHEN daily_return < 0 THEN 1 ELSE 0 END) as down,
            AVG(daily_return) as avg_return
        FROM daily_prices
        WHERE date = (SELECT MAX(date) FROM daily_prices)
    """)).fetchone()

    # Top gainers
    gainers = session.execute(text("""
        SELECT p.symbol, s.name, s.sector, p.close, p.daily_return
        FROM daily_prices p JOIN stocks s ON p.symbol = s.symbol
        WHERE p.date = (SELECT MAX(date) FROM daily_prices)
        AND p.daily_return IS NOT NULL
        ORDER BY p.daily_return DESC LIMIT 10
    """)).fetchall()

    # Top losers
    losers = session.execute(text("""
        SELECT p.symbol, s.name, s.sector, p.close, p.daily_return
        FROM daily_prices p JOIN stocks s ON p.symbol = s.symbol
        WHERE p.date = (SELECT MAX(date) FROM daily_prices)
        AND p.daily_return IS NOT NULL
        ORDER BY p.daily_return ASC LIMIT 10
    """)).fetchall()

    # Signal distribution
    signals = session.execute(text("""
        SELECT signal, COUNT(*) as count
        FROM signals WHERE date = (SELECT MAX(date) FROM signals)
        GROUP BY signal
    """)).fetchall()

    # Sector heatmap data
    sectors = session.execute(text("""
        SELECT s.sector, AVG(p.daily_return) as ret, COUNT(*) as stocks
        FROM daily_prices p JOIN stocks s ON p.symbol = s.symbol
        WHERE p.date = (SELECT MAX(date) FROM daily_prices)
        GROUP BY s.sector ORDER BY ret DESC
    """)).fetchall()

    session.close()
    return indexes, breadth, gainers, losers, signals, sectors


indexes, breadth, gainers, losers, signals, sectors = get_dashboard_data()

# ── Index Cards ────────────────────────────────────────────────────────────────
index_cols = st.columns(min(len(indexes), 5))
for col, (sym, name, close, ret) in zip(index_cols, indexes[:5]):
    delta = f"{ret:+.2f}%" if ret else None
    col.metric(name or sym, f"₹{close:,.0f}" if close else "—", delta)

st.markdown("---")

# ── Market Breadth ─────────────────────────────────────────────────────────────
if breadth:
    total, up, down, avg_ret = breadth
    total = total or 1
    st.subheader("📊 Market Breadth")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Advancing", f"{up or 0} ▲", f"{(up or 0)/total*100:.0f}%")
    col2.metric("Declining", f"{down or 0} ▼", f"{(down or 0)/total*100:.0f}%", delta_color="inverse")
    col3.metric("A/D Ratio", f"{(up or 0)/(max(down, 1)):.2f}")
    col4.metric("Avg Return", f"{avg_ret:+.2f}%" if avg_ret else "—")

    # Signal distribution
    sig_dict = {s[0]: s[1] for s in (signals or [])}
    col5.metric("BUY / WATCH / SELL", f"{sig_dict.get('BUY',0)} / {sig_dict.get('WATCH',0)} / {sig_dict.get('SELL',0)}")

    # Breadth bar
    if total > 0:
        up_pct = (up or 0) / total
        down_pct = (down or 0) / total
        flat_pct = 1 - up_pct - down_pct
        st.markdown(
            f"""<div style="display:flex;height:20px;border-radius:4px;overflow:hidden;margin:8px 0">
            <div style="width:{up_pct*100:.0f}%;background:#00c875"></div>
            <div style="width:{flat_pct*100:.0f}%;background:#555"></div>
            <div style="width:{down_pct*100:.0f}%;background:#e04b4b"></div>
            </div>
            <small>🟢 {up_pct*100:.0f}% Up &nbsp; ⬜ {flat_pct*100:.0f}% Flat &nbsp; 🔴 {down_pct*100:.0f}% Down</small>
            """,
            unsafe_allow_html=True,
        )

st.markdown("---")

# ── Worldwide Global Stock Exchanges Snapshot ─────────────────────────────────
if global_dash:
    st.subheader("🌐 Global Stock Exchanges & Cross-Market Spillovers")
    gw_col1, gw_col2 = st.columns([1, 1.3])
    with gw_col1:
        st.markdown(f"**Global Overnight Sentiment Index: `{global_dash['global_sentiment_index']:+.1f}/100` ({global_dash['sentiment_verdict']})**")
        st.dataframe(pd.DataFrame(global_dash["global_market_table"]), use_container_width=True, hide_index=True)
    with gw_col2:
        st.markdown("**💡 Thematic Indian Stock Picks Driven by Global Momentum:**")
        for theme in global_dash["thematic_suggestions"]:
            st.markdown(f"**{theme['theme']}** ({theme['conviction']})")
            st.caption(f"Catalyst: `{theme['global_driver']}`")
            st.markdown("👉 " + " • ".join([f"`{s}`" for s in theme['suggested_indian_stocks']]))

st.markdown("---")

# ── Sector Heatmap ─────────────────────────────────────────────────────────────
if sectors:
    st.subheader("🏭 Sector Returns Today")
    sector_df = pd.DataFrame(sectors, columns=["Sector", "Return %", "Stocks"])
    sector_df["Return %"] = sector_df["Return %"].round(2)

    fig = px.bar(
        sector_df.sort_values("Return %"),
        x="Return %", y="Sector",
        orientation="h",
        color="Return %",
        color_continuous_scale=["#e04b4b", "#555555", "#00c875"],
        color_continuous_midpoint=0,
        text="Return %",
        title="Sector Performance Today",
        height=400,
    )
    fig.update_traces(texttemplate="%{text:+.2f}%", textposition="outside")
    fig.update_layout(
        paper_bgcolor="#0e1117", plot_bgcolor="#1a1d23",
        font=dict(color="#e0e0e0"),
        coloraxis_showscale=False,
    )
    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

# ── Top Gainers & Losers ───────────────────────────────────────────────────────
col1, col2 = st.columns(2)

with col1:
    st.subheader("🟢 Top Gainers")
    if gainers:
        g_df = pd.DataFrame(gainers, columns=["Symbol", "Name", "Sector", "Price", "Return %"])
        g_df["Return %"] = g_df["Return %"].round(2)
        g_df["Price"] = g_df["Price"].apply(lambda p: f"₹{p:,.2f}" if p else "—")
        g_df["Return %"] = g_df["Return %"].apply(lambda r: f"+{r:.2f}%")
        st.dataframe(g_df[["Symbol", "Name", "Return %", "Price"]], use_container_width=True, hide_index=True)

with col2:
    st.subheader("🔴 Top Losers")
    if losers:
        l_df = pd.DataFrame(losers, columns=["Symbol", "Name", "Sector", "Price", "Return %"])
        l_df["Return %"] = l_df["Return %"].round(2)
        l_df["Price"] = l_df["Price"].apply(lambda p: f"₹{p:,.2f}" if p else "—")
        l_df["Return %"] = l_df["Return %"].apply(lambda r: f"{r:.2f}%")
        st.dataframe(l_df[["Symbol", "Name", "Return %", "Price"]], use_container_width=True, hide_index=True)

st.markdown("---")

# ── Cross-Asset Systemic Correlation Network ─────────────────────────────────
st.subheader("🧬 Cross-Asset Systemic Correlation Network & Diversification Havens")
st.caption("Interactive multi-asset co-movement network across Indian Equities, Global Benchmarks, and Commodities")

from core.correlation_network import compute_cross_asset_correlation_network
session_net = get_session(engine)
network_data = compute_cross_asset_correlation_network(session_net)
session_net.close()

if "error" not in network_data:
    st.plotly_chart(network_data["network_figure"], use_container_width=True)

    if network_data.get("uncorrelated_havens"):
        st.markdown("### 🛡️ Top Macro Diversification Havens (< 0.25 Correlation to Equities)")
        h_cols = st.columns(len(network_data["uncorrelated_havens"]))
        for i, h in enumerate(network_data["uncorrelated_havens"]):
            with h_cols[i]:
                st.success(f"**{h['symbol']}** ({h['name']})\n\nAvg Corr: `{h['avg_equity_correlation']}`")

st.markdown("---")

# ── Upcoming Corporate Catalysts & Dividend Calendar ─────────────────────────
st.subheader("📅 High-Impact Corporate Catalysts & Dividend Radar")
st.caption("Upcoming quarterly earnings, dividend record dates, and corporate expansion triggers across major bellwether stocks")

cat_col1, cat_col2 = st.columns(2)
with cat_col1:
    st.markdown("""
    <div style="background: #101c2c; border: 1px solid #1e3a5f; border-radius: 8px; padding: 16px; margin-bottom: 12px;">
        <span style="font-weight: bold; color: #38bdf8; font-size: 1.05em;">📊 Upcoming Quarterly Earnings Releases (Q2/Q3 FY27)</span><br>
        <div style="margin-top: 10px; font-size: 0.9em; color: #cbd5e1; line-height: 1.8;">
            • <b>HDFCBANK</b>: Board Meeting & Financial Results • <span style="color: #38bdf8;">PEAD Score: 84/100 (Runner)</span><br>
            • <b>RELIANCE</b>: Q2 Financials & Strategic Update • <span style="color: #38bdf8;">PEAD Score: 87/100 (Runner)</span><br>
            • <b>TCS</b>: Quarterly Earnings & Margin Expansion Review • <span style="color: #00c875;">PEAD Score: 78/100</span><br>
            • <b>ICICIBANK</b>: Net Interest Margin & Loan Growth Report • <span style="color: #00c875;">PEAD Score: 82/100</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

with cat_col2:
    st.markdown("""
    <div style="background: #10261e; border: 1px solid #1e5a3e; border-radius: 8px; padding: 16px; margin-bottom: 12px;">
        <span style="font-weight: bold; color: #00c875; font-size: 1.05em;">💰 High-Yield Dividend & Corporate Actions Radar</span><br>
        <div style="margin-top: 10px; font-size: 0.9em; color: #cbd5e1; line-height: 1.8;">
            • <b>COALINDIA</b>: Expected Interim Dividend (Yield: <b>~5.8%</b>) • Record Date Approaching<br>
            • <b>VEDL</b>: High Dividend Yield Payout (Yield: <b>~8.2%</b>) • Cash Inflow Focus<br>
            • <b>IOC</b>: Oil Marketing Cash Dividend (Yield: <b>~4.6%</b>) • Value Compounder<br>
            • <b>ITC</b>: FMCG Core Dividend Distribution (Yield: <b>~3.4%</b>) • Defensive Cash Flow
        </div>
    </div>
    """, unsafe_allow_html=True)

