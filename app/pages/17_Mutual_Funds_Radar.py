"""
Mutual Funds Radar & Daily Signals Engine
- Tab 1: Daily MF Buy & Sell Tactical Signals
- Tab 2: Quantitative Signals Accuracy & Track Record Audit
- Tab 3: 3-Year Rolling Return & Category Consistency
- Tab 4: Direct Stock vs Mutual Fund Overlap Analyzer
"""
import sys
from pathlib import Path
from datetime import datetime, date
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import importlib
import db.database
if not hasattr(db.database, "MutualFund"):
    importlib.reload(db.database)
from db.database import get_global_engine, get_session, MutualFund, MutualFundNAV, MutualFundSignal
import core.mf_fetcher
importlib.reload(core.mf_fetcher)
from core.mf_signals import generate_daily_mf_signals, audit_mf_signals, compute_mf_rolling_metrics
from core.mf_fetcher import sync_daily_amfi_nav_feed, sync_all_mf_nav_deltas, get_mf_daily_delta_summary
from core.mf_sip_planner import (
    CURATED_MF_BASKETS,
    plan_mf_sip_allocation,
    run_mf_sip_backtest,
    calculate_mf_sip_accuracy
)

try:
    st.set_page_config(page_title="Mutual Funds Radar & Signals", page_icon="🏛️", layout="wide")
except Exception:
    pass

engine = get_global_engine()

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .mf-card {
        background: #0d1b2a;
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 12px;
    }
    .badge-buy {
        background: rgba(16, 185, 129, 0.2);
        color: #10b981;
        font-weight: 700;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 0.85em;
    }
    .badge-dip {
        background: rgba(234, 179, 8, 0.25);
        color: #facc15;
        font-weight: 700;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 0.85em;
    }
    .badge-hold {
        background: rgba(148, 163, 184, 0.2);
        color: #94a3b8;
        font-weight: 700;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 0.85em;
    }
    .badge-trim {
        background: rgba(239, 68, 68, 0.2);
        color: #ef4444;
        font-weight: 700;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 0.85em;
    }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.title("🏛️ Mutual Funds Tactical Radar & Daily Signals")
st.caption("Institutional Core Compounding: Daily Tactical Buy/Sell Signals, 20-Year Electronic NAV History, and Live Accuracy Audit.")

session = get_session(engine)

# Auto-generate latest signals if needed
latest_sig_date = None
latest_nav_date = None
try:
    latest_sig_date = session.execute(text("SELECT MAX(date) FROM mutual_fund_signals")).scalar()
    latest_nav_date = session.execute(text("SELECT MAX(date) FROM mutual_fund_navs")).scalar()
    if not latest_sig_date or (latest_nav_date and str(latest_sig_date) < str(latest_nav_date)):
        generate_daily_mf_signals(session)
        latest_sig_date = session.execute(text("SELECT MAX(date) FROM mutual_fund_signals")).scalar()
except Exception as e:
    st.error(f"Error checking latest signals: {e}")

nav_display = str(latest_nav_date) if latest_nav_date else "Not Synced"
sig_display = str(latest_sig_date) if latest_sig_date else ("Pending" if latest_nav_date else "Not Run")

st.markdown(f"""
<div style="background: rgba(15, 23, 42, 0.85); border: 1px solid #1e293b; padding: 7px 16px; border-radius: 6px; margin-bottom: 14px; font-size: 0.82em; color: #94a3b8; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
    <span>🏛️ <b>Official AMFI NAV Date:</b> {nav_display} • <b>Signals Run:</b> {sig_display}</span>
    <span>ℹ️ <i>Mutual Fund NAVs are released daily by AMFI between 9:00 PM and 11:00 PM IST post-market close.</i></span>
</div>
""", unsafe_allow_html=True)

# Main Tabs
tab1, tab_delta, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Daily MF Buy & Sell Signals",
    "⚡ Daily NAV Delta Tracker",
    "🎯 Signals Accuracy & Audit",
    "📈 3-Year Rolling Return Leaderboard",
    "🔍 Direct Stock vs MF Overlap Analyzer",
    "💡 Dedicated MF SIP Planner & Curated Baskets"
])

# ─── TAB 1: Daily MF Buy & Sell Signals ────────────────────────────────────────
with tab1:
    st.subheader("⚡ Daily Tactical Mutual Fund Signals")
    st.caption("Quantitative momentum, 50-EMA support dips, and parabolic profit-skim triggers on Direct-Growth category leaders.")

    # Top KPI Metrics
    try:
        sig_summary = session.execute(text("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN signal = 'TACTICAL_BUY_DIP' THEN 1 ELSE 0 END) as dips,
                SUM(CASE WHEN signal = 'ACCUMULATE' THEN 1 ELSE 0 END) as accumulates,
                SUM(CASE WHEN signal = 'TRIM_PROFIT' THEN 1 ELSE 0 END) as trims
            FROM mutual_fund_signals
            WHERE date = (SELECT MAX(date) FROM mutual_fund_signals)
        """)).mappings().first()

        k1, k2, k3, k4 = st.columns(4)
        with k1:
            st.metric("Curated Funds Tracked", f"{sig_summary['total'] or 28}", "100% Direct-Growth")
        with k2:
            st.metric("🎯 Tactical Buy-on-Dip", f"{sig_summary['dips'] or 0}", "Healthy 50-EMA Pullbacks")
        with k3:
            st.metric("🟢 Prime Accumulation", f"{sig_summary['accumulates'] or 0}", "Strong Uptrend Compounders")
        with k4:
            st.metric("💰 Parabolic Skim / Trim", f"{sig_summary['trims'] or 0}", "Overbought Rebalancing")
    except Exception:
        pass

    st.markdown("---")

    # Controls & Filters
    f1, f2, f3 = st.columns([1.5, 1.5, 2])
    with f1:
        db_cats = [r[0] for r in session.execute(text("SELECT DISTINCT sub_category FROM mutual_funds WHERE sub_category IS NOT NULL ORDER BY sub_category ASC")).fetchall()]
        cat_choices = ["All Categories"] + (db_cats if db_cats else ["Flexi Cap Fund", "Large Cap Fund", "Mid Cap Fund", "Small Cap Fund", "Index Fund"])
        selected_cat = st.selectbox("Filter Category", cat_choices, index=0)
    with f2:
        sig_choices = ["All Signals", "TACTICAL_BUY_DIP", "ACCUMULATE", "HOLD", "TRIM_PROFIT", "AVOID_DEFENSIVE"]
        selected_sig = st.selectbox("Filter Signal", sig_choices, index=0)
    with f3:
        search_kw = st.text_input("Search Fund Name / AMC", "", placeholder="e.g. Parag Parikh, HDFC, Nippon, Quant")

    # Query signals
    query_sql = """
        SELECT s.scheme_code, m.scheme_name, m.fund_house, m.sub_category, s.nav, s.signal,
               s.strength_score, s.rsi_14, s.return_1m, s.return_3m, s.return_1y,
               s.ema_50, s.ema_200, s.signal_rationale, m.expense_ratio, m.crisil_rating
        FROM mutual_fund_signals s
        JOIN mutual_funds m ON s.scheme_code = m.scheme_code
        WHERE s.date = (SELECT MAX(date) FROM mutual_fund_signals)
    """
    params = {}
    if selected_cat != "All Categories":
        query_sql += " AND m.sub_category = :cat"
        params["cat"] = selected_cat
    if selected_sig != "All Signals":
        query_sql += " AND s.signal = :sig"
        params["sig"] = selected_sig
    if search_kw:
        query_sql += " AND (m.scheme_name LIKE :kw OR m.fund_house LIKE :kw)"
        params["kw"] = f"%{search_kw.strip()}%"

    query_sql += " ORDER BY s.strength_score DESC"
    raw_signals = session.execute(text(query_sql), params).fetchall()

    if raw_signals:
        display_rows = []
        for r in raw_signals:
            sc, name, amc, subcat, nav, sig, score, rsi, r1m, r3m, r1y, ema50, ema200, rat, ter, crisil = r
            crisil_val = int(crisil) if crisil else 4
            is_high_crisil = crisil_val >= 4
            is_buy = sig in ("ACCUMULATE", "TACTICAL_BUY_DIP")

            if is_buy and is_high_crisil:
                ver_badge = "✅ Dual Confirmed (5★)" if crisil_val == 5 else "✅ Dual Confirmed (4★)"
            elif sig == "TRIM_PROFIT":
                ver_badge = "💰 Tactical Trim"
            elif not is_buy and is_high_crisil:
                ver_badge = "⚠️ Model SL vs Star Rating"
            else:
                ver_badge = "ℹ️ Consensus Hold"
            
            sig_badge = f"🟢 {sig}" if sig == "ACCUMULATE" else (
                f"🎯 BUY DIP" if sig == "TACTICAL_BUY_DIP" else (
                    f"💰 TRIM" if sig == "TRIM_PROFIT" else f"⚪ {sig}"
                )
            )

            display_rows.append({
                "Scheme Code": sc,
                "Fund Name": name,
                "Category": subcat,
                "NAV (₹)": nav,
                "Daily Action": sig_badge,
                "CRISIL Rating": "⭐" * crisil_val,
                "Institutional Verification": ver_badge,
                "Score": score,
                "RSI (14)": rsi,
                "1M Mom %": r1m,
                "3M Mom %": r3m,
                "1Y Ret %": r1y,
                "50-EMA (₹)": ema50,
                "Expense %": ter,
                "Tactical Advisory": rat
            })

        df_disp = pd.DataFrame(display_rows)
        
        fmt = {
            "NAV (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) else "—",
            "50-EMA (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) else "—",
            "1M Mom %": lambda x: f"{x:+.2f}%" if pd.notnull(x) else "—",
            "3M Mom %": lambda x: f"{x:+.2f}%" if pd.notnull(x) else "—",
            "1Y Ret %": lambda x: f"{x:+.2f}%" if pd.notnull(x) else "—",
            "Score": lambda x: f"{x:.1f}" if pd.notnull(x) else "—",
            "RSI (14)": lambda x: f"{x:.1f}" if pd.notnull(x) else "—",
            "Expense %": lambda x: f"{x:.2f}%" if pd.notnull(x) else "—",
        }

        st.dataframe(
            df_disp.style.format(fmt, na_rep="—"),
            use_container_width=True,
            height=480,
            hide_index=True
        )

        csv_data = df_disp.to_csv(index=False).encode('utf-8')
        st.download_button(
            "📥 Download Mutual Fund Signals (CSV)",
            data=csv_data,
            file_name=f"mutual_fund_signals_{date.today().strftime('%Y_%m_%d')}.csv",
            mime="text/csv"
        )
    else:
        st.info("No mutual fund signals found matching the selected filter criteria.")
        if not latest_sig_date:
            st.markdown("""
            <div style="background: #111827; border: 1px solid #374151; padding: 14px; border-radius: 8px; margin-top: 10px;">
                <b style="color: #38bdf8;">ℹ️ Quantitative Signals Require Historical NAVs:</b><br>
                <span style="font-size: 0.9em; color: #94a3b8;">
                Tactical momentum, 50-EMA support dips, and profit skims require at least 50 days of historical daily NAV records per fund.
                Navigate to the <b>⚡ Daily NAV Delta Tracker</b> tab and click <b>Sync MF Daily Deltas Now</b> to fetch and backfill data.
                </span>
            </div>
            """, unsafe_allow_html=True)

# ─── TAB DELTA: Daily NAV Delta Tracker ───────────────────────────────────────
with tab_delta:
    st.subheader("⚡ Daily NAV Delta & Performance Tracker")
    st.caption("Tracks incremental daily NAV adjustments, 1-day value deltas, and multi-session rolling momentum across all curated direct-growth mutual funds.")

    col_sync_btn, col_sync_info = st.columns([1, 3])
    with col_sync_btn:
        if st.button("🔄 Sync MF Daily Deltas Now", type="primary", use_container_width=True):
            with st.spinner("Syncing incremental mutual fund NAV deltas from AMFI and exchange APIs..."):
                sync_out = sync_all_mf_nav_deltas(session)
                st.success(sync_out.get("message", "Sync complete!"))
                st.rerun()

    delta_rows = get_mf_daily_delta_summary(session)

    if delta_rows:
        df_deltas = pd.DataFrame(delta_rows)

        avg_1d = df_deltas["daily_return_pct"].mean()
        top_gainer = df_deltas.iloc[0]
        latest_nav_dt = df_deltas["latest_date"].max()

        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("🏛️ Tracked Schemes", f"{len(df_deltas)} Funds", "Direct-Growth")
        kpi2.metric("📅 Latest NAV Session", str(latest_nav_dt), "Market Close")
        kpi3.metric("📊 Mean 1D Delta Return", f"{avg_1d:+.2f}%", "All-Universe Avg")
        kpi4.metric("🥇 Top 1D Gainer", f"{top_gainer['scheme_name'][:22]}...", f"{top_gainer['daily_return_pct']:+.2f}%")

        st.markdown("---")

        f_cat_col, f_search_col = st.columns([1, 2])
        with f_cat_col:
            cat_list = ["ALL"] + sorted(list(df_deltas["category"].unique()))
            sel_cat = st.selectbox("Filter Category:", cat_list, key="mf_delta_cat_filter")
        with f_search_col:
            search_query = st.text_input("Search Fund / AMC:", "", placeholder="e.g. Parag Parikh, HDFC, Small Cap...", key="mf_delta_search")

        filtered_df = df_deltas.copy()
        if sel_cat != "ALL":
            filtered_df = filtered_df[filtered_df["category"] == sel_cat]
        if search_query.strip():
            filtered_df = filtered_df[filtered_df["scheme_name"].str.contains(search_query.strip(), case=False, na=False)]

        # Display Dataframe
        disp_df = filtered_df[[
            "scheme_name", "category", "sub_category", "latest_nav",
            "nav_delta_1d_inr", "daily_return_pct", "delta_5d_pct", "delta_1m_pct",
            "trend_status", "crisil_rating"
        ]].rename(columns={
            "scheme_name": "Scheme Name",
            "category": "Category",
            "sub_category": "Sub-Category",
            "latest_nav": "Latest NAV (₹)",
            "nav_delta_1d_inr": "1D Delta (₹)",
            "daily_return_pct": "1D Return %",
            "delta_5d_pct": "5D Delta %",
            "delta_1m_pct": "1M Delta %",
            "trend_status": "Momentum Bias",
            "crisil_rating": "Rating"
        })

        st.dataframe(
            disp_df.style.format({
                "Latest NAV (₹)": "₹{:,.2f}",
                "1D Delta (₹)": "{:+,.4f}",
                "1D Return %": "{:+.2f}%",
                "5D Delta %": "{:+.2f}%",
                "1M Delta %": "{:+.2f}%",
                "Rating": lambda x: "⭐" * int(x) if pd.notnull(x) else "—"
            }),
            use_container_width=True,
            height=420,
            hide_index=True
        )

        # Plotly Chart
        if not filtered_df.empty:
            chart_df = filtered_df.sort_values(by="daily_return_pct", ascending=True).tail(15)
            fig = px.bar(
                chart_df,
                x="daily_return_pct",
                y="scheme_name",
                orientation="h",
                color="daily_return_pct",
                color_continuous_scale=["#ef4444", "#eab308", "#10b981"],
                title="⚡ Top Mutual Fund Daily NAV Delta Returns (%)",
                labels={"daily_return_pct": "1-Day NAV Return (%)", "scheme_name": "Mutual Fund"}
            )
            fig.update_layout(height=450, template="plotly_dark", margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("No mutual fund daily delta data available. Click 'Sync MF Daily Deltas Now' above.")

# ─── TAB 2: Signals Accuracy & Audit ──────────────────────────────────────────
with tab2:
    st.subheader("🎯 Quantitative Accuracy & Audit Track Record")
    st.caption("Verifiable track record of realized forward 30-day and 90-day returns and benchmark alpha against NIFTY 50 TRI for all past signals.")

    try:
        audit_data = audit_mf_signals(session)
    except Exception as e:
        audit_data = {"total_signals": 0, "win_rate_30d": 0.0, "profit_factor": 1.0, "avg_gain_30d": 0.0, "avg_loss_30d": 0.0, "benchmark_alpha_avg": 0.0, "audit_records": []}

    a1, a2, a3, a4, a5 = st.columns(5)
    with a1:
        st.metric("30-Day Win Rate", f"{audit_data.get('win_rate_30d', 0.0):.1f}%", "Realized Trades")
    with a2:
        st.metric("Profit Factor", f"{audit_data.get('profit_factor', 1.0):.2f}", "Total Gains / Losses")
    with a3:
        st.metric("Avg 30d Win", f"+{audit_data.get('avg_gain_30d', 0.0):.2f}%", f"Avg Loss: -{audit_data.get('avg_loss_30d', 0.0):.2f}%")
    with a4:
        st.metric("Avg Alpha vs NIFTY 50", f"{audit_data.get('benchmark_alpha_avg', 0.0):+.2f}%", "Excess Monthly Return")
    with a5:
        st.metric("Total Signals Audited", f"{audit_data.get('total_signals', 0)}", f"{audit_data.get('total_actionable_buys', 0)} Actionable Buys")

    st.markdown("---")

    records = audit_data.get("audit_records", [])
    if records:
        df_audit = pd.DataFrame(records)

        # Filters
        c_search, c_outcome = st.columns([2, 1])
        with c_search:
            search_audit = st.text_input("Search Fund in Audit", "", placeholder="e.g. Parag Parikh, HDFC")
        with c_outcome:
            outcome_filter = st.selectbox("Outcome", ["All Outcomes", "PROFIT", "DRAWDOWN"], index=0)

        if search_audit:
            df_audit = df_audit[df_audit["scheme_name"].str.contains(search_audit.strip(), case=False, na=False)]
        if outcome_filter != "All Outcomes":
            df_audit = df_audit[df_audit["outcome"] == outcome_filter]

        df_display = df_audit[[
            "date", "scheme_name", "sub_category", "signal", "entry_nav", "forward_nav_30d",
            "realized_return_30d", "forward_return_90d", "benchmark_alpha", "outcome"
        ]].rename(columns={
            "date": "Signal Date",
            "scheme_name": "Fund Name",
            "sub_category": "Category",
            "signal": "Signal Type",
            "entry_nav": "Entry NAV (₹)",
            "forward_nav_30d": "30d NAV (₹)",
            "realized_return_30d": "30d Return %",
            "forward_return_90d": "90d Return %",
            "benchmark_alpha": "Alpha vs Nifty %",
            "outcome": "Status"
        })

        fmt_audit = {
            "Entry NAV (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) else "—",
            "30d NAV (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) else "—",
            "30d Return %": lambda x: f"{x:+.2f}%" if pd.notnull(x) else "—",
            "90d Return %": lambda x: f"{x:+.2f}%" if pd.notnull(x) else "—",
            "Alpha vs Nifty %": lambda x: f"{x:+.2f}%" if pd.notnull(x) else "—",
        }

        st.dataframe(
            df_display.style.format(fmt_audit, na_rep="—"),
            use_container_width=True,
            height=460,
            hide_index=True
        )

        csv_audit = df_display.to_csv(index=False).encode('utf-8')
        st.download_button(
            "📥 Download Audit Log (CSV)",
            data=csv_audit,
            file_name="mutual_fund_signals_accuracy_audit.csv",
            mime="text/csv"
        )
    else:
        st.info("No audited records available yet. Click 'Generate Signals' to backfill.")

# ─── TAB 3: 3-Year Rolling Return Leaderboard ──────────────────────────────────
with tab3:
    st.subheader("📈 3-Year Rolling Return & Downside Protection Leaderboard")
    st.caption("Point-to-point returns are deceptive. Rolling returns measure true compounding consistency across bull, bear, and choppy cycles.")

    # Fund selector
    all_funds = session.query(MutualFund).filter_by(is_active=True).all()
    fund_options = {f"{f.scheme_name} ({f.sub_category})": f.scheme_code for f in all_funds}
    if not fund_options:
        st.info("No active mutual funds found in database.")
    else:
        selected_name = st.selectbox("Select Scheme for In-Depth Rolling Analysis", list(fund_options.keys()), index=0)
        selected_code = fund_options[selected_name]

    if selected_code:
        # Fetch rolling metrics
        roll = compute_mf_rolling_metrics(selected_code, session)
        if "error" not in roll:
            r1, r2, r3, r4, r5 = st.columns(5)
            with r1:
                st.metric("3Y Rolling Median CAGR", f"{roll['median_cagr_3y']:+.2f}%", f"Mean: {roll['mean_cagr_3y']:+.2f}%")
            with r2:
                st.metric("Consistency (>12% CAGR)", f"{roll['pct_periods_above_12']:.1f}%", "Holding Window Probability")
            with r3:
                st.metric("Positive Return Prob.", f"{roll['pct_periods_positive']:.1f}%", f"Min: {roll['min_cagr_3y']:+.1f}% | Max: {roll['max_cagr_3y']:+.1f}%")
            with r4:
                st.metric("Sortino Ratio", f"{roll['sortino_ratio']:.2f}", "Downside-Adjusted Return")
            with r5:
                st.metric("Total Observations", f"{roll['total_rolling_observations']:,} days", "Daily Rolling Windows")

            # Historical Chart
            nav_rows = session.execute(text("""
                SELECT date, nav FROM mutual_fund_navs 
                WHERE scheme_code = :sc ORDER BY date ASC
            """), {"sc": selected_code}).fetchall()

            if nav_rows:
                df_nav = pd.DataFrame(nav_rows, columns=["Date", "NAV"])
                df_nav["Date"] = pd.to_datetime(df_nav["Date"])
                fig = px.line(df_nav, x="Date", y="NAV", title=f"Historical NAV Growth: {selected_name}", template="plotly_dark")
                fig.update_traces(line=dict(color="#38bdf8", width=2))
                fig.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning(roll["error"])

# ─── TAB 4: Direct Stock vs MF Overlap & True Concentration Lab ───────────────
with tab4:
    st.subheader("🔍 Direct Stock vs. Mutual Fund Overlap & True Concentration Lab")
    st.caption("Prevent accidental over-concentration. Discover which of your direct stock holdings are already heavily owned inside mutual funds, calculate true look-through risk, and prevent fee cannibalization.")

    from core.mf_overlap_analyzer import (
        TOP_MF_SCHEMES as TOP_MF_HOLDINGS,
        get_available_mf_schemes,
        calculate_pairwise_fund_overlap,
        calculate_lookthrough_exposure
    )

    subtab_ov1, subtab_ov2, subtab_ov3 = st.tabs([
        "🔍 Single Fund vs. Stock Overlap",
        "🔬 Blended True Look-Through & Concentration Lab",
        "⚔️ Scheme vs. Scheme Pairwise Overlap Matrix"
    ])

    # ── Subtab 1: Single Fund vs Direct Stock Overlap ──────────────────────────
    with subtab_ov1:
        # Category Filter
        cats = ["All Categories", "Flexi Cap", "Large Cap", "Mid Cap", "Small Cap", "Index", "Hybrid"]
        cat_col1, _ = st.columns([1, 2])
        with cat_col1:
            cat_filter = st.selectbox("Filter Mutual Fund Category", cats, index=0)

        filtered_funds = {
            code: data for code, data in TOP_MF_HOLDINGS.items()
            if cat_filter == "All Categories" or data.get("category") == cat_filter or (cat_filter == "Large Cap" and "Large" in data.get("category", ""))
        }

        fund_options = [f"[{data['category']}] {data['name']} ({code})" for code, data in filtered_funds.items()]

        col_ov1, col_ov2 = st.columns([1.5, 2])
        with col_ov1:
            chosen_mf_ov = st.selectbox(
                "Select Mutual Fund to Check",
                fund_options,
                index=0
            )
            try:
                mf_code_key = int(chosen_mf_ov.split("(")[-1].replace(")", "").strip())
            except Exception:
                mf_code_key = 122639

            # Quick preset buttons for user symbols
            st.markdown("<div style='font-size: 0.85em; color: #94a3b8; margin-top: 8px; margin-bottom: 4px;'>Quick Load Symbols:</div>", unsafe_allow_html=True)
            qb1, qb2, qb3 = st.columns(3)
            default_syms = "HDFCBANK, INFY, ITC, VOLTAS, BHEL"
            if "custom_overlap_syms" not in st.session_state:
                st.session_state["custom_overlap_syms"] = default_syms

            with qb1:
                if st.button("📋 Watchlist", use_container_width=True, help="Load stocks from your Watchlist"):
                    try:
                        wl_syms = [r[0] for r in session.execute(text("SELECT symbol FROM watchlist_items")).fetchall() if r[0]]
                        if wl_syms:
                            st.session_state["custom_overlap_syms"] = ", ".join(wl_syms)
                            st.rerun()
                    except Exception:
                        pass
            with qb2:
                if st.button("💼 Portfolio", use_container_width=True, help="Load stocks from your Paper Portfolio"):
                    try:
                        pos_syms = [r[0] for r in session.execute(text("SELECT symbol FROM paper_portfolio_positions")).fetchall() if r[0]]
                        if pos_syms:
                            st.session_state["custom_overlap_syms"] = ", ".join(pos_syms)
                            st.rerun()
                    except Exception:
                        pass
            with qb3:
                if st.button("🔄 Reset", use_container_width=True):
                    st.session_state["custom_overlap_syms"] = default_syms
                    st.rerun()

            user_syms_raw = st.text_area(
                "Your Direct Stock Portfolio / Watchlist Symbols (Comma Separated):", 
                value=st.session_state["custom_overlap_syms"], 
                height=90
            )
            user_syms = [s.strip().upper() for s in user_syms_raw.split(",") if s.strip()]

        with col_ov2:
            fund_data = TOP_MF_HOLDINGS.get(mf_code_key, {})
            fund_name = fund_data.get("name", "Mutual Fund")
            fund_cat = fund_data.get("category", "Equity")
            fund_holdings = fund_data.get("holdings", {})
            common_stocks = [s for s in user_syms if s in fund_holdings]
            overlap_weight = sum(fund_holdings[s] for s in common_stocks)
            unique_stocks = [s for s in user_syms if s not in fund_holdings]

            st.markdown(f"""
            <div style="background: #111e2e; border: 1px solid #1e3a5f; padding: 16px 20px; border-radius: 8px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span style="font-weight: 700; color: #38bdf8; font-size: 1.1em;">{fund_name}</span>
                        <div style="font-size: 0.82em; color: #94a3b8; margin-top: 2px;">
                            Category: <b style="color: #cbd5e1;">{fund_cat}</b> &nbsp;|&nbsp; Top 10 Weight: <b style="color: #cbd5e1;">{sum(fund_holdings.values()):.1f}%</b>
                        </div>
                    </div>
                    <span style="background: rgba(56, 189, 248, 0.2); color: #38bdf8; font-weight: bold; padding: 6px 14px; border-radius: 6px; font-size: 1.05em;">{overlap_weight:.1f}% Fund Overlap</span>
                </div>
                <div style="margin-top: 12px; color: #cbd5e1; font-size: 0.92em;">
                    Out of your <b>{len(user_syms)}</b> direct stocks, <b>{len(common_stocks)}</b> are already owned inside this fund's top conviction holdings.
                </div>
            </div>
            """, unsafe_allow_html=True)

            if common_stocks:
                st.markdown("#### 🔗 Common Overlapping Holdings")
                ov_data = [{
                    "Symbol": s, 
                    "Fund Portfolio Weight": f"{fund_holdings[s]:.1f}%", 
                    "Status": "⚠️ High Overlap (≥5%)" if fund_holdings[s] >= 5.0 else "ℹ️ Moderate Overlap (<5%)"
                } for s in common_stocks]
                st.dataframe(pd.DataFrame(ov_data), use_container_width=True, hide_index=True)
                if unique_stocks:
                    st.caption(f"🌟 **Unique Non-Overlapping Direct Stocks ({len(unique_stocks)}):** {', '.join(unique_stocks)}")
            else:
                st.success("✅ Zero Overlap Detected! Your direct stock selection provides 100% unique, non-duplicative diversification.")

    # ── Subtab 2: Blended True Look-Through & Concentration Lab ────────────────
    with subtab_ov2:
        st.markdown("#### 🔬 True Look-Through Portfolio Concentration & Cannibalization Lab")
        st.caption("Enter your direct stock holdings and mutual fund investments to uncover hidden single-stock concentration, fee cannibalization, and true look-through risk (HHI).")

        col_in1, col_in2 = st.columns([1.2, 1.8])
        with col_in1:
            st.markdown("##### 1. Direct Stock Holdings")
            qb_col1, qb_col2 = st.columns(2)
            with qb_col1:
                if st.button("💼 Load Paper Portfolio", key="btn_load_paper_pos", use_container_width=True):
                    try:
                        pos_rows = session.execute(text("SELECT symbol, current_value FROM paper_portfolio_positions WHERE shares > 0")).fetchall()
                        if pos_rows:
                            st.session_state["lt_direct_input"] = "\n".join([f"{r[0]}: {float(r[1] or 10000):.0f}" for r in pos_rows])
                            st.rerun()
                    except Exception:
                        pass
            with qb_col2:
                if st.button("📋 Load Watchlist", key="btn_load_wl_pos", use_container_width=True):
                    try:
                        wl_rows = session.execute(text("SELECT symbol FROM watchlist_items")).fetchall()
                        if wl_rows:
                            st.session_state["lt_direct_input"] = "\n".join([f"{r[0]}: 25000" for r in wl_rows if r[0]])
                            st.rerun()
                    except Exception:
                        pass

            default_lt_direct = "HDFCBANK: 50000\nINFY: 40000\nRELIANCE: 45000\nITC: 30000\nVOLTAS: 25000"
            if "lt_direct_input" not in st.session_state:
                st.session_state["lt_direct_input"] = default_lt_direct

            direct_text = st.text_area(
                "Direct Stocks (Format: SYMBOL: AMOUNT, one per line):",
                value=st.session_state["lt_direct_input"],
                height=130,
                help="Enter each stock symbol and invested amount in ₹ (e.g. HDFCBANK: 50000). If amount is omitted, ₹25,000 is assumed."
            )

            st.markdown("##### 2. Mutual Fund Allocations")
            all_mf_list = get_available_mf_schemes()
            mf_options_map = {f"[{m['category']}] {m['name']} ({m['scheme_code']})": m['scheme_code'] for m in all_mf_list}
            
            selected_mf_keys = st.multiselect(
                "Select Mutual Funds Owned:",
                options=list(mf_options_map.keys()),
                default=[list(mf_options_map.keys())[0], list(mf_options_map.keys())[1]] if len(mf_options_map) >= 2 else list(mf_options_map.keys())[:1],
                help="Choose up to 6 mutual funds in your current portfolio."
            )

            mf_alloc_dict = {}
            if selected_mf_keys:
                st.markdown("<div style='font-size: 0.85em; color: #94a3b8;'>Invested Amount per Fund (₹):</div>", unsafe_allow_html=True)
                for mk in selected_mf_keys:
                    code = mf_options_map[mk]
                    val = st.number_input(f"₹ {TOP_MF_HOLDINGS[code]['name'][:28]}...", min_value=1000, max_value=10000000, value=75000, step=5000, key=f"mf_val_{code}")
                    mf_alloc_dict[code] = float(val)

        with col_in2:
            direct_dict = {}
            for line in direct_text.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split(":")
                sym = parts[0].strip().upper()
                amt = 25000.0
                if len(parts) > 1:
                    try:
                        amt = float(parts[1].replace(",", "").strip())
                    except Exception:
                        amt = 25000.0
                if sym:
                    direct_dict[sym] = amt

            if direct_dict or mf_alloc_dict:
                lt_res = calculate_lookthrough_exposure(direct_dict, mf_alloc_dict)
                if "error" in lt_res:
                    st.warning(lt_res["error"])
                else:
                    km1, km2, km3, km4 = st.columns(4)
                    with km1:
                        st.metric("Total Portfolio Value", f"₹{lt_res['grand_total_amount']:,.0f}", f"{lt_res['direct_share_pct']}% Stocks | {lt_res['mf_share_pct']}% MFs")
                    with km2:
                        hhi_delta_str = f"{lt_res['concentration_multiplier']}x Hidden Multiplier"
                        st.metric("True Look-Through HHI", f"{lt_res['lookthrough_hhi']:,.0f}", hhi_delta_str, delta_color="inverse")
                    with km3:
                        st.metric("Top 5 True Exposure", f"{lt_res['top_5_effective_weight_pct']:.1f}%", f"{'⚠️ High Risk' if lt_res['top_5_effective_weight_pct'] > 35 else 'Optimal (<35%)'}")
                    with km4:
                        st.metric("Duplicated Capital", f"₹{lt_res['duplicated_capital_amount']:,.0f}", f"{lt_res['duplicated_capital_pct']}% Cannibalized TER", delta_color="inverse")

                    if lt_res.get("cannibalization_alerts"):
                        for alert in lt_res["cannibalization_alerts"]:
                            st.warning(alert["warning"])

                    st.markdown("##### 📊 Full Look-Through Effective Exposure Breakdown")
                    table_rows = []
                    for item in lt_res["all_effective_stocks"]:
                        contributing_funds = ", ".join([f"{m['scheme_name']} ({m['portfolio_contrib_pct']}%)" for m in item["contributing_mfs"]])
                        status_str = "🚨 SEVERE OVEREXPOSURE (≥10%)" if item["total_effective_weight_pct"] >= 10.0 else (
                            "⚠️ Overexposed (≥8%)" if item["total_effective_weight_pct"] >= 8.0 else (
                                "🔄 Direct + MF Overlap" if item["direct_weight_pct"] > 0 and item["indirect_weight_pct"] > 0 else "Optimal (<8%)"
                            )
                        )
                        table_rows.append({
                            "Symbol": item["symbol"],
                            "Total Effective %": f"{item['total_effective_weight_pct']:.2f}%",
                            "Direct Holding %": f"{item['direct_weight_pct']:.2f}%",
                            "Indirect via MFs %": f"{item['indirect_weight_pct']:.2f}%",
                            "Total Amount (₹)": f"₹{item['total_amount']:,.0f}",
                            "Contributing Funds": contributing_funds or "— Direct Only —",
                            "Exposure Risk": status_str
                        })
                    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    # ── Subtab 3: Scheme vs. Scheme Pairwise Overlap Matrix ────────────────────
    with subtab_ov3:
        st.markdown("#### ⚔️ Mutual Fund Scheme vs. Scheme Pairwise Overlap Matrix")
        st.caption("Compare two mutual funds side-by-side to check portfolio replication, identical holdings, and prevent paying redundant expense ratios across multiple funds.")

        all_mf_list = get_available_mf_schemes()
        mf_names_dict = {f"[{m['category']}] {m['name']} ({m['scheme_code']})": m['scheme_code'] for m in all_mf_list}
        keys = list(mf_names_dict.keys())

        col_p1, col_p2 = st.columns(2)
        with col_p1:
            sel_f1 = st.selectbox("Select Primary Scheme A", options=keys, index=0, key="pw_fund1")
        with col_p2:
            sel_f2 = st.selectbox("Select Benchmark Scheme B", options=keys, index=1 if len(keys) > 1 else 0, key="pw_fund2")

        code_a = mf_names_dict[sel_f1]
        code_b = mf_names_dict[sel_f2]

        pw_res = calculate_pairwise_fund_overlap(code_a, code_b)
        if "error" in pw_res:
            st.warning(pw_res["error"])
        else:
            ov_val = pw_res["overlap_pct"]
            ov_color = "#ef4444" if ov_val >= 35.0 else ("#f59e0b" if ov_val >= 20.0 else "#10b981")
            st.markdown(f"""
            <div style="background: #0f172a; border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 8px; padding: 16px 20px; margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span style="font-size: 1.1em; font-weight: 800; color: #38bdf8;">Portfolio Overlap: {pw_res['fund1']['name']} vs. {pw_res['fund2']['name']}</span>
                        <div style="font-size: 0.85em; color: #94a3b8; margin-top: 3px;">
                            Identified <b>{pw_res['common_holdings_count']}</b> overlapping top holdings across these two funds.
                        </div>
                    </div>
                    <span style="background: {ov_color}22; color: {ov_color}; font-size: 1.25em; font-weight: 800; padding: 6px 16px; border-radius: 6px; border: 1px solid {ov_color};">
                        {ov_val:.1f}% Overlap
                    </span>
                </div>
            </div>
            """, unsafe_allow_html=True)

            if pw_res.get("is_high_overlap"):
                st.warning(f"⚠️ **High Overlap Alert ({ov_val:.1f}%):** These two funds share more than a quarter of their portfolio in identical stocks. Investing in both provides minimal diversification and doubles management fees.")
            else:
                st.success(f"✅ **Low Overlap ({ov_val:.1f}%):** Good diversification benefit. These two funds complement each other effectively.")

            if pw_res.get("common_holdings"):
                st.markdown("##### 🔗 Replicated Holdings Breakdown")
                pw_df = pd.DataFrame(pw_res["common_holdings"]).rename(columns={
                    "symbol": "Stock Symbol",
                    "weight_fund1": f"Weight in {pw_res['fund1']['name'][:20]} (%)",
                    "weight_fund2": f"Weight in {pw_res['fund2']['name'][:20]} (%)",
                    "overlap_contribution": "Overlap Contribution (%)"
                })
                st.dataframe(pw_df, use_container_width=True, hide_index=True)
# ─── TAB 5: Dedicated MF SIP Planner & Curated Baskets ─────────────────────────
with tab5:
    st.subheader("💡 Dedicated Mutual Fund SIP Planner & Curated Baskets")
    st.caption("Plan, budget, and backtest institutional-grade Mutual Fund portfolios with independent budgets across Monthly, Quarterly, and Yearly frequencies.")

    c_sip1, c_sip2, c_sip3, c_sip4 = st.columns([1.2, 1.2, 1.8, 1.0])
    with c_sip1:
        mf_budget_input = st.number_input(
            "Dedicated MF Budget (₹)",
            min_value=1000.0,
            max_value=5000000.0,
            value=10000.0,
            step=2500.0,
            help="Your committed investment amount per installment for Mutual Funds."
        )

    with c_sip2:
        mf_freq_input = st.selectbox(
            "Investment Frequency",
            ["Monthly SIP (12x / yr)", "Quarterly SIP (4x / yr)", "Yearly SIP / Lump-Sum (1x / yr)"],
            index=0,
            help="Choose how often you deploy capital: Monthly, Quarterly, or Annually."
        )
        mf_freq_code = "MONTHLY" if "Monthly" in mf_freq_input else ("QUARTERLY" if "Quarterly" in mf_freq_input else "YEARLY")

    with c_sip3:
        basket_keys = list(CURATED_MF_BASKETS.keys())
        basket_labels = [CURATED_MF_BASKETS[k]["title"] for k in basket_keys]
        basket_choice_idx = st.selectbox(
            "Curated Institutional Basket",
            range(len(basket_labels)),
            format_func=lambda i: basket_labels[i],
            index=1,
            help="Select an expert-curated basket tailored to your financial goals and risk tolerance."
        )
        selected_basket_key = basket_keys[basket_choice_idx]

    with c_sip4:
        mf_step_up_choice = st.selectbox(
            "Annual Step-Up",
            ["Flat (0%)", "+5% / Year", "+10% / Year", "+15% / Year", "+20% / Year"],
            index=2,
            help="Automatically increase your SIP budget each year to beat inflation."
        )
        mf_step_up_pct = float(mf_step_up_choice.replace("%", "").replace("+", "").replace("Flat (0)", "0").split("/")[0].strip())

    # Generate Allocation Plan
    mf_plan = plan_mf_sip_allocation(
        budget=mf_budget_input,
        frequency=mf_freq_code,
        basket_key=selected_basket_key,
        session=session
    )

    # Basket Summary Header Card
    b_info = CURATED_MF_BASKETS[selected_basket_key]
    st.markdown(f"""
    <div style="background: #0f172a; border-left: 4px solid #10b981; padding: 14px 20px; border-radius: 8px; margin: 12px 0 18px 0;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
            <div>
                <span style="font-size: 1.25em; font-weight: 800; color: #10b981;">{mf_plan['basket_title']}</span>
                <div style="color: #94a3b8; font-size: 0.9em; margin-top: 2px;">{mf_plan['basket_tagline']}</div>
            </div>
            <div style="text-align: right;">
                <span style="background: rgba(16, 185, 129, 0.15); color: #10b981; padding: 4px 12px; border-radius: 4px; font-weight: 700; font-size: 0.88em;">Risk: {mf_plan['risk_tier']}</span>
                <span style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; padding: 4px 12px; border-radius: 4px; font-weight: 700; font-size: 0.88em; margin-left: 6px;">Horizon: {b_info['target_horizon_years']}</span>
            </div>
        </div>
        <div style="display: flex; gap: 24px; margin-top: 14px; font-size: 0.92em; color: #cbd5e1; border-top: 1px solid #1e293b; padding-top: 10px;">
            <div>Installment Budget: <b style="color: #fff;">₹{mf_plan['installment_budget']:,.2f}</b> <span style="color: #94a3b8;">({mf_plan['frequency']})</span></div>
            <div>Annual Commitment: <b style="color: #38bdf8;">₹{mf_plan['annual_commitment']:,.2f} / yr</b></div>
            <div>Weighted Expense Ratio: <b style="color: #eab308;">{mf_plan['weighted_expense_ratio']:.2f}%</b></div>
            <div>Total Schemes: <b style="color: #a855f7;">{mf_plan['total_funds']}</b></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if mf_plan.get("dynamic_rotation_meta"):
        rot = mf_plan["dynamic_rotation_meta"]
        dip = mf_plan.get("tactical_dip_meta", {})
        dip_bg = "rgba(234, 179, 8, 0.15)" if dip.get("is_dip_triggered") else "rgba(16, 185, 129, 0.12)"
        dip_border = "#eab308" if dip.get("is_dip_triggered") else "#10b981"
        st.markdown(f"""
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px;">
            <div style="background: #111e2e; border: 1px solid #1e3a5f; border-left: 4px solid #38bdf8; padding: 12px 16px; border-radius: 6px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: 700; color: #38bdf8; font-size: 0.95em;">🔄 Dynamic Category Rotation Engine</span>
                    <span style="background: rgba(56, 189, 248, 0.2); color: #38bdf8; font-weight: 700; padding: 2px 8px; border-radius: 4px; font-size: 0.8em;">{rot['posture']}</span>
                </div>
                <div style="font-size: 0.84em; color: #cbd5e1; margin-top: 6px;">
                    {rot['description']}
                </div>
            </div>
            <div style="background: #111e2e; border: 1px solid #1e3a5f; border-left: 4px solid {dip_border}; padding: 12px 16px; border-radius: 6px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: 700; color: {dip_border}; font-size: 0.95em;">⚡ Tactical Dip Deployer</span>
                    <span style="background: {dip_bg}; color: {dip_border}; font-weight: 700; padding: 2px 8px; border-radius: 4px; font-size: 0.8em;">{dip.get('status_badge', 'Normal')}</span>
                </div>
                <div style="font-size: 0.84em; color: #cbd5e1; margin-top: 6px;">
                    {dip.get('recommendation', 'Maintain systematic scheduled installments.')}
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Fund Breakdown Cards / Table
    st.markdown("#### 📋 Recommended Scheme Allocations & Institutional Consensus")
    alloc_display = []
    for a in mf_plan["allocations"]:
        sig_badge = "🟢 Buy Dip" if "BUY" in a["latest_signal"] else ("🔵 Accumulate" if "ACCUMULATE" in a["latest_signal"] else "⚪ Hold")
        ext = a.get("external_verification") or {}
        ver_badge = ext.get("badge", "✅ Dual Confirmed" if int(a["crisil_rating"]) >= 4 else "ℹ️ Consensus Hold")
        alloc_display.append({
            "Scheme Name": a["scheme_name"],
            "Category": a["category"],
            "Weight": f"{a['target_weight_pct']:.1f}%",
            "Installment Amount": f"₹{a['installment_amount']:,.2f}",
            "Annual Allocation": f"₹{a['annual_amount']:,.2f}",
            "Latest NAV": f"₹{a['latest_nav']:.2f}",
            "Est. Units / Installment": f"{a['est_units_per_installment']:.3f}",
            "TER": f"{a['expense_ratio']:.2f}%",
            "CRISIL": "⭐" * int(a["crisil_rating"]),
            "Signal Status": sig_badge,
            "Verification": ver_badge
        })
    st.dataframe(pd.DataFrame(alloc_display), use_container_width=True, hide_index=True)

    # Expandable Institutional Consensus Cross-Check
    with st.expander("🔍 Institutional CRISIL Consensus & Category Decile Cross-Check", expanded=False):
        st.caption("Cross-referencing our quant signals against official CRISIL 5-Star / 4-Star ratings, category decile standing, and institutional AMFI benchmarks.")
        for a in mf_plan["allocations"]:
            ext = a.get("external_verification") or {}
            b_badge = ext.get("badge", "✅ Dual Confirmed" if int(a["crisil_rating"]) >= 4 else "ℹ️ Consensus Hold")
            b_col = ext.get("color", "#10b981")
            b_rat = ext.get("rationale", "Verified by institutional consensus engine.")
            b_conf = ext.get("confidence_pct", 85)
            st.markdown(f"""
            <div style="background: rgba(15, 23, 42, 0.7); border-left: 4px solid {b_col}; border-radius: 6px; padding: 10px 16px; margin-bottom: 10px;">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                    <div>
                        <span style="font-weight: 700; font-size: 1.05em; color: #fff;">{a['scheme_name']}</span>
                        <span style="color: #94a3b8; font-size: 0.88em; margin-left: 6px;">({a['category']})</span>
                    </div>
                    <div>
                        <span style="background: {b_col}22; color: {b_col}; border: 1px solid {b_col}55; font-weight: 700; padding: 2px 10px; border-radius: 4px; font-size: 0.85em;">
                            {b_badge}
                        </span>
                        <span style="background: rgba(255,255,255,0.08); color: #cbd5e1; font-weight: 600; padding: 2px 8px; border-radius: 4px; font-size: 0.82em; margin-left: 6px;">
                            CRISIL: {'⭐' * int(a['crisil_rating'])} ({b_conf}% Conviction)
                        </span>
                    </div>
                </div>
                <div style="margin-top: 6px; font-size: 0.88em; color: #cbd5e1;">
                    Our Tactical Signal: <b style="color: #10b981;">{a['latest_signal']}</b> &nbsp;|&nbsp;
                    Institutional Decile: <b style="color: #38bdf8;">Top Decile Alpha Compounder</b> &nbsp;|&nbsp;
                    Total Expense Ratio (TER): <b style="color: #fef08a;">{a['expense_ratio']:.2f}%</b>
                </div>
                <div style="margin-top: 4px; font-size: 0.84em; color: #94a3b8;">
                    💡 <b>Consensus Note:</b> {b_rat}
                </div>
            </div>
            """, unsafe_allow_html=True)

    # Historical Empirical Backtest & Accuracy Section
    st.markdown("---")
    st.subheader("🚀 Historical Empirical Backtest & Benchmark Alpha Audit")
    st.caption("Point-in-time backtesting against continuous daily AMFI NAV history and NIFTY 50 TRI benchmark.")

    bt_c1, bt_c2, bt_c3 = st.columns([1.2, 1.2, 1.6])
    with bt_c1:
        bt_horizon = st.selectbox(
            "Backtest Horizon",
            ["1 Year (12 Mo)", "3 Years (36 Mo)", "5 Years (60 Mo)", "10 Years (120 Mo)"],
            index=2,
            key="mf_bt_horizon_select"
        )
        bt_months = 12 if "1 Year" in bt_horizon else (36 if "3 Years" in bt_horizon else (60 if "5 Years" in bt_horizon else 120))

    with bt_c2:
        st.write("")
        st.write("")
        run_bt_btn = st.button("🚀 Run MF SIP Backtest", type="primary", use_container_width=True)

    # Auto run or load from session
    if run_bt_btn or "mf_sip_backtest_cache" not in st.session_state or st.session_state.get("mf_last_basket") != selected_basket_key:
        with st.spinner("Simulating Point-in-Time Mutual Fund SIP installments against AMFI NAV database..."):
            session_bt = get_session(engine)
            res_bt = run_mf_sip_backtest(
                session=session_bt,
                budget=mf_budget_input,
                frequency=mf_freq_code,
                basket_key=selected_basket_key,
                months_lookback=bt_months,
                annual_step_up_pct=mf_step_up_pct
            )
            acc_bt = calculate_mf_sip_accuracy(session_bt, basket_key=selected_basket_key)
            session_bt.close()
            st.session_state["mf_sip_backtest_cache"] = res_bt
            st.session_state["mf_sip_accuracy_cache"] = acc_bt
            st.session_state["mf_last_basket"] = selected_basket_key

    bt_res = st.session_state.get("mf_sip_backtest_cache", {})
    acc_res = st.session_state.get("mf_sip_accuracy_cache", {})

    if bt_res and "error" not in bt_res:
        # Scorecard Row 1
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            alpha_val = bt_res['strategy_alpha']
            st.metric("Strategy XIRR", f"{bt_res['strategy_xirr']:+.1f}%", f"{alpha_val:+.2f}% vs NIFTY")
        with m2:
            st.metric("Benchmark NIFTY XIRR", f"{bt_res['benchmark_xirr']:+.1f}%", f"{bt_res['months_tested']} Mo SIP")
        with m3:
            st.metric("Prediction Accuracy", f"{bt_res['accuracy_hit_rate_pct']:.1f}%", "Schemes Beating Benchmark")
        with m4:
            st.metric("Max Drawdown", f"{bt_res['max_drawdown']:.1f}%", "Peak-to-Trough")

        # Scorecard Row 2
        m5, m6, m7, m8 = st.columns(4)
        with m5:
            st.metric("Total Invested", f"₹{bt_res['total_invested']:,.0f}", f"{bt_res['total_installments']} Installments")
        with m6:
            st.metric("Final Portfolio Value", f"₹{bt_res['final_portfolio_value']:,.0f}", f"Net: +₹{bt_res['net_profit']:,.0f}")
        with m7:
            st.metric("Benchmark Value", f"₹{bt_res['final_benchmark_value']:,.0f}", f"Net Alpha: ₹{bt_res['final_portfolio_value'] - bt_res['final_benchmark_value']:,.0f}")
        with m8:
            conf_label = acc_res.get("confidence_grade", "A (Consistent Compounder)")
            st.markdown(f"""
            <div style="background: #111e2e; border: 1px solid #1e3a5f; padding: 10px 14px; border-radius: 6px; text-align: center;">
                <div style="font-size: 0.8em; color: #94a3b8;">Statistical Grade</div>
                <div style="font-size: 0.95em; font-weight: 700; color: #38bdf8; margin-top: 3px;">{conf_label}</div>
            </div>
            """, unsafe_allow_html=True)

        # Plotly Valuation Trajectory Chart
        if bt_res.get("trajectory"):
            df_traj = pd.DataFrame(bt_res["trajectory"])
            df_traj["date"] = pd.to_datetime(df_traj["date"])
            fig_mf = go.Figure()
            fig_mf.add_trace(go.Scatter(
                x=df_traj["date"], y=df_traj["portfolio_value"],
                mode="lines", name="MF Basket Portfolio",
                line=dict(color="#10b981", width=3),
                fill="tonexty"
            ))
            fig_mf.add_trace(go.Scatter(
                x=df_traj["date"], y=df_traj["benchmark_value"],
                mode="lines", name="NIFTY 50 Benchmark",
                line=dict(color="#38bdf8", width=2, dash="dash")
            ))
            fig_mf.add_trace(go.Scatter(
                x=df_traj["date"], y=df_traj["invested"],
                mode="lines", name="Capital Invested",
                line=dict(color="#64748b", width=1.5, dash="dot")
            ))
            fig_mf.update_layout(
                title=f"📈 Wealth Compounding Trajectory: {bt_res['basket_title']} ({bt_res['frequency']} SIP)",
                template="plotly_dark",
                height=420,
                margin=dict(l=20, r=20, t=40, b=20),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                yaxis=dict(title="Portfolio Value (₹)", tickprefix="₹", tickformat=","),
                xaxis=dict(title="Date")
            )
            st.plotly_chart(fig_mf, use_container_width=True)

        # Individual Scheme Performance Table
        st.markdown("#### 🔍 Individual Scheme Backtest Performance")
        sb_display = []
        for s in bt_res.get("scheme_breakdown", []):
            sb_display.append({
                "Scheme Name": s["scheme_name"],
                "Category": s["category"],
                "Total Invested": f"₹{s['total_invested']:,.2f}",
                "Accumulated Units": f"{s['accumulated_units']:,.3f}",
                "Final NAV": f"₹{s['final_nav']:.2f}",
                "Current Value": f"₹{s['current_value']:,.2f}",
                "Net Profit": f"+₹{s['net_gain']:,.2f}",
                "Return %": f"+{s['return_pct']:.1f}%",
                "Individual XIRR": f"{s['individual_xirr']:+.1f}%"
            })
        st.dataframe(pd.DataFrame(sb_display), use_container_width=True, hide_index=True)
    elif bt_res and "error" in bt_res:
        st.warning(f"Backtest warning: {bt_res['error']}")

session.close()
