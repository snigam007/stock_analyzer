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
        if str(_curr) not in sys.path:
            sys.path.insert(0, str(_curr))
        break
    _curr = _curr.parent
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
