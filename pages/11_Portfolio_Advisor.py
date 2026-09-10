"""
Page 11: Dynamic Multi-Asset Portfolio Advisor & Mandate Generator
- Institutional Portfolio Recommendations for 10, 20, 50, or custom N assets
- Multi-Asset: Equities (Large/Mid/Small), Benchmark Indexes/ETFs, and Commodities
- 3 Risk Profiles: Safe Fortress, Balanced All-Weather, High-Growth (Risky)
- 4 Horizons: Daily Swing, 1-Year, 3-Years, 5-Years
- 1-Click Deploy to Live Paper Trading Ledger & 1-Click Mandate Export
"""
import sys
from pathlib import Path
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from datetime import date, datetime

# Universal Root Directory Finder
_curr = Path(__file__).resolve()
while _curr != _curr.parent:
    if (_curr / "core").exists() and (_curr / "db").exists():
        break
    _curr = _curr.parent
BASE_DIR = _curr
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    st.set_page_config(page_title="Institutional Portfolio Advisor", page_icon="💼", layout="wide")
    
    import importlib
    import core.portfolio_analyzer
    importlib.reload(core.portfolio_analyzer)
    
    from db.database import get_global_engine, get_session
    from sqlalchemy import text
    from core.portfolio_advisor import generate_institutional_portfolio
    from core.portfolio_optimizer import execute_paper_buy
    from core.macro_regime import evaluate_macro_regime
    from core.portfolio_analyzer import (
        parse_portfolio_text,
        parse_portfolio_csv,
        analyze_custom_portfolio,
        get_searchable_assets_catalog
    )
except Exception:
    pass

engine = get_global_engine()


def format_price(p): return f"₹{p:,.2f}" if p else "—"


st.title("💼 Multi-Asset Portfolio Advisor & Health Audit Lab")
st.caption("Audit your current portfolio with real-time institutional metrics or algorithmically construct optimal 10, 20, 50+ asset diversified portfolios.")

# Top Macro Regime Context
session_m = get_session(engine)
macro_info = evaluate_macro_regime(session_m)
session_m.close()

st.markdown(f"""
<div style="background: #101c28; border-left: 4px solid #38bdf8; padding: 10px 16px; border-radius: 6px; margin-bottom: 15px;">
    <span style="font-weight: bold; color: #38bdf8;">🏛️ Current Macro Regime: {macro_info['regime']} (Score: {macro_info['macro_score']}/100)</span> &nbsp;•&nbsp; 
    <span style="color: #cbd5e1; font-size: 0.9em;">Recommended Strategic Tilt: Equities <b>{macro_info['recommended_allocation']['Equities %']}%</b> | Gold/Commodities <b>{macro_info['recommended_allocation']['Gold & Commodities %']}%</b> | Cash <b>{macro_info['recommended_allocation']['Cash & Liquid %']}%</b></span>
</div>
""", unsafe_allow_html=True)

tab_user_port, tab_model_port = st.tabs([
    "📥 Punch In My Current Portfolio (Audit & Insights)",
    "🏛️ Institutional Model Portfolios (10/20/50 Assets)"
])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1: USER PORTFOLIO AUDIT & ACTIONABLE ADVISORY
# ═══════════════════════════════════════════════════════════════════════════════
with tab_user_port:
    st.subheader("📥 Punch In Current Portfolio & Institutional Audit")
    st.caption("Input your active holdings to generate a real-time risk diagnostic, concentration audit, and actionable Buy / Hold / Trim / Exit recommendations.")

    # Ingestion Method Selector
    in_method = st.radio(
        "Select Input Method:",
        ["🔍 Interactive Search & Add (Stocks, MFs, ETFs, Commodities)", "📝 Quick Paste Text", "📂 Upload Broker CSV", "✏️ Interactive Table Editor"],
        horizontal=True,
        key="port_in_method"
    )

    parsed_holdings = []

    if in_method == "🔍 Interactive Search & Add (Stocks, MFs, ETFs, Commodities)":
        if "interactive_portfolio_holdings" not in st.session_state:
            st.session_state["interactive_portfolio_holdings"] = [
                {"symbol": "RELIANCE", "name": "Reliance Industries", "shares": 30.0, "buy_price": 2850.0, "asset_class": "Stock", "sector": "Energy"},
                {"symbol": "TCS", "name": "Tata Consultancy Services", "shares": 20.0, "buy_price": 3900.0, "asset_class": "Stock", "sector": "Information Technology"},
                {"symbol": "118955", "name": "HDFC Flexi Cap Fund - Direct Plan", "shares": 100.0, "buy_price": 280.0, "asset_class": "Mutual Fund", "sector": "MF: Equity"},
                {"symbol": "GOLDBEES.NS", "name": "Nippon India ETF Gold BeES", "shares": 50.0, "buy_price": 120.0, "asset_class": "Index / ETF", "sector": "Precious Metals"},
            ]

        st.markdown("##### 🔍 Search & Add Any Asset to Your Portfolio")
        st.caption("Search across 366 Equities, 28 Mutual Funds, 20 Benchmark Indexes & ETFs, and MCX Commodities before adding.")

        col_cat, col_srch = st.columns([1.2, 3])
        with col_cat:
            cat_choice = st.selectbox(
                "Filter Category:",
                ["🌐 All Instruments", "🏢 Stocks (366)", "🏦 Mutual Funds (28)", "📊 Indexes & ETFs (20)", "🪙 Commodities (7)"],
                index=0,
                key="catalog_cat_choice"
            )
        
        session_cat = get_session(engine)
        catalog = get_searchable_assets_catalog(session_cat, category=cat_choice)
        session_cat.close()

        catalog_labels = [x["display_label"] for x in catalog]
        label_to_item = {x["display_label"]: x for x in catalog}

        with col_srch:
            chosen_label = st.selectbox(
                "Search Instrument (Type Company, Ticker, Mutual Fund Name, ETF, or Commodity):",
                options=catalog_labels,
                index=0 if catalog_labels else None,
                key="search_asset_box"
            )

        if chosen_label and chosen_label in label_to_item:
            selected_item = label_to_item[chosen_label]

            # Preview mini-card
            ac_badge = selected_item["asset_class"]
            badge_bg = "#10b981" if ac_badge == "Stock" else ("#38bdf8" if ac_badge == "Mutual Fund" else ("#a855f7" if ac_badge == "Index / ETF" else "#f59e0b"))
            st.markdown(f"""
            <div style="background: rgba(15, 23, 42, 0.7); border-left: 4px solid {badge_bg}; padding: 8px 16px; border-radius: 6px; margin: 8px 0 14px 0; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                <div>
                    <span style="font-weight: 800; color: #fff; font-size: 1.05em;">{selected_item['name']}</span>
                    <span style="color: #94a3b8; font-size: 0.88em; margin-left: 8px;">({selected_item['symbol']})</span>
                    <span style="background: {badge_bg}22; color: {badge_bg}; border: 1px solid {badge_bg}55; font-weight: 700; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; margin-left: 8px;">{ac_badge}</span>
                </div>
                <div>
                    <span style="color: #94a3b8; font-size: 0.85em;">Category: <b>{selected_item['sector']}</b> &nbsp;•&nbsp; </span>
                    <span style="color: #fef08a; font-weight: 800; font-size: 1.05em;">Live Price/NAV: ₹{selected_item['current_price']:,.2f}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

            col_q, col_bp, col_out, col_btn = st.columns([1.5, 1.5, 1.8, 1.2])
            with col_q:
                def_qty = 50.0 if ac_badge == "Mutual Fund" else 10.0
                qty_input = st.number_input(
                    "Quantity / Units:",
                    min_value=0.01,
                    value=def_qty,
                    step=1.0 if ac_badge != "Mutual Fund" else 5.0,
                    key="add_qty_input"
                )
            with col_bp:
                def_p = float(selected_item['current_price']) if selected_item['current_price'] > 0 else 100.0
                price_input = st.number_input(
                    "Avg Buy Price / NAV (₹):",
                    min_value=0.01,
                    value=def_p,
                    step=1.0,
                    key="add_price_input"
                )
            with col_out:
                est_outlay = qty_input * price_input
                st.metric("Estimated Outlay", f"₹{est_outlay:,.2f}")
            with col_btn:
                st.write("")
                st.write("")
                if st.button("➕ Add Asset", type="primary", use_container_width=True, key="btn_add_asset"):
                    existing = False
                    for ex in st.session_state["interactive_portfolio_holdings"]:
                        if ex["symbol"] == selected_item["symbol"]:
                            tot_q = ex["shares"] + qty_input
                            tot_c = (ex["shares"] * ex["buy_price"]) + (qty_input * price_input)
                            ex["shares"] = tot_q
                            ex["buy_price"] = round(tot_c / tot_q, 2)
                            existing = True
                            break
                    if not existing:
                        st.session_state["interactive_portfolio_holdings"].append({
                            "symbol": selected_item["symbol"],
                            "name": selected_item["name"],
                            "asset_class": selected_item["asset_class"],
                            "sector": selected_item["sector"],
                            "shares": qty_input,
                            "buy_price": price_input
                        })
                    st.success(f"Added {selected_item['symbol']} ({qty_input:,.1f} units @ ₹{price_input:,.2f})!")
                    st.rerun()

        # Display Current Added Holdings Table
        st.markdown("---")
        h_col1, h_col2 = st.columns([3, 1])
        with h_col1:
            st.markdown(f"##### 📋 Active Portfolio Holdings ({len(st.session_state['interactive_portfolio_holdings'])} Assets Added)")
        with h_col2:
            if st.button("🗑️ Clear All Holdings", key="btn_clear_port", use_container_width=True):
                st.session_state["interactive_portfolio_holdings"] = []
                st.rerun()

        if st.session_state["interactive_portfolio_holdings"]:
            df_cur = pd.DataFrame(st.session_state["interactive_portfolio_holdings"])
            df_cur["Total Cost (₹)"] = df_cur["shares"] * df_cur["buy_price"]

            st.dataframe(
                df_cur[["asset_class", "symbol", "name", "sector", "shares", "buy_price", "Total Cost (₹)"]].rename(columns={
                    "asset_class": "Asset Class",
                    "symbol": "Symbol / Code",
                    "name": "Instrument Name",
                    "sector": "Category / Sector",
                    "shares": "Shares / Units",
                    "buy_price": "Buy Price / NAV (₹)"
                }).style.format({
                    "Shares / Units": "{:,.2f}",
                    "Buy Price / NAV (₹)": "₹{:,.2f}",
                    "Total Cost (₹)": "₹{:,.2f}"
                }),
                use_container_width=True,
                hide_index=True
            )

            # Quick removal selector
            with st.expander("🗑️ Remove an Individual Asset from Holdings", expanded=False):
                holding_opts = {f"{h['symbol']} • {h['name']} ({h['shares']} units)": i for i, h in enumerate(st.session_state["interactive_portfolio_holdings"])}
                rem_sel = st.selectbox("Select asset to remove:", list(holding_opts.keys()), key="sel_rem_holding")
                if st.button("❌ Remove Selected Asset", type="secondary"):
                    idx_to_rem = holding_opts[rem_sel]
                    st.session_state["interactive_portfolio_holdings"].pop(idx_to_rem)
                    st.rerun()

            parsed_holdings = st.session_state["interactive_portfolio_holdings"]
        else:
            st.info("No holdings added yet. Search and add assets above or load a sample template below!")
            col_s1, col_s2, col_s3 = st.columns(3)
            with col_s1:
                if st.button("💡 Load Multi-Asset Sample (Stocks + MFs + Gold)", use_container_width=True):
                    st.session_state["interactive_portfolio_holdings"] = [
                        {"symbol": "RELIANCE", "name": "Reliance Industries", "shares": 30.0, "buy_price": 2850.0, "asset_class": "Stock", "sector": "Energy"},
                        {"symbol": "TCS", "name": "Tata Consultancy Services", "shares": 20.0, "buy_price": 3900.0, "asset_class": "Stock", "sector": "Information Technology"},
                        {"symbol": "118955", "name": "HDFC Flexi Cap Fund - Direct Plan", "shares": 100.0, "buy_price": 280.0, "asset_class": "Mutual Fund", "sector": "MF: Equity"},
                        {"symbol": "GOLDBEES.NS", "name": "Nippon India ETF Gold BeES", "shares": 50.0, "buy_price": 120.0, "asset_class": "Index / ETF", "sector": "Precious Metals"},
                    ]
                    st.rerun()
            with col_s2:
                if st.button("💡 Load All-Equity Bluechip Sample", use_container_width=True):
                    st.session_state["interactive_portfolio_holdings"] = [
                        {"symbol": "RELIANCE", "name": "Reliance Industries", "shares": 40.0, "buy_price": 2800.0, "asset_class": "Stock", "sector": "Energy"},
                        {"symbol": "TCS", "name": "Tata Consultancy Services", "shares": 25.0, "buy_price": 3850.0, "asset_class": "Stock", "sector": "Information Technology"},
                        {"symbol": "HDFCBANK", "name": "HDFC Bank", "shares": 60.0, "buy_price": 1600.0, "asset_class": "Stock", "sector": "Banking"},
                        {"symbol": "ICICIBANK", "name": "ICICI Bank", "shares": 80.0, "buy_price": 1150.0, "asset_class": "Stock", "sector": "Banking"},
                    ]
                    st.rerun()
            with col_s3:
                if st.button("💡 Load Mutual Fund Core Sample", use_container_width=True):
                    st.session_state["interactive_portfolio_holdings"] = [
                        {"symbol": "118955", "name": "HDFC Flexi Cap Fund", "shares": 200.0, "buy_price": 285.0, "asset_class": "Mutual Fund", "sector": "MF: Equity"},
                        {"symbol": "118959", "name": "HDFC Small Cap Fund", "shares": 1000.0, "buy_price": 9.5, "asset_class": "Mutual Fund", "sector": "MF: Equity"},
                        {"symbol": "118968", "name": "HDFC Balanced Advantage Fund", "shares": 300.0, "buy_price": 90.0, "asset_class": "Mutual Fund", "sector": "MF: Hybrid"},
                    ]
                    st.rerun()

    elif in_method == "📝 Quick Paste Text":
        col_txt, col_smpl = st.columns([3, 1])
        with col_txt:
            default_txt = st.session_state.get("user_pasted_portfolio_text", "RELIANCE, 30, 2850\nTCS, 20, 3900\n118955, 100, 280\nGOLDBEES.NS, 50, 120\nINFY, 60, 1550\nHDFCBANK, 50, 1620")
            txt_in = st.text_area(
                "Paste Holdings (Format: SYMBOL_OR_SCHEME_CODE, SHARES_OR_UNITS, BUY_PRICE):",
                value=default_txt,
                height=160,
                key="txt_portfolio_input"
            )
        with col_smpl:
            st.markdown("##### 💡 Quick Templates")
            if st.button("Multi-Asset Sample (Stock+MF+Gold)", use_container_width=True):
                st.session_state["user_pasted_portfolio_text"] = "RELIANCE, 30, 2850\nTCS, 20, 3900\n118955, 100, 280\nGOLDBEES.NS, 50, 120\nINFY, 60, 1550"
                st.rerun()
            if st.button("Load Bluechip Sample", use_container_width=True):
                st.session_state["user_pasted_portfolio_text"] = "RELIANCE, 40, 2800\nTCS, 25, 3850\nHDFCBANK, 60, 1600\nICICIBANK, 80, 1150\nBHARTIARTL, 50, 1420\nLT, 20, 3550"
                st.rerun()
            if st.button("Load Growth & Tech Sample", use_container_width=True):
                st.session_state["user_pasted_portfolio_text"] = "INFY, 80, 1520\nKPITTECH, 50, 1600\nTATAMOTORS, 100, 880\nDIXON, 15, 11500\nHAL, 20, 4400\nTRENT, 25, 6200"
                st.rerun()

        if txt_in.strip():
            parsed_holdings = parse_portfolio_text(txt_in)

    elif in_method == "📂 Upload Broker CSV":
        st.info("Supports CSV exports from Zerodha Kite, Groww, AngelOne, Upstox, ICICI Direct, or generic CSV with Symbol/Scheme and Quantity columns.")
        up_file = st.file_uploader("Upload Broker Holding CSV:", type=["csv"], key="csv_port_uploader")
        if up_file:
            parsed_holdings = parse_portfolio_csv(up_file.getvalue())
            if parsed_holdings:
                st.success(f"Parsed {len(parsed_holdings)} holdings from CSV file!")
            else:
                st.error("Could not find recognizable Symbol and Quantity columns in the uploaded CSV.")

    else: # Interactive Table Editor
        sample_df = pd.DataFrame([
            {"Symbol / Code": "RELIANCE", "Asset Class": "Stock", "Shares": 30.0, "Buy Price": 2850.0},
            {"Symbol / Code": "TCS", "Asset Class": "Stock", "Shares": 20.0, "Buy Price": 3900.0},
            {"Symbol / Code": "118955", "Asset Class": "Mutual Fund", "Shares": 100.0, "Buy Price": 280.0},
            {"Symbol / Code": "GOLDBEES.NS", "Asset Class": "Index / ETF", "Shares": 50.0, "Buy Price": 120.0},
            {"Symbol / Code": "HDFCBANK", "Asset Class": "Stock", "Shares": 50.0, "Buy Price": 1620.0},
        ])
        ed_df = st.data_editor(sample_df, num_rows="dynamic", use_container_width=True, key="grid_port_editor")
        for _, r in ed_df.iterrows():
            s = str(r.get("Symbol / Code", "")).strip()
            ac = str(r.get("Asset Class", "Stock")).strip()
            q = float(r.get("Shares", 0) or 0)
            p = float(r.get("Buy Price", 0.0) or 0.0)
            if s and q > 0:
                parsed_holdings.append({"symbol": s, "shares": q, "buy_price": p, "asset_class": ac})

    # Run Analysis
    if parsed_holdings:
        session_aud = get_session(engine)
        p_res = analyze_custom_portfolio(parsed_holdings, session_aud)
        session_aud.close()

        sum_m = p_res["summary"]
        h_list = p_res["holdings"]

        st.markdown("---")

        # ── 1. Portfolio Health Scorecard Ribbon ──────────────────────────────
        pk1, pk2, pk3, pk4, pk5 = st.columns(5)
        pk1.metric("💰 Total Invested", f"₹{sum_m['total_invested']:,.2f}", f"{sum_m['total_holdings']} Holdings")
        pk2.metric("📦 Current Valuation", f"₹{sum_m['total_current']:,.2f}", f"Health: {sum_m['health_rating']}")
        
        pnl_val = sum_m['total_pnl_inr']
        pk3.metric("📈 Unrealized P&L", f"₹{pnl_val:+,.2f}", f"{sum_m['total_pnl_pct']:+.2f}% Overall")
        
        day_val = sum_m['today_pnl_inr']
        pk4.metric("⚡ Today's P&L", f"₹{day_val:+,.2f}", f"{sum_m['today_pnl_pct']:+.2f}% 1D")
        pk5.metric("🎯 Portfolio Score", f"{sum_m['weighted_avg_score']:.1f}/100", f"HHI: {sum_m['hhi_score']:.0f}")

        # ── 2. Concentration & Risk Alerts ────────────────────────────────────
        if sum_m["overweight_alerts"] or sum_m["sector_alerts"]:
            st.markdown("#### 🚨 Risk & Concentration Alerts")
            for alert in sum_m["overweight_alerts"]:
                st.warning(alert)
            for alert in sum_m["sector_alerts"]:
                st.warning(alert)

        # ── 3. Actionable Suggestions Summary Ribbon ──────────────────────────
        st.markdown("---")
        st.markdown("##### 💡 Actionable Portfolio Health Advisory")
        adv = sum_m["advice_counts"]
        ak1, ak2, ak3, ak4, ak5 = st.columns(5)
        ak1.metric("🚀 Accumulate / Add", f"{adv['ACCUMULATE']} stocks", "High Momentum & Conviction")
        ak2.metric("🟢 Hold & Compound", f"{adv['HOLD']} stocks", "Stable Core Compounding")
        ak3.metric("💰 Trim / Book Profit", f"{adv['TRIM']} stocks", "Parabolic / Overweight (>18%)")
        ak4.metric("⚠️ Rebalance Needed", f"{adv['REBALANCE']} stocks", "Sluggish Intermediate Trend")
        ak5.metric("🛑 Exit / Cut Loss", f"{adv['EXIT']} stocks", "Broken 200 EMA / Breached SL")

        # ── 4. Charts: Multi-Asset, Sector & Market Cap Exposure ─────────────
        col_ac_ch, col_sec_ch, col_tier_ch = st.columns(3)
        with col_ac_ch:
            df_ac = pd.DataFrame(sum_m.get("asset_class_breakdown", []))
            if not df_ac.empty:
                fig_ac = px.pie(
                    df_ac,
                    names="asset_class",
                    values="value",
                    hole=0.45,
                    title="🌐 Multi-Asset Allocation Tilt",
                    color_discrete_sequence=["#38bdf8", "#10b981", "#a855f7", "#f59e0b"]
                )
                fig_ac.update_layout(height=280, template="plotly_dark", margin=dict(l=10, r=10, t=35, b=10))
                st.plotly_chart(fig_ac, use_container_width=True)

        with col_sec_ch:
            df_sec = pd.DataFrame(sum_m["sector_breakdown"])
            if not df_sec.empty:
                fig_sec = px.pie(
                    df_sec,
                    names="sector",
                    values="value",
                    hole=0.45,
                    title="🏭 Sector Allocation & Exposure",
                    color_discrete_sequence=px.colors.qualitative.Plotly
                )
                fig_sec.update_layout(height=280, template="plotly_dark", margin=dict(l=10, r=10, t=35, b=10))
                st.plotly_chart(fig_sec, use_container_width=True)

        with col_tier_ch:
            tier_dict = sum_m["tier_breakdown"]
            fig_tier = px.pie(
                names=list(tier_dict.keys()),
                values=list(tier_dict.values()),
                hole=0.45,
                title="🏢 Market Cap / Tier (% Value)",
                color_discrete_sequence=["#38bdf8", "#f59e0b", "#10b981", "#ec4899", "#8b5cf6"]
            )
            fig_tier.update_layout(height=280, template="plotly_dark", margin=dict(l=10, r=10, t=35, b=10))
            st.plotly_chart(fig_tier, use_container_width=True)

        # ── 5. Detailed Holdings Advisory Table ───────────────────────────────
        st.markdown("---")
        st.markdown("##### 📋 Multi-Asset Holdings Health, Diagnostics & Actionable Advice")

        df_holdings = pd.DataFrame(h_list)
        st.dataframe(
            df_holdings[[
                "asset_class", "symbol", "name", "sector", "shares", "buy_price", "cmp", "weight_pct",
                "unrealized_pnl_inr", "unrealized_pnl_pct", "day_ret_pct", "composite_score",
                "signal", "momentum_6m_pct", "advice_badge", "advice_reason"
            ]].rename(columns={
                "asset_class": "Asset Class",
                "symbol": "Symbol / Code",
                "name": "Instrument",
                "sector": "Category / Sector",
                "shares": "Shares / Units",
                "buy_price": "Buy Price / NAV (₹)",
                "cmp": "CMP / NAV (₹)",
                "weight_pct": "Weight %",
                "unrealized_pnl_inr": "P&L (₹)",
                "unrealized_pnl_pct": "P&L %",
                "day_ret_pct": "1D Return %",
                "composite_score": "Score",
                "signal": "Signal",
                "momentum_6m_pct": "6M Mom %",
                "advice_badge": "Actionable Advice",
                "advice_reason": "Quantitative Diagnostic Rationale"
            }).style.format({
                "Shares / Units": "{:,.2f}",
                "Buy Price / NAV (₹)": "₹{:,.2f}",
                "CMP / NAV (₹)": "₹{:,.2f}",
                "Weight %": "{:.2f}%",
                "P&L (₹)": "₹{:,.2f}",
                "P&L %": "{:+.2f}%",
                "1D Return %": "{:+.2f}%",
                "Score": "{:.1f}",
                "6M Mom %": "{:+.1f}%"
            }),
            use_container_width=True,
            height=420,
            hide_index=True
        )

        csv_port = df_holdings.to_csv(index=False).encode('utf-8')
        st.download_button(
            "📥 Download Full Portfolio Diagnostic Audit (CSV)",
            data=csv_port,
            file_name=f"portfolio_diagnostic_{date.today().strftime('%Y_%m_%d')}.csv",
            mime="text/csv"
        )
    else:
        st.info("Enter or paste your holdings above to unlock full institutional portfolio analytics.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2: INSTITUTIONAL MODEL PORTFOLIOS (10/20/50 ASSETS)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_model_port:
    st.subheader("🏛️ Institutional Multi-Asset Model Portfolios")
    st.caption("Algorithmically constructs and rebalances 10, 20, 50+ asset diversified portfolios across Equities, Indexes, and Commodities tailored to your risk mandate and time horizon.")

    # ── Sidebar / Top Controls ───────────────────────────────────────────────────
    ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4 = st.columns(4)

    with ctrl_col1:
        basket_choice = st.selectbox("Asset Basket Size", ["10 Assets (Concentrated Core)", "20 Assets (Institutional Optimal)", "50 Assets (Broad All-Weather)", "Custom N Assets"], index=1, key="mod_basket_sz")
        if basket_choice == "10 Assets (Concentrated Core)":
            target_n = 10
        elif basket_choice == "20 Assets (Institutional Optimal)":
            target_n = 20
        elif basket_choice == "50 Assets (Broad All-Weather)":
            target_n = 50
        else:
            target_n = st.slider("Select Custom Asset Count", 5, 80, 25, key="mod_custom_n")

    with ctrl_col2:
        risk_choice = st.selectbox(
            "Risk Profile Mandate",
            ["🛡️ Safe Fortress (Capital Preservation)", "⚖️ Balanced All-Weather (Sharpe Optimal)", "⚡ High Growth (Maximum Capital Appreciation)"],
            index=1,
            key="mod_risk_mandate"
        )
        risk_code = "SAFE" if "Safe" in risk_choice else ("RISKY" if "High Growth" in risk_choice else "BALANCED")

    with ctrl_col3:
        horizon_choice = st.selectbox(
            "Investment Time Horizon",
            ["⚡ Daily / Swing (1–30 Days)", "🌱 1 Year (Medium Term)", "🌳 3 Years (Long-Term Compounding)", "🏛️ 5 Years (Secular Wealth Fortress)"],
            index=2,
            key="mod_horizon_sel"
        )
        horizon_code = "DAILY" if "Daily" in horizon_choice else ("1_YEAR" if "1 Year" in horizon_choice else ("3_YEARS" if "3 Years" in horizon_choice else "5_YEARS"))

    with ctrl_col4:
        total_capital = st.number_input("Total Portfolio Capital (₹)", min_value=50000.0, max_value=500000000.0, value=1000000.0, step=100000.0, key="mod_tot_cap")

    # Generate Portfolio
    session_adv = get_session(engine)
    portfolio = generate_institutional_portfolio(
        session=session_adv,
        n_assets=target_n,
        risk_profile=risk_code,
        horizon=horizon_code,
        total_capital_inr=total_capital
    )
    session_adv.close()

    # ── Summary Scorecard ────────────────────────────────────────────────────────
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("Total Assets Selected", portfolio["n_assets"], f"Risk: {risk_code}")
    with m2:
        st.metric("Expected Annual CAGR", f"{portfolio['expected_cagr_pct']:+.1f}%/yr", "Compounding Target")
    with m3:
        st.metric("Projected 1-Yr Capital", f"₹{portfolio['projected_1y_capital']:,.0f}", f"+₹{portfolio['projected_1y_capital'] - total_capital:,.0f}")
    with m4:
        st.metric("Projected 3-Yr Capital", f"₹{portfolio['projected_3y_capital']:,.0f}", f"+₹{portfolio['projected_3y_capital'] - total_capital:,.0f}")
    with m5:
        st.metric("Projected 5-Yr Capital", f"₹{portfolio['projected_5y_capital']:,.0f}", f"+₹{portfolio['projected_5y_capital'] - total_capital:,.0f}")

    st.markdown(f"**Institutional Mandate Archetype:** `{portfolio['mandate_desc']}`")

    st.markdown("---")

# ── Asset Class & Sector Allocation Donut Charts ─────────────────────────────
ch_col1, ch_col2 = st.columns(2)

with ch_col1:
    st.markdown("##### 🥧 Multi-Asset Class Distribution")
    df_ac = pd.DataFrame(list(portfolio["asset_class_summary"].items()), columns=["Asset Class", "Allocation %"])
    fig_ac = px.pie(df_ac, names="Asset Class", values="Allocation %", hole=0.45, color_discrete_sequence=["#38bdf8", "#00c875", "#f0a500"])
    fig_ac.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#e0e0e0"))
    st.plotly_chart(fig_ac, use_container_width=True)

with ch_col2:
    st.markdown("##### 🌐 Equity Sector & Commodity Diversification (≤25% Cap)")
    df_sec = pd.DataFrame(list(portfolio["sector_summary"].items()), columns=["Sector / Vertical", "Allocation %"])
    fig_sec = px.pie(df_sec, names="Sector / Vertical", values="Allocation %", hole=0.45, color_discrete_sequence=px.colors.sequential.Tealgrn)
    fig_sec.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#e0e0e0"))
    st.plotly_chart(fig_sec, use_container_width=True)

st.markdown("---")

# ── Projected Wealth Compounding Growth Curve ────────────────────────────────
st.markdown("##### 📈 5-Year Projected Capital Compounding Trajectory (₹)")
years = list(range(6))
growth_curve = [round(total_capital * ((1.0 + portfolio['expected_cagr_pct'] / 100.0) ** y), 2) for y in years]
df_growth = pd.DataFrame({"Year": [f"Year {y}" if y > 0 else "Today" for y in years], "Portfolio Capital (₹)": growth_curve})

fig_growth = go.Figure()
fig_growth.add_trace(go.Scatter(x=df_growth["Year"], y=df_growth["Portfolio Capital (₹)"], mode="lines+markers+text", text=[f"₹{v:,.0f}" for v in growth_curve], textposition="top center", line=dict(color="#00c875", width=3), name="Compounded Value"))
fig_growth.update_layout(height=300, margin=dict(l=20, r=20, t=30, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#e0e0e0"), yaxis_title="Portfolio Capital (₹)")
st.plotly_chart(fig_growth, use_container_width=True)

st.markdown("---")

# ── Action Buttons (Deploy & Export) ──────────────────────────────────────────
act_col1, act_col2, act_col3 = st.columns([1.5, 1.5, 2])

with act_col1:
    if st.button("🚀 Deploy to Live Paper Trading Ledger", type="primary", use_container_width=True):
        session_exec = get_session(engine)
        deploy_count = 0
        for item in portfolio["assets"]:
            if item["asset_class"] == "Equity" and item["shares_to_buy"] > 0:
                execute_paper_buy(
                    session=session_exec,
                    symbol=item["symbol"],
                    shares=item["shares_to_buy"],
                    buy_price=item["current_price"],
                    stop_loss=item["stop_loss"],
                    target_1=item["target_price_1"],
                    target_2=item["target_price_1"] * 1.04,
                    target_3=item["target_price_1"] * 1.10
                )
                deploy_count += 1
        session_exec.close()
        st.success(f"🎉 Successfully deployed {deploy_count} positions to your Live Paper Trading Ledger (Page 8)!")

with act_col2:
    # Generate HTML Mandate
    mandate_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Institutional Portfolio Mandate - {portfolio['n_assets']} Assets</title>
        <style>
            body {{ font-family: Arial, sans-serif; background: #0a0e14; color: #f0f4f8; padding: 30px; }}
            .header {{ border-bottom: 2px solid #00c875; padding-bottom: 15px; margin-bottom: 20px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ border: 1px solid #1e293b; padding: 10px; text-align: left; }}
            th {{ background: #111a24; color: #38bdf8; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>🏛️ Institutional Portfolio Advisory Mandate</h2>
            <p><b>Risk Profile:</b> {risk_code} | <b>Horizon:</b> {horizon_choice} | <b>Total Capital:</b> ₹{total_capital:,.2f} | <b>Expected CAGR:</b> {portfolio['expected_cagr_pct']:+.1f}%</p>
        </div>
        <table>
            <tr><th>Symbol</th><th>Asset Class</th><th>Sector</th><th>Weight %</th><th>Allocated Capital (₹)</th><th>Price (₹)</th><th>Target (₹)</th><th>Stop Loss (₹)</th></tr>
            {''.join([f"<tr><td><b>{x['symbol']}</b></td><td>{x['asset_class']}</td><td>{x['sector']}</td><td>{x['weight_pct']:.2f}%</td><td>₹{x['allocated_capital_inr']:,.2f}</td><td>₹{x['current_price']:,.2f}</td><td>₹{x['target_price_1']:,.2f}</td><td>₹{x['stop_loss']:,.2f}</td></tr>" for x in portfolio['assets']])}
        </table>
    </body>
    </html>
    """
    st.download_button(
        "📥 Export Portfolio Mandate (HTML/PDF)",
        data=mandate_html,
        file_name=f"Institutional_Portfolio_Mandate_{portfolio['n_assets']}_Assets.html",
        mime="text/html",
        use_container_width=True
    )

with act_col3:
    if st.button("📌 Lock as Tracked Active Mandate", use_container_width=True):
        from core.recommendation_tracker import save_active_recommendation_mandate
        session_m = get_session(engine)
        mid = save_active_recommendation_mandate(
            session_m,
            name=f"Institutional {portfolio['n_assets']} Assets ({risk_code})",
            strategy=f"INSTITUTIONAL_{risk_code}",
            assets=portfolio["assets"],
            source="Portfolio Advisor",
            monthly_outlay=total_capital,
            notes=f"Institutional allocation generated for {horizon_choice}"
        )
        session_m.close()
        st.success(f"✅ Mandate #{mid} saved! You can follow live trailing stops and daily shift alerts in Page 16.")

# ── Detailed Asset Allocation Table ──────────────────────────────────────────
st.subheader(f"📋 Complete Asset Allocation Matrix ({portfolio['n_assets']} Assets)")

df_assets = pd.DataFrame(portfolio["assets"])
st.dataframe(
    df_assets[[
        "symbol", "name", "asset_class", "sector", "weight_pct", "allocated_capital_inr", "shares_to_buy", "current_price", "target_price_1", "stop_loss", "expected_1y_ret_pct", "risk_level"
    ]].rename(columns={
        "symbol": "Symbol",
        "name": "Asset Name",
        "asset_class": "Asset Class",
        "sector": "Sector / Theme",
        "weight_pct": "Target Weight %",
        "allocated_capital_inr": "Capital (₹)",
        "shares_to_buy": "Units / Shares",
        "current_price": "Price (₹)",
        "target_price_1": "Target (₹)",
        "stop_loss": "Stop Loss (₹)",
        "expected_1y_ret_pct": "Expected Return %",
        "risk_level": "Risk Rating"
    }).style.format({
        "Target Weight %": "{:.2f}%",
        "Capital (₹)": "₹{:,.2f}",
        "Units / Shares": "{:,}",
        "Price (₹)": "₹{:,.2f}",
        "Target (₹)": "₹{:,.2f}",
        "Stop Loss (₹)": "₹{:,.2f}",
        "Expected Return %": "{:+.1f}%"
    }),
    use_container_width=True,
    hide_index=True
)