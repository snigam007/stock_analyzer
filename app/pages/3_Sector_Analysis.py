"""
Page 3: Sector Analysis
Sector performance, correlation heatmap, rotation wheel, and cross-sector impact.
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
st.set_page_config(page_title="Sector Analysis", page_icon="🏭", layout="wide")

from db.database import get_global_engine, get_session
from sqlalchemy import text
from core.sector_analysis import get_sector_returns, compute_sector_correlations, detect_sector_rotation, get_cross_sector_impacts

engine = get_global_engine()

st.title("🏭 Sector Analysis")
st.caption("Sector performance, correlations, rotation signals, and cross-sector impact")

@st.cache_data(ttl=30)
def get_sector_data():
    session = get_session(engine)
    # Sector performance
    perf = session.execute(text("""
        SELECT sector, daily_return_avg, weekly_return, monthly_return, quarterly_return,
               total_stocks, stocks_up, stocks_down, advance_decline_ratio,
               avg_composite_score, buy_signals_count, sell_signals_count, sector_signal
        FROM sector_analysis
        WHERE date = (SELECT MAX(date) FROM sector_analysis)
        ORDER BY avg_composite_score DESC
    """)).fetchall()

    # Correlation
    corr_data = session.execute(text("""
        SELECT sector_a, sector_b, correlation_30d, correlation_90d
        FROM sector_correlations
        WHERE date = (SELECT MAX(date) FROM sector_correlations)
    """)).fetchall()

    session.close()
    return perf, corr_data


perf_data, corr_data = get_sector_data()

# ─── Sector Performance Cards ─────────────────────────────────────────────────
st.subheader("📊 Today's Sector Performance")

if perf_data:
    # Heatmap of sector returns
    perf_df = pd.DataFrame(perf_data, columns=[
        "Sector", "Daily %", "Weekly %", "Monthly %", "Quarterly %",
        "Stocks", "Up", "Down", "A/D Ratio",
        "Avg Score", "Buy Signals", "Sell Signals", "Signal"
    ])

    # Color-coded metrics
    cols = st.columns(min(len(perf_df), 4))
    for i, (_, row) in enumerate(perf_df.head(8).iterrows()):
        col = cols[i % 4]
        with col:
            daily = row["Daily %"] or 0
            color = "🟢" if daily > 0 else "🔴"
            sig_icon = {"BUY": "🟢", "SELL": "🔴", "WATCH": "🟡"}.get(row["Signal"], "🟡")
            st.metric(
                f"{row['Sector'][:25]}",
                f"{daily:+.2f}%",
                f"A/D: {row['Up']}/{row['Down']} | {sig_icon} {row['Signal']}"
            )

    st.markdown("---")

    # Performance table
    st.subheader("📅 Multi-Period Sector Returns")
    perf_display = perf_df[["Sector", "Daily %", "Weekly %", "Monthly %", "Avg Score", "Buy Signals", "Signal"]].copy()

    def color_return(val):
        try:
            v = float(val)
            if v > 0: return "color: #00c875; font-weight: bold"
            elif v < 0: return "color: #e04b4b; font-weight: bold"
        except: pass
        return ""

    def color_score(val):
        try:
            v = float(val)
            if v >= 60: return "background-color: #1a4d2e; color: #00c875; font-weight: bold"
            elif v <= 40: return "background-color: #4d1a1a; color: #ff6b6b; font-weight: bold"
            else: return "background-color: #3d3200; color: #ffd700"
        except: pass
        return ""

    st.dataframe(
        perf_display.style
            .map(color_return, subset=["Daily %", "Weekly %", "Monthly %"])
            .map(color_score, subset=["Avg Score"])
            .format({"Daily %": "{:+.2f}%", "Weekly %": "{:+.2f}%", "Monthly %": "{:+.2f}%", "Avg Score": "{:.0f}"}),
        use_container_width=True,
        hide_index=True,
    )

    # Sector signal bar chart
    fig_bar = px.bar(
        perf_df.sort_values("Monthly %"),
        x="Monthly %",
        y="Sector",
        orientation="h",
        color="Monthly %",
        color_continuous_scale=["#e04b4b", "#f0a500", "#00c875"],
        title="Monthly Returns by Sector",
        color_continuous_midpoint=0,
    )
    fig_bar.update_layout(
        paper_bgcolor="#0e1117", plot_bgcolor="#1a1d23",
        font=dict(color="#e0e0e0"), height=400,
        coloraxis_showscale=False,
    )
    st.plotly_chart(fig_bar, use_container_width=True)

else:
    st.info("No sector data available. Run `python initialize.py` first.")

st.markdown("---")

# ─── Correlation Heatmap ──────────────────────────────────────────────────────
st.subheader("🔗 Sector Correlation Matrix (30-Day)")

if corr_data:
    corr_df = pd.DataFrame(corr_data, columns=["Sector A", "Sector B", "Corr 30D", "Corr 90D"])
    all_sectors = sorted(set(corr_df["Sector A"].tolist() + corr_df["Sector B"].tolist()))

    matrix = pd.DataFrame(np.eye(len(all_sectors)), index=all_sectors, columns=all_sectors)
    for _, row in corr_df.iterrows():
        a, b = row["Sector A"], row["Sector B"]
        c = row["Corr 30D"] or 0
        if a in matrix.index and b in matrix.columns:
            matrix.loc[a, b] = c
            matrix.loc[b, a] = c

    fig_heatmap = go.Figure(data=go.Heatmap(
        z=matrix.values,
        x=matrix.columns.tolist(),
        y=matrix.index.tolist(),
        colorscale="RdYlGn",
        zmin=-1, zmax=1,
        text=matrix.round(2).values,
        texttemplate="%{text}",
        hovertemplate="<b>%{y}</b> × <b>%{x}</b><br>Correlation: %{z:.2f}<extra></extra>",
    ))
    fig_heatmap.update_layout(
        title="30-Day Rolling Sector Correlation",
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
        font=dict(color="#e0e0e0"), height=500,
    )
    st.plotly_chart(fig_heatmap, use_container_width=True)
    st.caption("Green = positive correlation (move together), Red = negative correlation (inverse)")
else:
    st.info("Correlation data not available yet.")

st.markdown("---")

# ─── Sector Rotation ──────────────────────────────────────────────────────────
st.subheader("🔄 Sector Rotation Signals")

session = get_session(engine)
sector_returns = get_sector_returns(session, days=30)
session.close()

if not sector_returns.empty:
    rotation = detect_sector_rotation(sector_returns)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("### 📈 Gaining Momentum")
        for s in rotation["gaining"]:
            st.success(f"**{s['sector'][:30]}** +{s['momentum']*100:.2f}%")

    with col2:
        st.markdown("### ➡️ Neutral")
        for s in rotation["neutral"][:5]:
            st.info(f"**{s['sector'][:30]}** {s['momentum']*100:+.2f}%")

    with col3:
        st.markdown("### 📉 Losing Momentum")
        for s in rotation["losing"]:
            st.error(f"**{s['sector'][:30]}** {s['momentum']*100:.2f}%")

st.markdown("---")

# ─── Cross-Sector Impact Rules ────────────────────────────────────────────────
st.subheader("⚡ Cross-Sector Impact Rules")
st.caption("How movement in one sector affects another (direct or inverse)")

impacts = get_cross_sector_impacts()

col1, col2 = st.columns(2)
for i, impact in enumerate(impacts):
    col = col1 if i % 2 == 0 else col2
    with col:
        direction_icon = "→" if impact["direction"] == 1 else ("⟲" if impact["direction"] == -1 else "≈")
        impact_color = "success" if impact["direction"] == 1 else ("error" if impact["direction"] == -1 else "info")
        if impact_color == "success":
            st.success(f"**{impact['from_sector'][:25]}** {direction_icon} **{impact['to_sector'][:25]}** (DIRECT)\n\n{impact['description']}")
        elif impact_color == "error":
            st.error(f"**{impact['from_sector'][:25]}** {direction_icon} **{impact['to_sector'][:25]}** (INVERSE)\n\n{impact['description']}")
        else:
            st.info(f"**{impact['from_sector'][:25]}** {direction_icon} **{impact['to_sector'][:25]}** (WEAK)\n\n{impact['description']}")

st.markdown("---")

# ── Relative Rotation Graphs (RRG) ───────────────────────────────────────────
st.subheader("🌀 JdK Relative Rotation Graph (RRG) & Institutional Money Flow")
st.caption("Benchmark: NIFTY 50 (^NSEI) — Track sector capital rotation across Leading, Weakening, Lagging, and Improving quadrants")

from core.rrg_matrix import compute_sector_rrg_matrix
session_rrg = get_session(engine)
rrg_data = compute_sector_rrg_matrix(session_rrg, lookback_weeks=14)
session_rrg.close()

if "error" not in rrg_data and rrg_data.get("sectors"):
    fig_rrg = go.Figure()

    # 4 Quadrant Background Rectangles
    fig_rrg.add_shape(type="rect", x0=100, y0=100, x1=115, y1=115, fillcolor="rgba(0, 200, 117, 0.12)", line_width=0, layer="below")
    fig_rrg.add_shape(type="rect", x0=100, y0=85, x1=115, y1=100, fillcolor="rgba(240, 165, 0, 0.12)", line_width=0, layer="below")
    fig_rrg.add_shape(type="rect", x0=85, y0=85, x1=100, y1=100, fillcolor="rgba(255, 75, 75, 0.12)", line_width=0, layer="below")
    fig_rrg.add_shape(type="rect", x0=85, y0=100, x1=100, y1=115, fillcolor="rgba(0, 168, 255, 0.12)", line_width=0, layer="below")

    # Center Reference Lines
    fig_rrg.add_hline(y=100, line=dict(color="#556677", width=1.5, dash="dash"))
    fig_rrg.add_vline(x=100, line=dict(color="#556677", width=1.5, dash="dash"))

    for s in rrg_data["sectors"]:
        tail_x = [t["rs_ratio"] for t in s["tail"]]
        tail_y = [t["rs_momentum"] for t in s["tail"]]
        fig_rrg.add_trace(go.Scatter(
            x=tail_x, y=tail_y,
            mode="lines",
            line=dict(color=s["quad_color"], width=1.5),
            opacity=0.6,
            showlegend=False,
            hoverinfo="skip",
        ))

        fig_rrg.add_trace(go.Scatter(
            x=[s["rs_ratio"]],
            y=[s["rs_momentum"]],
            mode="markers+text",
            marker=dict(size=14, color=s["quad_color"], line=dict(width=1.5, color="#ffffff")),
            text=[s["sector"]],
            textposition="top center",
            name=s["sector"],
            hovertemplate=f"<b>{s['sector']}</b><br>Quadrant: {s['quadrant']}<br>RS-Ratio: {s['rs_ratio']}<br>RS-Momentum: {s['rs_momentum']}<br>Action: {s['advice']}<extra></extra>",
        ))

    # Quadrant Labels
    fig_rrg.add_annotation(x=112, y=112, text="🟢 LEADING<br>(Overweight)", showarrow=False, font=dict(color="#00c875", size=13))
    fig_rrg.add_annotation(x=112, y=88, text="🟡 WEAKENING<br>(Take Profit)", showarrow=False, font=dict(color="#f0a500", size=13))
    fig_rrg.add_annotation(x=88, y=88, text="🔴 LAGGING<br>(Underweight)", showarrow=False, font=dict(color="#ff4b4b", size=13))
    fig_rrg.add_annotation(x=88, y=112, text="🔵 IMPROVING<br>(Accumulate)", showarrow=False, font=dict(color="#00a8ff", size=13))

    fig_rrg.update_layout(
        title="🌀 Sector Relative Rotation Graph (RRG) vs NIFTY 50 Benchmark",
        xaxis=dict(title="JdK RS-Ratio (Relative Trend > 100 is Outperforming)", range=[85, 115], gridcolor="#2d3139"),
        yaxis=dict(title="JdK RS-Momentum (Momentum Acceleration > 100 is Expanding)", range=[85, 115], gridcolor="#2d3139"),
        height=580,
        paper_bgcolor="#0e1117",
        plot_bgcolor="#161b22",
        font=dict(color="#e0e8f0"),
        showlegend=False,
    )
    st.plotly_chart(fig_rrg, use_container_width=True)

    # Sector Quadrant Summary Cards
    q_col1, q_col2, q_col3, q_col4 = st.columns(4)
    with q_col1:
        st.markdown("### 🟢 Leading Sectors")
        for s in [sec for sec in rrg_data["sectors"] if "Leading" in sec["quadrant"]]:
            st.success(f"**{s['sector']}** (RS: {s['rs_ratio']:.1f})")
    with q_col2:
        st.markdown("### 🔵 Improving Sectors")
        for s in [sec for sec in rrg_data["sectors"] if "Improving" in sec["quadrant"]]:
            st.info(f"**{s['sector']}** (Mom: {s['rs_momentum']:.1f})")
    with q_col3:
        st.markdown("### 🟡 Weakening Sectors")
        for s in [sec for sec in rrg_data["sectors"] if "Weakening" in sec["quadrant"]]:
            st.warning(f"**{s['sector']}** (RS: {s['rs_ratio']:.1f})")
    with q_col4:
        st.markdown("### 🔴 Lagging Sectors")
        for s in [sec for sec in rrg_data["sectors"] if "Lagging" in sec["quadrant"]]:
            st.error(f"**{s['sector']}** (RS: {s['rs_ratio']:.1f})")

st.markdown("---")

# ─── Sector Peer Benchmarking Matrix ──────────────────────────────────────────
st.subheader("🔍 Intra-Sector Peer Ranking & Valuation Matrix")
st.caption("Deep-dive comparative ranking across all companies within any target sector.")

from db.database import Stock
from core.peer_comparison import get_custom_peer_comparison

session_sec = get_session(engine)
all_sec_names = [s[0] for s in session_sec.execute(text("SELECT DISTINCT sector FROM stocks WHERE is_active=1 ORDER BY sector")).fetchall()]

if all_sec_names:
    selected_bench_sector = st.selectbox("📂 Select Sector to Benchmark:", all_sec_names, index=0)

    sec_stocks = session_sec.query(Stock).filter(Stock.sector == selected_bench_sector, Stock.is_active == True).all()
    sec_symbols = [s.symbol for s in sec_stocks]

    if sec_symbols:
        peer_results = get_custom_peer_comparison(sec_symbols, session_sec)
        session_sec.close()

        if peer_results and "peers" in peer_results and peer_results["peers"]:
            peers_list = peer_results["peers"]
            s_avg = peer_results["sector_averages"]

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("🏢 Sector Universe", f"{s_avg['peer_count']} stocks")
            k2.metric("🎯 Average Score", f"{s_avg['avg_composite_score']:.1f}/100")
            k3.metric("📅 3M Cohort Return", f"{s_avg['avg_ret_3m']:+.2f}%")
            k4.metric("🛡️ Quality Benchmark", f"{s_avg['avg_piotroski']:.1f}/9 (Piotroski)")

            df_peer_table = pd.DataFrame(peers_list)[[
                "symbol", "name", "composite_score", "score_rank", "signal",
                "ret_1m", "ret_3m", "ret_1y", "rsi", "adx", "beta", "volatility_pct",
                "piotroski_f", "altman_z", "solvency"
            ]]

            st.dataframe(
                df_peer_table.rename(columns={
                    "symbol": "Symbol", "name": "Company", "composite_score": "Score",
                    "score_rank": "Rank", "signal": "Signal",
                    "ret_1m": "1M Ret %", "ret_3m": "3M Ret %", "ret_1y": "1Y Ret %",
                    "rsi": "RSI", "adx": "ADX", "beta": "Beta", "volatility_pct": "Vol %",
                    "piotroski_f": "Piotroski", "altman_z": "Altman Z", "solvency": "Solvency"
                }).style.format({
                    "Score": "{:.1f}",
                    "1M Ret %": "{:+.2f}%",
                    "3M Ret %": "{:+.2f}%",
                    "1Y Ret %": "{:+.2f}%",
                    "RSI": "{:.1f}",
                    "ADX": "{:.1f}",
                    "Beta": "{:.2f}",
                    "Vol %": "{:.1f}%",
                    "Altman Z": "{:.2f}"
                }),
                use_container_width=True,
                height=350,
                hide_index=True
            )
else:
    session_sec.close()
