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

# ── Live Market Pulse Breadth Bar ─────────────────────────────────────────────
@st.cache_data(ttl=60)
def get_market_pulse():
    sess = get_session(engine)
    try:
        # Nifty 50 + Bank Nifty
        def get_idx(sym):
            rows = sess.execute(text(
                "SELECT close FROM index_prices WHERE symbol=:s ORDER BY date DESC LIMIT 2"
            ), {"s": sym}).fetchall()
            if len(rows) >= 2:
                curr, prev = float(rows[0][0]), float(rows[1][0])
                return curr, (curr - prev) / prev * 100
            return None, None

        nifty_lvl, nifty_chg   = get_idx("^NSEI")
        bnifty_lvl, bnifty_chg = get_idx("^NSEBANK")
        vix_lvl, _              = get_idx("^INDIAVIX")
        if vix_lvl is None:
            vix_row = sess.execute(text(
                "SELECT close FROM index_prices WHERE symbol LIKE '%VIX%' ORDER BY date DESC LIMIT 1"
            )).scalar()
            vix_lvl = float(vix_row) if vix_row else None

        # Market breadth from daily_prices today
        latest_date = sess.execute(text("SELECT MAX(date) FROM daily_prices")).scalar()
        breadth = sess.execute(text("""
            SELECT
              SUM(CASE WHEN close > open THEN 1 ELSE 0 END) as adv,
              SUM(CASE WHEN close <= open THEN 1 ELSE 0 END) as dec
            FROM daily_prices WHERE date = :d
        """), {"d": latest_date}).fetchone()
        adv, dec = (int(breadth[0] or 0), int(breadth[1] or 0)) if breadth else (0, 0)

        # BUY signals today
        sig_date = sess.execute(text("SELECT MAX(date) FROM signals")).scalar()
        buy_cnt = sess.execute(text(
            "SELECT COUNT(*) FROM signals WHERE date=:d AND signal='BUY'"
        ), {"d": sig_date}).scalar() or 0
        sell_cnt = sess.execute(text(
            "SELECT COUNT(*) FROM signals WHERE date=:d AND signal='SELL'"
        ), {"d": sig_date}).scalar() or 0

        return {
            "nifty_lvl": nifty_lvl, "nifty_chg": nifty_chg,
            "bnifty_lvl": bnifty_lvl, "bnifty_chg": bnifty_chg,
            "vix_lvl": vix_lvl, "adv": adv, "dec": dec,
            "buy_cnt": buy_cnt, "sell_cnt": sell_cnt,
            "ad_ratio": adv / max(1, adv + dec),
        }
    except Exception:
        return {}
    finally:
        sess.close()

pulse = get_market_pulse()

def _delta_color(chg):
    if chg is None: return "#888"
    return "#00c875" if chg >= 0 else "#ff4b4b"

def _arrow(chg):
    if chg is None: return ""
    return "▲" if chg >= 0 else "▼"

if pulse:
    vix = pulse.get("vix_lvl")
    vix_color = "#ff4b4b" if (vix and vix > 22) else ("#f0c040" if (vix and vix > 15) else "#00c875")
    ad = pulse.get("ad_ratio", 0.5)
    ad_color = "#00c875" if ad >= 0.55 else ("#ff4b4b" if ad < 0.40 else "#f0c040")
    nc, bc = _delta_color(pulse.get("nifty_chg")), _delta_color(pulse.get("bnifty_chg"))
    na, ba = _arrow(pulse.get("nifty_chg")), _arrow(pulse.get("bnifty_chg"))

    st.markdown(f"""
<div style="display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap;">
  <div style="flex:1;min-width:130px;background:#0d1f2d;border:1px solid #1e3a52;border-radius:8px;padding:10px 14px;text-align:center;">
    <div style="color:#8ab4d0;font-size:0.75em;font-weight:600;letter-spacing:1px;">NIFTY 50</div>
    <div style="color:#e8f0f8;font-size:1.3em;font-weight:700;">{f'{pulse["nifty_lvl"]:,.0f}' if pulse.get("nifty_lvl") else '—'}</div>
    <div style="color:{nc};font-size:0.85em;font-weight:600;">{na} {f'{pulse["nifty_chg"]:+.2f}%' if pulse.get("nifty_chg") is not None else '—'}</div>
  </div>
  <div style="flex:1;min-width:130px;background:#0d1f2d;border:1px solid #1e3a52;border-radius:8px;padding:10px 14px;text-align:center;">
    <div style="color:#8ab4d0;font-size:0.75em;font-weight:600;letter-spacing:1px;">BANK NIFTY</div>
    <div style="color:#e8f0f8;font-size:1.3em;font-weight:700;">{f'{pulse["bnifty_lvl"]:,.0f}' if pulse.get("bnifty_lvl") else '—'}</div>
    <div style="color:{bc};font-size:0.85em;font-weight:600;">{ba} {f'{pulse["bnifty_chg"]:+.2f}%' if pulse.get("bnifty_chg") is not None else '—'}</div>
  </div>
  <div style="flex:1;min-width:130px;background:#0d1f2d;border:1px solid #1e3a52;border-radius:8px;padding:10px 14px;text-align:center;">
    <div style="color:#8ab4d0;font-size:0.75em;font-weight:600;letter-spacing:1px;">INDIA VIX</div>
    <div style="color:{vix_color};font-size:1.3em;font-weight:700;">{f'{vix:.2f}' if vix else '—'}</div>
    <div style="color:{vix_color};font-size:0.82em;">{'⚠️ High Fear' if vix and vix > 22 else ('🟡 Elevated' if vix and vix > 15 else '🟢 Calm')}</div>
  </div>
  <div style="flex:1;min-width:130px;background:#0d1f2d;border:1px solid #1e3a52;border-radius:8px;padding:10px 14px;text-align:center;">
    <div style="color:#8ab4d0;font-size:0.75em;font-weight:600;letter-spacing:1px;">ADVANCE / DECLINE</div>
    <div style="color:{ad_color};font-size:1.3em;font-weight:700;">{pulse.get("adv",0)}↑ / {pulse.get("dec",0)}↓</div>
    <div style="color:{ad_color};font-size:0.82em;">A/D Ratio: {ad:.0%}</div>
  </div>
  <div style="flex:1;min-width:130px;background:#0d1f2d;border:1px solid #1e3a52;border-radius:8px;padding:10px 14px;text-align:center;">
    <div style="color:#8ab4d0;font-size:0.75em;font-weight:600;letter-spacing:1px;">TODAY'S SIGNALS</div>
    <div style="color:#e8f0f8;font-size:1.3em;font-weight:700;">🟢 {pulse.get("buy_cnt",0)} BUY</div>
    <div style="color:#ff4b4b;font-size:0.85em;font-weight:600;">🔴 {pulse.get("sell_cnt",0)} SELL</div>
  </div>
</div>
""", unsafe_allow_html=True)

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

# ── Terminal AI Quant Copilot Console ─────────────────────────────────────────
with st.expander("🤖 **Terminal AI Quant Copilot & Market Diagnostician**", expanded=False):
    st.caption("Ask natural language queries to scan the universe, diagnose market anomalies, and generate structured institutional trade ideas.")
    
    from core.quant_copilot import answer_quant_copilot_query
    
    copilot_c1, copilot_c2 = st.columns([3, 1])
    with copilot_c1:
        user_query = st.text_input(
            "Enter market inquiry / screening directive:",
            value="Show me top oversold quality stocks with strong buy signal",
            placeholder="e.g. Find high Piotroski banking stocks or top oversold dip candidates"
        )
    with copilot_c2:
        st.markdown("<br>", unsafe_allow_html=True)
        run_copilot = st.button("🔎 Run AI Query", type="primary", use_container_width=True)

    if user_query:
        session_copilot = get_session(engine)
        ai_resp = answer_quant_copilot_query(user_query, session_copilot)
        session_copilot.close()

        st.markdown(ai_resp["response"])
        if ai_resp.get("has_data") and not ai_resp["table"].empty:
            st.dataframe(ai_resp["table"], use_container_width=True, hide_index=True)



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

st.markdown("---")

# ── Global Macro Transmission Matrix & Yield Curve Monitor ───────────────────
st.subheader("🌐 Global Macro Transmission Matrix & Yield Curve Monitor")
st.caption("Inter-market elasticity modeling linking US/India Yields, USD/INR, Brent Crude, and Gold to Sector Tailwinds")

from core.macro_transmission import compute_macro_transmission_dashboard
macro_tx = compute_macro_transmission_dashboard()

mx1, mx2, mx3, mx4 = st.columns(4)
mx1.metric("India 10Y Yield", f"{macro_tx['india_10y_yield']:.2f}%", f"US 10Y: {macro_tx['us_10y_yield']:.2f}%")
mx2.metric("Yield Spread (IN - US)", f"{macro_tx['yield_spread']:+.2f}%", macro_tx['fii_badge'])
mx3.metric("Yield Curve Slope", f"{macro_tx['yc_slope']:+.2f}%", macro_tx['yc_regime'])
mx4.metric("USD / INR Rate", f"₹{macro_tx['usd_inr']:.2f}", f"Crude: ${macro_tx['brent_crude']:.1f}/bbl")

with st.expander("📊 **Sector Macro Sensitivity & Elasticity Matrix**", expanded=False):
    df_tx = pd.DataFrame(macro_tx["sector_matrix"])
    st.dataframe(
        df_tx[["sector", "net_macro_score", "macro_status", "usd_inr_beta", "crude_beta", "rate_beta", "catalyst"]].rename(columns={
            "sector": "Sector",
            "net_macro_score": "Macro Score",
            "macro_status": "Regime Impact",
            "usd_inr_beta": "USD/INR Beta",
            "crude_beta": "Crude Beta",
            "rate_beta": "Rate Beta",
            "catalyst": "Primary Macro Transmission Driver"
        }).style.format({
            "Macro Score": "{:+.1f}",
            "USD/INR Beta": "{:+.2f}",
            "Crude Beta": "{:+.2f}",
            "Rate Beta": "{:+.2f}",
        }),
        use_container_width=True,
        hide_index=True
    )

st.markdown("---")

# ── Financial News Sentiment Velocity & NLP Catalyst Radar ───────────────────
st.subheader("📰 Live Financial News Sentiment Velocity & Catalyst Radar")
st.caption("Real-time natural language sentiment scoring (NLP) and catalyst categorization across Indian corporate headlines")

from core.news_sentiment_nlp import fetch_live_news_sentiment_radar
news_radar = fetch_live_news_sentiment_radar()

nr1, nr2, nr3 = st.columns([1, 1, 2])
nr1.metric("Avg Sentiment Score", f"{news_radar['avg_sentiment_score']}/100", news_radar['regime_badge'])
nr2.metric("Sentiment Velocity", news_radar['sentiment_velocity'], "Surging Momentum")
nr3.markdown(f"**Market Sentiment Regime:** `{news_radar['overall_regime']}`")

for item in news_radar["headlines"]:
    s_col = "#00c875" if item["sentiment_score"] > 0 else "#ff4b4b"
    st.markdown(f"""
    <div style="background: #151d28; border-left: 4px solid {s_col}; padding: 10px 14px; border-radius: 6px; margin-bottom: 8px;">
        <span style="font-size: 0.85em; color: #94a3b8;"><b>{item['symbol']}</b> • {item['sector']} • {item['time']}</span> &nbsp;&nbsp;
        <span style="font-size: 0.8em; background: #1e293b; color: #38bdf8; padding: 2px 6px; border-radius: 4px;">{item['badge']}</span><br>
        <span style="font-size: 0.95em; color: #f1f5f9; font-weight: 500;">{item['headline']}</span>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# ── Indian Macro Alternative Data Real-Economy Pulse ─────────────────────────
st.subheader("🛰️ Indian Macro Alternative Data Real-Economy Pulse")
st.caption("High-frequency ground-level proxies: GST E-Way Bills, UPI Payments, Vahan Auto Dispatches, and National Power Grid Load")

from core.alternative_data import fetch_alternative_data_pulse
alt_pulse = fetch_alternative_data_pulse()

ap1, ap2, ap3 = st.columns([1, 1, 2])
ap1.metric("Real-Economy Pulse", f"{alt_pulse['pulse_score']}/100", alt_pulse['regime_badge'])
ap2.metric("Avg Proxy Velocity", f"{alt_pulse['avg_growth_pct']:+.1f}% YoY", "Ground Acceleration")
ap3.markdown(f"**Alternative Data Health Verdict:** `{alt_pulse['regime']}`<br><span style='font-size: 0.88em; color: #94a3b8;'>{alt_pulse['description']}</span>", unsafe_allow_html=True)

with st.expander("📊 **High-Frequency Alternative Data Vertical Breakdown**", expanded=False):
    df_alt = pd.DataFrame(alt_pulse["pillars"])
    st.dataframe(
        df_alt[["indicator", "category", "latest_value", "growth_pct", "impact_sector", "health_badge", "lead_time_days"]].rename(columns={
            "indicator": "Real-Economy Indicator",
            "category": "Vertical",
            "latest_value": "Latest Run-Rate",
            "growth_pct": "Growth % YoY",
            "impact_sector": "Primary Impact Sectors",
            "health_badge": "Status",
            "lead_time_days": "Lead Horizon vs GDP"
        }).style.format({
            "Growth % YoY": "{:+.1f}%"
        }),
        use_container_width=True,
        hide_index=True
    )

st.markdown("---")

# ── FII / DII Institutional Flow & F&O Positioning Tracker ──────────────────
st.subheader("🛰️ FII / DII Institutional Flow Regime & Derivatives Positioning")
st.caption("Foreign & Domestic institutional cash market buying/selling and Index Futures smart-money long/short exposure")

from core.institutional_flows import fetch_institutional_flows_dashboard
fii_dash = fetch_institutional_flows_dashboard()

fc1, fc2, fc3, fc4 = st.columns(4)
fc1.metric("FII Cash Market (Today)", f"₹{fii_dash['fii_cash_today_cr']:+,.1f} Cr", "Net Inflow" if fii_dash['fii_cash_today_cr'] > 0 else "Net Outflow")
fc2.metric("DII Cash Market (Today)", f"₹{fii_dash['dii_cash_today_cr']:+,.1f} Cr", "Domestic Support")
fc3.metric("FII Index Futures Long %", f"{fii_dash['fii_futures_long_pct']:.1f}%", fii_dash['regime_badge'])
fc4.metric("FII Call/Put OI Ratio", f"{fii_dash['fii_call_put_ratio']:.2f}", f"Score: {fii_dash['sentiment_score']}/100")

st.markdown(f"**Smart Money Flow Verdict:** `{fii_dash['regime']}` • 5-Day Cumulative Inflow: FII **₹{fii_dash['fii_5d_cum_cr']:+,.1f} Cr** | DII **₹{fii_dash['dii_5d_cum_cr']:+,.1f} Cr**")




