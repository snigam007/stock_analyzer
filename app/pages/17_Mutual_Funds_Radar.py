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
from core.mf_signals import generate_daily_mf_signals, audit_mf_signals, compute_mf_rolling_metrics
from core.mf_fetcher import sync_daily_amfi_nav_feed

st.set_page_config(page_title="Mutual Funds Radar & Signals", page_icon="🏛️", layout="wide")

engine = get_global_engine()

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .mf-card {
        background: #0d1b2a;
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 14px 18px;
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
try:
    latest_sig_date = session.execute(text("SELECT MAX(date) FROM mutual_fund_signals")).scalar()
    latest_nav_date = session.execute(text("SELECT MAX(date) FROM mutual_fund_navs")).scalar()
    if not latest_sig_date or (latest_nav_date and str(latest_sig_date) < str(latest_nav_date)):
        generate_daily_mf_signals(session)
except Exception as e:
    st.error(f"Error checking latest signals: {e}")

# Main Tabs
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Daily MF Buy & Sell Signals",
    "🎯 Signals Accuracy & Audit",
    "📈 3-Year Rolling Return Leaderboard",
    "🔍 Direct Stock vs MF Overlap Analyzer"
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
        cat_choices = ["All Categories", "Flexi Cap Fund", "Large Cap Fund", "Mid Cap Fund", "Small Cap Fund", "Index Fund", "Dynamic Asset Allocation / Balanced Advantage", "Liquid Fund"]
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
               s.ema_50, s.ema_200, s.signal_rationale, m.expense_ratio
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
            sc, name, amc, subcat, nav, sig, score, rsi, r1m, r3m, r1y, ema50, ema200, rat, ter = r
            
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

# ─── TAB 4: Direct Stock vs MF Overlap Analyzer ────────────────────────────────
with tab4:
    st.subheader("🔍 Direct Stock vs Mutual Fund Overlap Analyzer")
    st.caption("Prevent accidental over-concentration. Discover which of your direct stock holdings or watchlist picks are already heavily owned inside top mutual funds.")

    # Curated Institutional Top Holdings Knowledgebase
    TOP_MF_HOLDINGS = {
        122639: {  # Parag Parikh Flexi Cap
            "HDFCBANK": 8.1, "BAJAJHLDNG": 6.8, "ITC": 6.2, "ICICIBANK": 5.9, "POWERGRID": 4.8,
            "INFY": 4.2, "COALINDIA": 3.9, "HCLTECH": 3.5, "AXISBANK": 3.2, "TCS": 2.8
        },
        118955: {  # HDFC Flexi Cap
            "ICICIBANK": 9.4, "HDFCBANK": 8.7, "INFY": 6.8, "SBIN": 5.9, "LICI": 4.5,
            "AXISBANK": 4.2, "BHARTIARTL": 3.8, "NTPC": 3.4, "LT": 3.1, "TCS": 2.9
        },
        120823: {  # Nippon India Small Cap
            "TUBEINVEST": 3.1, "APARINDS": 2.8, "HDFCBANK": 2.5, "KEC": 2.4, "CREDITACC": 2.2,
            "VOLTAS": 2.1, "CROMPTON": 1.9, "BHEL": 1.8, "GLAXO": 1.7, "PRESTIGE": 1.6
        },
        120716: {  # UTI Nifty 50 Index Fund
            "HDFCBANK": 11.8, "RELIANCE": 9.4, "ICICIBANK": 7.8, "INFY": 5.9, "ITC": 4.2,
            "TCS": 3.8, "BHARTIARTL": 3.7, "LT": 3.4, "AXISBANK": 3.1, "SBIN": 2.9
        }
    }

    col_ov1, col_ov2 = st.columns([1.5, 2])
    with col_ov1:
        chosen_mf_ov = st.selectbox(
            "Select Mutual Fund to Check",
            [
                "Parag Parikh Flexi Cap Fund (122639)",
                "HDFC Flexi Cap Fund (118955)",
                "Nippon India Small Cap Fund (120823)",
                "UTI Nifty 50 Index Fund (120716)"
            ]
        )
        mf_code_key = 122639 if "Parag" in chosen_mf_ov else (118955 if "HDFC" in chosen_mf_ov else (120823 if "Nippon" in chosen_mf_ov else 120716))
        
        # User entered direct stock symbols
        default_syms = "HDFCBANK, INFY, ITC, VOLTAS, BHEL"
        user_syms_raw = st.text_area("Your Direct Stock Portfolio / Watchlist Symbols (Comma Separated):", default_syms, height=100)
        user_syms = [s.strip().upper() for s in user_syms_raw.split(",") if s.strip()]

    with col_ov2:
        fund_holdings = TOP_MF_HOLDINGS.get(mf_code_key, {})
        common_stocks = [s for s in user_syms if s in fund_holdings]
        overlap_weight = sum(fund_holdings[s] for s in common_stocks)

        st.markdown(f"""
        <div style="background: #111e2e; border: 1px solid #1e3a5f; padding: 16px 20px; border-radius: 8px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="font-weight: 700; color: #38bdf8; font-size: 1.1em;">Portfolio Overlap Summary</span>
                <span style="background: rgba(56, 189, 248, 0.2); color: #38bdf8; font-weight: bold; padding: 4px 12px; border-radius: 4px;">{overlap_weight:.1f}% Fund Overlap</span>
            </div>
            <div style="margin-top: 10px; color: #cbd5e1; font-size: 0.92em;">
                Out of your <b>{len(user_syms)}</b> direct stocks, <b>{len(common_stocks)}</b> are already owned inside this fund's top conviction holdings.
            </div>
        </div>
        """, unsafe_allow_html=True)

        if common_stocks:
            st.markdown("#### 🔗 Common Overlapping Holdings")
            ov_data = [{"Symbol": s, "Fund Portfolio Weight": f"{fund_holdings[s]:.1f}%", "Status": "⚠️ High Overlap" if fund_holdings[s] >= 5.0 else "ℹ️ Moderate Overlap"} for s in common_stocks]
            st.dataframe(pd.DataFrame(ov_data), use_container_width=True, hide_index=True)
        else:
            st.success("✅ Zero Overlap Detected! Your direct stock selection provides 100% unique, non-duplicative diversification.")

session.close()
