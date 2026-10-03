"""
Page 13: Data Refresh Status & Universe Health Hub
Displays data freshness, daily stock/index/commodity ingestion counts,
complete searchable universe directory, and scheduled synchronization health.
"""
import sys
from pathlib import Path
from datetime import datetime, date

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Universal Root Directory Finder
_curr = Path(__file__).resolve()
while _curr != _curr.parent:
    if (_curr / "core").exists() and (_curr / "db").exists():
        break
    _curr = _curr.parent
BASE_DIR = _curr
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from core.data_status import (
    get_database_status_summary,
    get_daily_stock_counts_history,
    get_searchable_universe_directory,
)
from core.ui_components import (
    render_clean_html,
    fmt_inr,
    render_empty_defensive_state
)

try:
    st.set_page_config(
        page_title="Data Refresh Status",
        page_icon="🔄",
        layout="wide",
        initial_sidebar_state="expanded"
    )
except Exception:
    pass

# Custom CSS
st.markdown("""
<style>
    [data-testid="stSidebar"] { background-color: #0e1117; }
    .main { background-color: #0e1117; }
    
    div[data-testid="metric-container"] {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 12px 16px;
    }
    
    .status-card {
        background: linear-gradient(90deg, #102130, #0c1822);
        border-left: 5px solid #00c875;
        padding: 14px 20px;
        border-radius: 8px;
        margin-bottom: 16px;
    }

    .badge-stock { background-color: #1f6feb; color: white; padding: 2px 8px; border-radius: 12px; font-size: 0.8em; font-weight: bold; }
    .badge-index { background-color: #8957e5; color: white; padding: 2px 8px; border-radius: 12px; font-size: 0.8em; font-weight: bold; }
    .badge-commodity { background-color: #d29922; color: black; padding: 2px 8px; border-radius: 12px; font-size: 0.8em; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# Fetch Status Data
summary = get_database_status_summary()

# ── Title & Institutional Refresh Banner ───────────────────────────────────────
st.title("🔄 Data Refresh Status & Universe Health Hub")
st.caption("Live Synchronization Telemetry, Daily Ingestion Counts, and Searchable Asset Universe Directory")

# Top Refresh Banner
render_clean_html(f"""
<div style="background: linear-gradient(90deg, #101c28, #0e141e); border: 1px solid rgba(0,255,102,0.25); border-left: 5px solid #00ff66; padding: 14px 20px; border-radius: 8px; margin-bottom: 16px; box-shadow: 0 4px 16px rgba(0,0,0,0.3);">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
        <div>
            <span style="font-size: 1.25em; font-weight: bold; color: #00ff66;">
                📅 Data Refresh Date: {summary['max_date']} (Latest Market Close Session)
            </span><br>
            <span style="font-size: 0.92em; color: #cbd5e1; font-family: 'JetBrains Mono', monospace;">
                Telemetry Status: <b style="color: #00eefc;">{summary['status_badge']}</b> • <b style="color: #00ff66;">{summary['latest_session_stock_count']}</b> / <b>{summary['stock_count']}</b> Equities Active • <b>{summary['total_bars']:,}</b> Total Historical Bars
            </span>
        </div>
        <div style="text-align: right;">
            <span style="background: rgba(0, 255, 102, 0.15); border: 1px solid #00ff66; color: #00ff66; padding: 5px 12px; border-radius: 16px; font-weight: 700; font-size: 0.85em; font-family: 'JetBrains Mono', monospace;">
                ⚡ Auto-Refresh Scheduled: 08:00 AM IST
            </span>
        </div>
    </div>
</div>
""")

# ── Top Metric Cards ──────────────────────────────────────────────────────────
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Max Data Date", summary['max_date'], "Latest Ingested Session")
m2.metric("Total Equities", f"{summary['stock_count']} Stocks", f"{summary['latest_session_stock_count']} Synced Today")
m3.metric("Benchmark Indexes", f"{summary['index_count']} Indexes", "NSE/BSE/Global")
m4.metric("Commodity Assets", f"{summary['commodity_count']} Commodities", "MCX/COMEX/ETFs")
m5.metric("Total Universe", f"{summary['total_assets']} Assets", f"{summary['total_bars']:,} Total Bars")

st.markdown("---")

# ── SECTION 1: Stocks Count Per Day & Historical Ingestion Chart ──────────────
st.subheader("📈 Stocks Count Per Day & Ingestion Telemetry")
st.caption("Historical daily coverage tracking active equities, benchmark indexes, and commodities per trading day")

c_opt1, c_opt2 = st.columns([2, 8])
with c_opt1:
    history_days = st.selectbox("Lookback Window", [30, 60, 90, 180, 365, 730], index=3)

df_hist = get_daily_stock_counts_history(days=history_days)

if not df_hist.empty:
    fig_hist = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.7, 0.3],
        subplot_titles=("Active Stocks Ingested Per Trading Day", "Total Daily Market Volume Tracked")
    )

    # 1. Stocks count bar chart
    fig_hist.add_trace(
        go.Bar(
            x=df_hist["date"],
            y=df_hist["stock_count"],
            name="Active Stocks Count",
            marker=dict(
                color=df_hist["stock_count"],
                colorscale="Viridis",
                showscale=False
            ),
            hovertemplate="<b>Date:</b> %{x}<br><b>Active Stocks:</b> %{y}<extra></extra>"
        ),
        row=1, col=1
    )

    # Add reference line for target universe count
    fig_hist.add_hline(
        y=summary["stock_count"],
        line_dash="dot",
        line_color="#00c875",
        annotation_text=f"Full Universe ({summary['stock_count']})",
        annotation_position="top left",
        row=1, col=1
    )

    # 2. Daily volume bar chart
    fig_hist.add_trace(
        go.Bar(
            x=df_hist["date"],
            y=df_hist["total_stock_volume"],
            name="Daily Volume",
            marker_color="#00a8ff",
            opacity=0.7,
            hovertemplate="<b>Date:</b> %{x}<br><b>Turnover Volume:</b> %{y:,.0f}<extra></extra>"
        ),
        row=2, col=1
    )

    fig_hist.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0e1117",
        plot_bgcolor="#161b22",
        height=450,
        margin=dict(l=20, r=20, t=40, b=20),
        showlegend=False,
    )
    fig_hist.update_yaxes(title_text="Stock Count", row=1, col=1, gridcolor="#262c36")
    fig_hist.update_yaxes(title_text="Volume", row=2, col=1, gridcolor="#262c36")
    fig_hist.update_xaxes(gridcolor="#262c36")

    st.plotly_chart(fig_hist, use_container_width=True)

    # Daily breakdown collapsible table
    with st.expander(f"📋 View Daily Breakdown Table (Last {len(df_hist)} Trading Sessions)"):
        table_view = df_hist[["date", "stock_count", "index_count", "commodity_count", "total_assets_updated", "avg_stock_close", "total_stock_volume"]].sort_values("date", ascending=False)
        table_view.columns = ["Trading Date", "Stocks Active", "Indexes Active", "Commodities Active", "Total Assets Synced", "Avg Close Price (₹)", "Total Turnover Volume"]
        st.dataframe(
            table_view.style.format({
                "Avg Close Price (₹)": "₹{:,.2f}",
                "Total Turnover Volume": "{:,.0f}",
                "Stocks Active": "{:d}",
                "Indexes Active": "{:d}",
                "Commodities Active": "{:d}",
                "Total Assets Synced": "{:d}"
            }),
            use_container_width=True,
            height=300
        )

st.markdown("---")

# ── SECTION 2: Complete Searchable Asset Universe Directory ───────────────────
st.subheader("🔍 Searchable Asset Universe Directory")
st.caption(f"Complete searchable catalog of all {summary['total_assets']} assets ({summary['stock_count']} Equities, {summary['index_count']} Indexes, {summary['commodity_count']} Commodities) with real-time status")

df_universe = get_searchable_universe_directory()

# Filter Controls
f_col1, f_col2, f_col3, f_col4 = st.columns([4, 2, 2, 2])

with f_col1:
    search_query = st.text_input(
        "🔎 Search Symbol, Company / Asset Name, or Sector",
        "",
        placeholder="e.g. RELIANCE, NIFTY, Gold, TCS, HDFC, Crude..."
    ).strip()

with f_col2:
    category_filter = st.selectbox(
        "Asset Category",
        ["All Categories", "Stock", "Index", "Commodity"],
        index=0
    )

with f_col3:
    all_sectors = sorted(df_universe["sector"].dropna().unique().tolist())
    sector_filter = st.selectbox("Filter Sector", ["All Sectors"] + all_sectors)

with f_col4:
    signal_filter = st.selectbox("Signal Filter", ["All Signals", "BUY", "SELL", "WATCH"])

# Apply Filters
filtered_df = df_universe.copy()

if search_query:
    q = search_query.lower()
    filtered_df = filtered_df[
        filtered_df["symbol"].str.lower().str.contains(q, na=False) |
        filtered_df["name"].str.lower().str.contains(q, na=False) |
        filtered_df["sector"].str.lower().str.contains(q, na=False) |
        filtered_df["yf_symbol"].str.lower().str.contains(q, na=False)
    ]

if category_filter != "All Categories":
    filtered_df = filtered_df[filtered_df["asset_type"] == category_filter]

if sector_filter != "All Sectors":
    filtered_df = filtered_df[filtered_df["sector"] == sector_filter]

if signal_filter != "All Signals":
    filtered_df = filtered_df[filtered_df["signal"] == signal_filter]

# Summary pills
cat_counts = filtered_df["asset_type"].value_counts().to_dict()
render_clean_html(f"""
<div style="margin-bottom: 12px; font-family: 'JetBrains Mono', monospace; font-size: 0.9em; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
    <b style="color: #f8fafc;">Matching Results: {len(filtered_df)} Assets</b> • 
    <span style="background: rgba(56,189,248,0.15); border: 1px solid #38bdf8; color: #38bdf8; padding: 2px 8px; border-radius: 4px; font-weight: 700;">🏢 {cat_counts.get('Stock', 0)} Stocks</span> • 
    <span style="background: rgba(168,85,247,0.15); border: 1px solid #a855f7; color: #c084fc; padding: 2px 8px; border-radius: 4px; font-weight: 700;">📊 {cat_counts.get('Index', 0)} Indexes</span> • 
    <span style="background: rgba(245,158,11,0.15); border: 1px solid #f59e0b; color: #fbbf24; padding: 2px 8px; border-radius: 4px; font-weight: 700;">🪙 {cat_counts.get('Commodity', 0)} Commodities</span>
</div>
""")

# Display Table
display_cols = [
    "symbol", "name", "asset_type", "sector", "tier", "price_records",
    "min_date", "max_date", "latest_close", "daily_return_pct", "signal", "composite_score"
]
table_display = filtered_df[display_cols].copy()
table_display.columns = [
    "Symbol", "Asset / Company Name", "Type", "Sector", "Tier", "Bars Count",
    "Data Start", "Latest Date", "Latest Close", "Daily Return %", "Signal", "Score"
]

def style_signal(val):
    if val == "BUY": return "background-color: #1a6b3c; color: #ffffff; font-weight: bold;"
    elif val == "SELL": return "background-color: #8b1a1a; color: #ffffff; font-weight: bold;"
    return "background-color: #4a4a5a; color: #ffffff;"

def style_return(val):
    if pd.isna(val): return ""
    color = "#00c875" if val > 0 else ("#e04b4b" if val < 0 else "#ffffff")
    return f"color: {color}; font-weight: bold;"

styler = table_display.style
map_fn = getattr(styler, "map", getattr(styler, "applymap", None))
if map_fn:
    styler = map_fn(style_signal, subset=["Signal"])
    map_fn_2 = getattr(styler, "map", getattr(styler, "applymap", None))
    if map_fn_2:
        styler = map_fn_2(style_return, subset=["Daily Return %"])

st.dataframe(
    styler.format({
        "Latest Close": "₹{:,.2f}",
        "Daily Return %": "{:+.2f}%",
        "Score": "{:.1f}",
        "Bars Count": "{:,d}"
    }),
    use_container_width=True,
    height=450
)

# Download CSV option
csv = filtered_df.to_csv(index=False).encode('utf-8')
st.download_button(
    "📥 Download Filtered Asset Directory (CSV)",
    data=csv,
    file_name=f"asset_universe_status_{summary['max_date']}.csv",
    mime="text/csv",
    use_container_width=False
)

st.markdown("---")

# ── SECTION 3: Empirical Signal Accuracy & Audit Track Record ────────────────
st.subheader("🎯 Empirical Signal Accuracy & Audit Track Record")
st.caption("Forward-testing empirical verification of BUY/SELL signals against actual subsequent price movements across all sessions")

try:
    from core.accuracy_tracker import evaluate_signal_audit_track_record
    engine = get_global_engine()
    session = get_session(engine)
    audit = evaluate_signal_audit_track_record(session)
    session.close()

    a1, a2, a3, a4, a5 = st.columns(5)
    a1.metric("Tracked Signals", f"{audit['total_signals_tracked']}", f"{audit['completed_signals']} Evaluated | {audit['active_signals']} In Play")
    a2.metric("Overall Win Rate", f"{audit['overall_win_rate_pct']}%", "Target Hit or Profitable Close")
    a3.metric("Target 1 Hit Rate", f"{audit['target_1_hit_rate_pct']}%", "+3.5% to +5.5% Gain")
    a4.metric("Stop Loss Rate", f"{audit['stop_loss_hit_rate_pct']}%", "Capital Preservation")
    a5.metric("Profit Factor", f"{audit['profit_factor']}x", f"+{audit['avg_peak_gain_mfe']}% Avg Peak Gain")

    if audit.get("records"):
        df_audit = pd.DataFrame(audit["records"])
        with st.expander("📋 View Granular Signal Audit Log & Excursion History", expanded=False):
            st.dataframe(
                df_audit.rename(columns={
                    "date": "Signal Date", "symbol": "Symbol", "signal": "Signal",
                    "entry_price": "Entry Price", "target_1": "Target 1", "target_2": "Target 2",
                    "target_3": "Target 3", "stop_loss": "Stop Loss", "status": "Audit Status",
                    "days_elapsed": "Days In Play", "max_gain_pct": "Max Peak Gain %",
                    "max_loss_pct": "Max Drawdown %", "current_gain_pct": "Current Return %"
                }),
                use_container_width=True,
                height=350
            )
except Exception as e:
    st.info(f"Audit track record loading: {e}")

st.markdown("---")

# ── SECTION 4: Manual On-Demand Refresh Trigger ──────────────────────────────
st.subheader("⚡ On-Demand Market Data Refresh Trigger")
st.caption("Manually execute the incremental delta update pipeline to pull the latest open market bars immediately")

btn_col1, btn_col2 = st.columns([3, 7])
with btn_col1:
    if st.button("🚀 Trigger Delta Update Now", type="primary", use_container_width=True):
        with st.spinner("⚡ Fetching latest price deltas & recomputing indicators & signals..."):
            try:
                from update_daily import run_daily_delta_update
                run_daily_delta_update()
                st.success("✅ Database refreshed successfully! Please reload the page to view updated numbers.")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Refresh failed: {e}")

with btn_col2:
    st.info(
        "💡 **Automatic Scheduling Info**: Market deltas are automatically fetched every day at **08:00 AM IST** "
        "via GitHub Actions workflow. Manual trigger is useful during active trading hours for mid-day updates."
    )
