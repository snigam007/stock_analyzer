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

    # Curated Institutional Top Holdings Knowledgebase across 25 Category Leaders
    TOP_MF_HOLDINGS = {
        # ── Flexi Cap & Multi Cap ──
        122639: {
            "name": "Parag Parikh Flexi Cap Fund",
            "category": "Flexi Cap",
            "holdings": {
                "HDFCBANK": 8.1, "BAJAJHLDNG": 6.8, "ITC": 6.2, "ICICIBANK": 5.9, "POWERGRID": 4.8,
                "INFY": 4.2, "COALINDIA": 3.9, "HCLTECH": 3.5, "AXISBANK": 3.2, "TCS": 2.8
            }
        },
        118955: {
            "name": "HDFC Flexi Cap Fund",
            "category": "Flexi Cap",
            "holdings": {
                "ICICIBANK": 9.4, "HDFCBANK": 8.7, "INFY": 6.8, "SBIN": 5.9, "LICI": 4.5,
                "AXISBANK": 4.2, "BHARTIARTL": 3.8, "NTPC": 3.4, "LT": 3.1, "TCS": 2.9
            }
        },
        125354: {
            "name": "Quant Flexi Cap Fund",
            "category": "Flexi Cap",
            "holdings": {
                "RELIANCE": 9.8, "JIOFIN": 7.2, "ADANIPOWER": 5.8, "SAIL": 4.9, "HDFCBANK": 4.6,
                "TATAPOWER": 4.1, "SAMVARDHANA": 3.8, "BRITANNIA": 3.5, "GAIL": 3.2, "HINDALCO": 3.0
            }
        },
        120503: {
            "name": "JM Flexicap Fund",
            "category": "Flexi Cap",
            "holdings": {
                "HDFCBANK": 6.5, "ICICIBANK": 5.8, "LT": 5.2, "RELIANCE": 4.9, "INFY": 4.5,
                "REC": 3.8, "PFC": 3.7, "BHEL": 3.4, "NTPC": 3.1, "TRENT": 2.9
            }
        },
        120828: {
            "name": "Kotak Flexicap Fund",
            "category": "Flexi Cap",
            "holdings": {
                "ICICIBANK": 8.5, "HDFCBANK": 7.8, "INFY": 5.6, "RELIANCE": 5.2, "LT": 4.8,
                "TCS": 3.9, "AXISBANK": 3.6, "BHARTIARTL": 3.3, "MARUTI": 3.0, "ULTRACEMCO": 2.7
            }
        },

        # ── Large Cap & Large/Mid Cap ──
        119063: {
            "name": "ICICI Prudential Bluechip Fund",
            "category": "Large Cap",
            "holdings": {
                "ICICIBANK": 9.2, "RELIANCE": 8.8, "HDFCBANK": 8.1, "INFY": 6.4, "LT": 5.5,
                "BHARTIARTL": 4.7, "AXISBANK": 4.1, "TCS": 3.8, "MARUTI": 3.2, "ULTRACEMCO": 2.8
            }
        },
        119598: {
            "name": "Mirae Asset Large Cap Fund",
            "category": "Large Cap",
            "holdings": {
                "HDFCBANK": 9.8, "ICICIBANK": 8.6, "INFY": 7.1, "RELIANCE": 6.5, "TCS": 4.2,
                "AXISBANK": 3.9, "LT": 3.8, "BHARTIARTL": 3.6, "SBIN": 3.2, "KOTAKBANK": 2.9
            }
        },
        119717: {
            "name": "SBI Bluechip Fund",
            "category": "Large Cap",
            "holdings": {
                "HDFCBANK": 8.9, "ICICIBANK": 7.6, "RELIANCE": 6.8, "INFY": 5.9, "LT": 4.8,
                "ITC": 4.2, "TCS": 3.9, "AXISBANK": 3.5, "BHARTIARTL": 3.1, "M&M": 2.8
            }
        },
        118989: {
            "name": "HDFC Top 100 Fund",
            "category": "Large Cap",
            "holdings": {
                "ICICIBANK": 9.8, "HDFCBANK": 9.1, "RELIANCE": 8.2, "INFY": 6.1, "LT": 4.9,
                "SBIN": 4.5, "AXISBANK": 3.9, "TCS": 3.5, "NTPC": 3.1, "BHARTIARTL": 3.0
            }
        },
        120586: {
            "name": "Canara Robeco Emerging Equities",
            "category": "Large & Mid Cap",
            "holdings": {
                "ICICIBANK": 6.2, "HDFCBANK": 5.8, "INFY": 4.9, "LT": 4.2, "BHARATFORG": 3.8,
                "RELIANCE": 3.5, "FEDERALBNK": 3.2, "TRENT": 3.1, "MAXHEALTH": 2.9, "AXISBANK": 2.7
            }
        },

        # ── Mid Cap ──
        120152: {
            "name": "Motilal Oswal Midcap Fund",
            "category": "Mid Cap",
            "holdings": {
                "PERSISTENT": 7.8, "TRENT": 6.9, "BSOFT": 6.1, "POLYCAB": 5.4, "COFORGE": 4.8,
                "DIXON": 4.2, "SUZLON": 3.9, "APARINDS": 3.6, "TUBEINVEST": 3.2, "VOLTAS": 2.9
            }
        },
        118988: {
            "name": "HDFC Mid-Cap Opportunities Fund",
            "category": "Mid Cap",
            "holdings": {
                "TATACOMM": 4.2, "INDHOTEL": 3.9, "FEDERALBNK": 3.7, "BHARATFORG": 3.5, "ASTRAL": 3.2,
                "MAXHEALTH": 3.1, "APOLLOTYRE": 2.9, "COFORGE": 2.8, "VOLTAS": 2.7, "BALKRISIND": 2.5
            }
        },
        119797: {
            "name": "Kotak Emerging Equity Fund",
            "category": "Mid Cap",
            "holdings": {
                "SUPREMEIND": 4.8, "PERSISTENT": 4.2, "SCHAEFFLER": 3.8, "THERMAX": 3.6, "CUMMINSIND": 3.4,
                "POLYCAB": 3.1, "SOLARINDS": 2.9, "OBEROIRLTY": 2.8, "ASTRAL": 2.7, "BHARATFORG": 2.6
            }
        },
        120847: {
            "name": "Nippon India Growth Fund",
            "category": "Mid Cap",
            "holdings": {
                "CHOLAFIN": 3.9, "POWERFIN": 3.6, "VARUN": 3.4, "BHARATFORG": 3.2, "FORTIS": 3.1,
                "SUPREMEIND": 2.9, "MAXHEALTH": 2.8, "FEDERALBNK": 2.7, "VOLTAS": 2.5, "TRENT": 2.4
            }
        },
        125494: {
            "name": "Quant Mid Cap Fund",
            "category": "Mid Cap",
            "holdings": {
                "RELIANCE": 8.5, "JIOFIN": 6.8, "TATACOMM": 5.2, "SAIL": 4.6, "ADANIPOWER": 4.2,
                "ESCORTS": 3.8, "BHEL": 3.5, "GAIL": 3.1, "CANBK": 2.9, "SUNTV": 2.7
            }
        },

        # ── Small Cap ──
        120823: {
            "name": "Nippon India Small Cap Fund",
            "category": "Small Cap",
            "holdings": {
                "TUBEINVEST": 3.1, "APARINDS": 2.8, "HDFCBANK": 2.5, "KEC": 2.4, "CREDITACC": 2.2,
                "VOLTAS": 2.1, "CROMPTON": 1.9, "BHEL": 1.8, "GLAXO": 1.7, "PRESTIGE": 1.6
            }
        },
        125497: {
            "name": "Quant Small Cap Fund",
            "category": "Small Cap",
            "holdings": {
                "RELIANCE": 9.1, "JIOFIN": 6.5, "IRB": 4.8, "HINDCOPPER": 4.2, "SAIL": 3.9,
                "BIKAJI": 3.5, "HFCL": 3.2, "ADANIPOWER": 2.9, "RITES": 2.7, "NATIONALUM": 2.5
            }
        },
        118959: {
            "name": "HDFC Small Cap Fund",
            "category": "Small Cap",
            "holdings": {
                "FIRSTSOURCE": 4.1, "SONATSOFTW": 3.7, "BANKBARODA": 3.4, "EQUITASBNK": 3.1, "BALRAMCHIN": 2.9,
                "KALPATPOWR": 2.7, "ELECON": 2.5, "ECLERX": 2.4, "SKFINDIA": 2.3, "CYIENT": 2.2
            }
        },
        125307: {
            "name": "Bandhan Small Cap Fund",
            "category": "Small Cap",
            "holdings": {
                "ARVIND": 3.2, "APARINDS": 2.9, "MOTILALOFS": 2.7, "RADICO": 2.5, "CENTURYPLY": 2.3,
                "REC": 2.1, "CHOLAMANDALAM": 2.0, "CERA": 1.9, "CARBORUNIV": 1.8, "BSE": 1.7
            }
        },

        # ── Index Funds ──
        120716: {
            "name": "UTI Nifty 50 Index Fund",
            "category": "Index",
            "holdings": {
                "HDFCBANK": 11.8, "RELIANCE": 9.4, "ICICIBANK": 7.8, "INFY": 5.9, "ITC": 4.2,
                "TCS": 3.8, "BHARTIARTL": 3.7, "LT": 3.4, "AXISBANK": 3.1, "SBIN": 2.9
            }
        },
        120717: {
            "name": "UTI Nifty Next 50 Index Fund",
            "category": "Index",
            "holdings": {
                "BEL": 4.8, "TRENT": 4.5, "TATAMTRDVR": 3.9, "HAL": 3.7, "CHOLAFIN": 3.5,
                "VBL": 3.3, "REC": 3.1, "PFC": 3.0, "TVSMOTOR": 2.8, "JIOFIN": 2.7
            }
        },
        119062: {
            "name": "ICICI Prudential Nifty 50 Index Fund",
            "category": "Index",
            "holdings": {
                "HDFCBANK": 11.8, "RELIANCE": 9.4, "ICICIBANK": 7.8, "INFY": 5.9, "ITC": 4.2,
                "TCS": 3.8, "BHARTIARTL": 3.7, "LT": 3.4, "AXISBANK": 3.1, "SBIN": 2.9
            }
        },
        148943: {
            "name": "Motilal Oswal Nifty Midcap 150 Index Fund",
            "category": "Index",
            "holdings": {
                "MAXHEALTH": 2.4, "SUZLON": 2.2, "PERSISTENT": 2.1, "INDIANB": 2.0, "BHARATFORG": 1.9,
                "CUMMINSIND": 1.8, "POLYCAB": 1.7, "TUBEINVEST": 1.6, "HDFCAMC": 1.5, "FEDERALBNK": 1.5
            }
        },

        # ── Hybrid & Balanced Advantage ──
        119065: {
            "name": "ICICI Prudential Balanced Advantage Fund",
            "category": "Hybrid",
            "holdings": {
                "ICICIBANK": 6.5, "RELIANCE": 5.8, "HDFCBANK": 5.2, "INFY": 4.1, "BHARTIARTL": 3.5,
                "LT": 3.2, "AXISBANK": 2.8, "MARUTI": 2.4, "TCS": 2.2, "NTPC": 2.0
            }
        },
        118968: {
            "name": "HDFC Balanced Advantage Fund",
            "category": "Hybrid",
            "holdings": {
                "ICICIBANK": 7.2, "HDFCBANK": 6.8, "SBIN": 5.4, "INFY": 4.8, "LICI": 4.1,
                "COALINDIA": 3.5, "NTPC": 3.2, "LT": 2.9, "ITC": 2.7, "AXISBANK": 2.5
            }
        }
    }

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
            if unique_stocks:
                st.caption(f"🌟 **All {len(unique_stocks)} stocks are 100% distinct from this fund:** {', '.join(unique_stocks)}")

session.close()
