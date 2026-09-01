"""
Institutional Bulk & Block Deals Tracker & Indian Economic Calendar
- Tab 1: Live Institutional Whale Transaction Stream & Accumulation / Distribution Tracker
- Tab 2: Economic & Market Events Calendar (RBI MPC, Inflation, GDP, F&O Expiries, Earnings)
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date

import sys
from pathlib import Path
import importlib

# Universal Root Directory Finder
_curr = Path(__file__).resolve()
while _curr != _curr.parent:
    if (_curr / "core").exists() and (_curr / "db").exists():
        break
    _curr = _curr.parent
BASE_DIR = _curr
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import db.database
if not hasattr(db.database, "BulkBlockDeal"):
    importlib.reload(db.database)

import core.bulk_deals
if not hasattr(core.bulk_deals, "get_latest_synced_deal_metadata"):
    importlib.reload(core.bulk_deals)

from db.database import get_global_engine, get_session
from core.bulk_deals import (
    fetch_latest_bulk_deals,
    get_bulk_deals_summary,
    get_latest_synced_deal_metadata,
    sync_bulk_and_block_deals_delta
)
from core.economic_calendar import get_upcoming_economic_events, seed_macro_calendar

st.set_page_config(page_title="🏦 Institutional Deals & Calendar", page_icon="🏦", layout="wide")

# Custom CSS
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, rgba(30,41,59,0.7) 0%, rgba(15,23,42,0.8) 100%);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 12px;
    }
    .high-impact {
        background-color: rgba(239, 68, 68, 0.2);
        color: #EF4444;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 4px;
    }
    .sync-badge {
        background: rgba(0, 200, 117, 0.15);
        color: #00c875;
        border: 1px solid rgba(0, 200, 117, 0.3);
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 0.85em;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

st.title("🏦 Institutional Whale Flows & Economic Calendar")
st.caption("Track institutional footprint in Bulk/Block deals with automated Delta Sync and stay ahead of critical RBI, Macro & Derivative Expiry catalysts.")

engine = get_global_engine()
session = get_session(engine)

meta_info = get_latest_synced_deal_metadata(session)

tab_deals, tab_cal = st.tabs(["🏦 Institutional Bulk & Block Deals", "📅 Indian Macro & Market Calendar"])

# ─── TAB 1: INSTITUTIONAL BULK & BLOCK DEALS ─────────────────────────────────
with tab_deals:
    col_hdr1, col_hdr2, col_hdr3 = st.columns([2.5, 1, 1])
    with col_hdr1:
        st.subheader("🐋 Large Whale Transaction Tracker (> ₹2-10 Cr)")
        status_color = "#00c875" if meta_info["is_up_to_date"] else "#f59e0b"
        st.markdown(
            f"<span style='color: {status_color}; font-weight: bold;'>● Database Status:</span> "
            f"**{meta_info['total_deals_count']}** deals indexed | "
            f"Latest synced: **{meta_info['last_synced_date']}** | "
            f"Market price date: **{meta_info['latest_price_date']}**",
            unsafe_allow_html=True
        )
    with col_hdr2:
        if st.button("⚡ Run Delta Sync", type="primary", help="Incrementally syncs new deals since the last synced date without re-fetching everything."):
            with st.spinner("Executing incremental Delta Sync..."):
                d_res = sync_bulk_and_block_deals_delta(session, force_full=False)
                st.session_state["last_deal_sync_result"] = d_res
                st.rerun()
    with col_hdr3:
        if st.button("🔄 Full Resync", help="Forces a complete 30-day lookback exchange re-sync."):
            with st.spinner("Executing 30-day full historical re-sync..."):
                d_res = sync_bulk_and_block_deals_delta(session, force_full=True)
                st.session_state["last_deal_sync_result"] = d_res
                st.rerun()

    # Show Delta Sync notification banner if sync just completed
    if "last_deal_sync_result" in st.session_state:
        sync_res = st.session_state["last_deal_sync_result"]
        st.success(
            f"**{sync_res['message']}**\n\n"
            f"• **New Deals Added:** `{sync_res['new_deals_added']}` | "
            f"• **Existing Deals Updated:** `{sync_res['existing_deals_updated']}` | "
            f"• **Net Delta Flow:** `₹{sync_res['net_delta_flow_cr']:+,.2f} Cr` | "
            f"• **Timestamp:** `{sync_res['timestamp']}`"
        )
        # Clear one-time banner
        del st.session_state["last_deal_sync_result"]

    # Filter Bar
    st.markdown("---")
    f_col1, f_col2, f_col3, f_col4 = st.columns([1.5, 1, 1, 1.5])
    with f_col1:
        search_query = st.text_input("🔍 Search Symbol or Investor Name:", placeholder="e.g., RELIANCE, Morgan Stanley, LIC")
    with f_col2:
        type_filter = st.selectbox("Deal Type:", ["ALL", "BULK", "BLOCK", "WHALES ONLY"])
    with f_col3:
        side_filter = st.selectbox("Side:", ["ALL", "BUY", "SELL"])
    with f_col4:
        min_cr = st.slider("Min Value (₹ Cr):", min_value=1.0, max_value=50.0, value=2.0, step=1.0)

    summary = get_bulk_deals_summary(session, min_value_cr=min_cr)

    # Top Flow KPI Cards
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("💰 Total Institutional Buy", f"₹{summary['total_buy_val_cr']:,.2f} Cr")
    kpi2.metric("💸 Total Institutional Sell", f"₹{summary['total_sell_val_cr']:,.2f} Cr")
    net_val = summary['net_market_flow_cr']
    kpi3.metric("📊 Net Institutional Flow", f"₹{net_val:+,.2f} Cr", delta="Net Accumulation" if net_val > 0 else "Net Outflow")
    kpi4.metric("📦 Filtered Transactions", f"{len(summary['deals_stream'])} deals")

    st.markdown("---")

    col_acc, col_dist = st.columns(2)

    with col_acc:
        st.markdown("#### 🟢 Top Institutional Accumulation")
        if summary["top_accumulations"]:
            df_acc = pd.DataFrame(summary["top_accumulations"])[["symbol", "name", "sector", "net_flow_cr", "total_deals"]]
            st.dataframe(
                df_acc.rename(columns={
                    "symbol": "Symbol", "name": "Company", "sector": "Sector",
                    "net_flow_cr": "Net Buy (₹ Cr)", "total_deals": "Deals"
                }).style.format({
                    "Net Buy (₹ Cr)": "+₹{:,.2f} Cr"
                }),
                use_container_width=True,
                height=220,
                hide_index=True
            )
        else:
            st.info("No net accumulation above threshold.")

    with col_dist:
        st.markdown("#### 🔴 Top Institutional Distribution")
        if summary["top_distributions"]:
            df_dist = pd.DataFrame(summary["top_distributions"])[["symbol", "name", "sector", "net_flow_cr", "total_deals"]]
            st.dataframe(
                df_dist.rename(columns={
                    "symbol": "Symbol", "name": "Company", "sector": "Sector",
                    "net_flow_cr": "Net Sell (₹ Cr)", "total_deals": "Deals"
                }).style.format({
                    "Net Sell (₹ Cr)": "₹{:,.2f} Cr"
                }),
                use_container_width=True,
                height=220,
                hide_index=True
            )
        else:
            st.info("No net distribution above threshold.")

    st.markdown("---")
    st.markdown("#### 📜 Live Deal Transaction Stream")

    if summary["deals_stream"]:
        df_deals = pd.DataFrame(summary["deals_stream"])
        
        # Apply Search & Dropdown Filters
        if search_query:
            sq = search_query.strip().upper()
            df_deals = df_deals[
                df_deals["symbol"].str.upper().str.contains(sq) |
                df_deals["name"].str.upper().str.contains(sq) |
                df_deals["client_name"].str.upper().str.contains(sq)
            ]
        if type_filter == "BULK":
            df_deals = df_deals[df_deals["deal_type"] == "BULK"]
        elif type_filter == "BLOCK":
            df_deals = df_deals[df_deals["deal_type"] == "BLOCK"]
        elif type_filter == "WHALES ONLY":
            df_deals = df_deals[df_deals["is_whale"] == True]

        if side_filter != "ALL":
            df_deals = df_deals[df_deals["buy_sell"] == side_filter]

        if not df_deals.empty:
            df_show = df_deals[
                ["date", "symbol", "name", "client_name", "deal_type", "buy_sell", "quantity", "trade_price", "value_in_crores", "is_whale"]
            ]
            st.dataframe(
                df_show.rename(columns={
                    "date": "Date", "symbol": "Symbol", "name": "Company",
                    "client_name": "Institutional Client / Marquee Whale",
                    "deal_type": "Type", "buy_sell": "Side",
                    "quantity": "Quantity", "trade_price": "Price (₹)",
                    "value_in_crores": "Value (₹ Cr)", "is_whale": "Whale Flag"
                }).style.format({
                    "Quantity": "{:,d}",
                    "Price (₹)": "₹{:,.2f}",
                    "Value (₹ Cr)": "₹{:,.2f} Cr"
                }),
                use_container_width=True,
                height=380,
                hide_index=True
            )
        else:
            st.info("No deals match the specified search and filter criteria.")
    else:
        st.info("No bulk deals recorded matching the current filter.")


# ─── TAB 2: ECONOMIC CALENDAR ────────────────────────────────────────────────
with tab_cal:
    st.subheader("📅 Indian Macro & Market Events Schedule")
    st.caption("Surveillance of critical high-impact market catalysts: RBI MPC interest rate statements, CPI & WPI Inflation prints, Quarterly GDP, and NSE F&O Expiries.")

    col_c1, col_c2, col_c3 = st.columns([1, 1, 1])
    with col_c1:
        cat_filter = st.selectbox(
            "Category Filter:",
            ["ALL", "FO_EXPIRY", "MONETARY_POLICY", "INFLATION", "GDP", "EARNINGS"]
        )
    with col_c2:
        imp_filter = st.selectbox("Impact Level:", ["ALL", "HIGH", "MEDIUM", "LOW"])
    with col_c3:
        days_ahead = st.slider("Lookahead Horizon (Days):", min_value=15, max_value=120, value=60, step=15)

    events = get_upcoming_economic_events(session, days_ahead=days_ahead, category=cat_filter, impact_level=imp_filter)

    if events:
        # Event Timeline Ribbon Cards
        today_events = [e for e in events if e["days_left"] == 0]
        high_imp = [e for e in events if e["impact_level"] == "HIGH"]
        fo_exp = [e for e in events if e["category"] == "FO_EXPIRY"]

        ek1, ek2, ek3, ek4 = st.columns(4)
        ek1.metric("🚨 Today's Events", f"{len(today_events)} catalysts", delta="Immediate Impact" if today_events else "Clear Session")
        ek2.metric("⚡ High Impact Events", f"{len(high_imp)} catalysts")
        ek3.metric("🎯 F&O Expiries Ahead", f"{len(fo_exp)} expiries")
        ek4.metric("📅 Total Upcoming Catalysts", f"{len(events)} events")

        st.markdown("---")

        df_ev = pd.DataFrame(events)[["event_date", "status", "event_name", "category", "impact_level", "affected_sector", "description"]]

        st.dataframe(
            df_ev.rename(columns={
                "event_date": "Date", "status": "Countdown", "event_name": "Market Event Catalyst",
                "category": "Category", "impact_level": "Impact",
                "affected_sector": "Impacted Sector", "description": "Key Details"
            }),
            use_container_width=True,
            height=420,
            hide_index=True
        )
    else:
        st.info("No events found matching the selected filter criteria.")

session.close()
