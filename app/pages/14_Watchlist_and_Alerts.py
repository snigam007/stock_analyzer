"""
Watchlist Management, 52-Week High/Low Radar & Alert Center
- Manage multiple custom watchlists with custom targets, stop-losses, and personal research notes
- Real-time 52-Week High Breakout and 52-Week Low Breakdown Proximity Radar
- Live Alert Notification Stream with trigger history
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

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
if not hasattr(db.database, "Watchlist"):
    importlib.reload(db.database)

from db.database import get_global_engine, get_session, Stock
from core.watchlist_manager import (
    get_all_watchlists, create_watchlist, delete_watchlist,
    get_watchlist_items, add_item_to_watchlist, remove_item_from_watchlist,
    get_52_week_high_low_radar, evaluate_and_generate_alerts, get_recent_alerts
)

st.set_page_config(page_title="⭐ Watchlists & 52W Radar", page_icon="⭐", layout="wide")

# Custom CSS
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, rgba(26,32,44,0.7) 0%, rgba(15,23,42,0.8) 100%);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 12px;
    }
    .badge-bull {
        background-color: rgba(16, 185, 129, 0.2);
        color: #10B981;
        padding: 3px 8px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .badge-bear {
        background-color: rgba(239, 68, 68, 0.2);
        color: #EF4444;
        padding: 3px 8px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.85rem;
    }
</style>
""", unsafe_allow_html=True)

st.title("⭐ Watchlists, 52-Week Radar & Alert Center")
st.caption("Institutional-grade portfolio monitoring, multi-watchlist target tracking, and 52-week breakout surveillance.")

engine = get_global_engine()
session = get_session(engine)

# Tabs
tab1, tab2, tab3 = st.tabs(["⭐ My Watchlists", "📡 52-Week High / Low Radar", "🔔 Real-Time Alerts Dispatcher"])

# ─── TAB 1: WATCHLISTS ────────────────────────────────────────────────────────
with tab1:
    col_wl_sel, col_wl_create = st.columns([2, 1])

    watchlists = get_all_watchlists(session)
    wl_options = {wl["name"]: wl["id"] for wl in watchlists}

    with col_wl_sel:
        selected_wl_name = st.selectbox("📂 Select Watchlist:", list(wl_options.keys()), index=0)
        selected_wl_id = wl_options[selected_wl_name]

    with col_wl_create:
        with st.popover("➕ Create New Watchlist"):
            new_wl_name = st.text_input("Watchlist Name:", placeholder="e.g. EV & Green Energy")
            new_wl_desc = st.text_input("Description:", placeholder="e.g. Long-term thematic basket")
            if st.button("Save Watchlist", use_container_width=True, type="primary"):
                if new_wl_name:
                    new_id = create_watchlist(new_wl_name, new_wl_desc, session)
                    if new_id:
                        st.success(f"Watchlist '{new_wl_name}' created!")
                        st.rerun()
                    else:
                        st.error("Failed to create watchlist (name may already exist).")

    # Add Stock to Current Watchlist Popover
    with st.expander("➕ Add Stock to this Watchlist", expanded=False):
        all_stocks = session.query(Stock).filter(Stock.is_active == True).order_by(Stock.symbol).all()
        stock_options = [f"{s.symbol} — {s.name} ({s.sector})" for s in all_stocks]

        col_s1, col_s2, col_s3, col_s4 = st.columns([2, 1, 1, 1])
        with col_s1:
            chosen_stock_str = st.selectbox("Select Stock:", stock_options)
            chosen_symbol = chosen_stock_str.split(" — ")[0] if chosen_stock_str else ""
        with col_s2:
            t_buy = st.number_input("Target Buy (₹):", min_value=0.0, value=0.0, step=5.0)
        with col_s3:
            t_sell = st.number_input("Target Sell (₹):", min_value=0.0, value=0.0, step=5.0)
        with col_s4:
            s_loss = st.number_input("Stop Loss (₹):", min_value=0.0, value=0.0, step=5.0)

        notes = st.text_input("Research Notes / Thesis:", placeholder="e.g. Breakout retest on 50 EMA with strong delivery")

        if st.button("Add to Watchlist", type="primary"):
            if chosen_symbol:
                ok = add_item_to_watchlist(
                    watchlist_id=selected_wl_id,
                    symbol=chosen_symbol,
                    target_buy_price=t_buy if t_buy > 0 else None,
                    target_sell_price=t_sell if t_sell > 0 else None,
                    stop_loss=s_loss if s_loss > 0 else None,
                    notes=notes,
                    session=session,
                )
                if ok:
                    st.success(f"Added {chosen_symbol} to {selected_wl_name}!")
                    st.rerun()

    # Display items in Watchlist
    items = get_watchlist_items(selected_wl_id, session)

    if items:
        # Summary KPI Ribbon
        avg_score = np.mean([it["composite_score"] for it in items])
        bullish_items = sum(1 for it in items if it["signal"] == "BUY")
        near_buy_targets = sum(1 for it in items if it["dist_to_buy_pct"] is not None and abs(it["dist_to_buy_pct"]) <= 2.0)

        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("📦 Tracked Assets", f"{len(items)} stocks")
        kpi2.metric("🎯 Average Score", f"{avg_score:.1f}/100")
        kpi3.metric("🟢 BUY Signals", f"{bullish_items} active")
        kpi4.metric("🔔 Near Buy Target", f"{near_buy_targets} stocks")

        st.markdown("---")

        # Table Display
        df_items = pd.DataFrame(items)
        disp_cols = [
            "symbol", "name", "sector", "current_price", "daily_return",
            "signal", "composite_score", "target_buy_price", "target_sell_price",
            "dist_to_buy_pct", "stop_loss", "notes"
        ]
        df_disp = df_items[disp_cols].rename(columns={
            "symbol": "Symbol", "name": "Company", "sector": "Sector",
            "current_price": "Price (₹)", "daily_return": "1D Return %",
            "signal": "Signal", "composite_score": "Score",
            "target_buy_price": "Target Buy (₹)", "target_sell_price": "Target Sell (₹)",
            "dist_to_buy_pct": "Dist to Buy %", "stop_loss": "Stop Loss (₹)", "notes": "Notes"
        })

        st.dataframe(
            df_disp.style.format({
                "Price (₹)": "₹{:,.2f}",
                "1D Return %": "{:+.2f}%",
                "Score": "{:.1f}",
                "Target Buy (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) and x else "—",
                "Target Sell (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) and x else "—",
                "Dist to Buy %": lambda x: f"{x:+.2f}%" if pd.notnull(x) and x is not None else "—",
                "Stop Loss (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) and x else "—",
            }),
            use_container_width=True,
            height=380,
            hide_index=True
        )

        # Quick Delete Action
        col_del_item, col_del_wl = st.columns([3, 1])
        with col_del_item:
            item_to_remove = st.selectbox("Select item to remove:", [f"{it['item_id']}: {it['symbol']} — {it['name']}" for it in items])
            if st.button("🗑️ Remove Selected Stock"):
                rem_id = int(item_to_remove.split(":")[0])
                if remove_item_from_watchlist(rem_id, session):
                    st.success("Item removed!")
                    st.rerun()
        with col_del_wl:
            if len(watchlists) > 1:
                if st.button("⚠️ Delete Entire Watchlist", type="secondary"):
                    if delete_watchlist(selected_wl_id, session):
                        st.success("Watchlist deleted!")
                        st.rerun()
    else:
        st.info(f"Watchlist '{selected_wl_name}' is currently empty. Add stocks above to begin tracking!")


# ─── TAB 2: 52-WEEK HIGH / LOW RADAR ──────────────────────────────────────────
with tab2:
    st.subheader("📡 52-Week High & Low Surveillance Radar")
    st.caption("Identify momentum breakout leaders and deeply oversold bargain opportunities across the entire NSE universe.")

    radar = get_52_week_high_low_radar(session)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🚀 52W High Breakouts", f"{len(radar['breakout_52w_high'])} stocks", delta="ATH / 52W High")
    m2.metric("🎯 Near 52W High (<=3%)", f"{len(radar['near_52w_high'])} stocks", delta="Breakout Candidates")
    m3.metric("🛡️ Near 52W Low (<=3%)", f"{len(radar['near_52w_low'])} stocks", delta="Value / Oversold")
    m4.metric("⚠️ 52W Low Breakdowns", f"{len(radar['breakdown_52w_low'])} stocks", delta="Bearish Breakdown")

    radar_subtab1, radar_subtab2, radar_subtab3 = st.tabs([
        "🚀 52W High Breakouts & Near High", "🛡️ 52W Low & Bargain Hunt", "📊 All Universe Proximity Matrix"
    ])

    with radar_subtab1:
        high_stocks = radar["breakout_52w_high"] + radar["near_52w_high"]
        if high_stocks:
            df_high = pd.DataFrame(high_stocks)[["symbol", "name", "sector", "current_price", "high_52w", "dist_52w_high_pct", "signal", "composite_score"]]
            st.dataframe(
                df_high.rename(columns={
                    "symbol": "Symbol", "name": "Company", "sector": "Sector",
                    "current_price": "Price (₹)", "high_52w": "52W High (₹)",
                    "dist_52w_high_pct": "Dist from High %", "signal": "Signal", "composite_score": "Score"
                }).style.format({
                    "Price (₹)": "₹{:,.2f}",
                    "52W High (₹)": "₹{:,.2f}",
                    "Dist from High %": "{:+.2f}%",
                    "Score": "{:.1f}"
                }),
                use_container_width=True,
                height=350,
                hide_index=True
            )
        else:
            st.info("No stocks currently within 3.5% of 52W High.")

    with radar_subtab2:
        low_stocks = radar["breakdown_52w_low"] + radar["near_52w_low"]
        if low_stocks:
            df_low = pd.DataFrame(low_stocks)[["symbol", "name", "sector", "current_price", "low_52w", "dist_52w_low_pct", "signal", "composite_score"]]
            st.dataframe(
                df_low.rename(columns={
                    "symbol": "Symbol", "name": "Company", "sector": "Sector",
                    "current_price": "Price (₹)", "low_52w": "52W Low (₹)",
                    "dist_52w_low_pct": "Dist from Low %", "signal": "Signal", "composite_score": "Score"
                }).style.format({
                    "Price (₹)": "₹{:,.2f}",
                    "52W Low (₹)": "₹{:,.2f}",
                    "Dist from Low %": "{:+.2f}%",
                    "Score": "{:.1f}"
                }),
                use_container_width=True,
                height=350,
                hide_index=True
            )
        else:
            st.info("No stocks currently within 3.5% of 52W Low.")

    with radar_subtab3:
        all_rad = radar["all_stocks_radar"]
        if all_rad:
            df_all = pd.DataFrame(all_rad)
            fig_scatter = px.scatter(
                df_all,
                x="dist_52w_high_pct",
                y="composite_score",
                color="sector",
                hover_name="symbol",
                hover_data=["current_price", "signal"],
                title="52-Week High Proximity vs 5-Pillar Composite Score",
                labels={"dist_52w_high_pct": "Distance from 52W High (%)", "composite_score": "Composite Score (0-100)"},
                template="plotly_dark",
                height=450,
            )
            fig_scatter.add_vline(x=-3.0, line_dash="dash", line_color="#10B981", annotation_text="Breakout Zone (-3%)")
            st.plotly_chart(fig_scatter, use_container_width=True)


# ─── TAB 3: REAL-TIME ALERTS DISPATCHER ───────────────────────────────────────
with tab3:
    st.subheader("🔔 Live Alert Trigger Log")
    st.caption("Automated execution alerts triggered by price target breaches, 52W breakouts, and stop losses.")

    if st.button("🔄 Re-evaluate All Alert Triggers Now", type="primary"):
        triggered = evaluate_and_generate_alerts(session)
        st.success(f"Evaluated alert rules! Triggered {len(triggered)} new alerts.")
        st.rerun()

    recent_alerts = get_recent_alerts(session, limit=40)

    if recent_alerts:
        df_al = pd.DataFrame(recent_alerts)[["symbol", "alert_type", "condition_value", "current_value", "message", "triggered_at"]]
        st.dataframe(
            df_al.rename(columns={
                "symbol": "Symbol", "alert_type": "Alert Rule",
                "condition_value": "Trigger Level (₹)", "current_value": "Trigger Price (₹)",
                "message": "Notification Message", "triggered_at": "Timestamp"
            }).style.format({
                "Trigger Level (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) and x else "—",
                "Trigger Price (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) and x else "—",
            }),
            use_container_width=True,
            height=420,
            hide_index=True
        )
    else:
        st.info("No active alerts logged yet. Create watchlists with target prices or wait for 52W breakouts!")

session.close()
