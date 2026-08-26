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

# Universal Root Directory Finder
_curr = Path(__file__).resolve()
while _curr != _curr.parent:
    if (_curr / "core").exists() and (_curr / "db").exists():
        break
    _curr = _curr.parent
BASE_DIR = _curr
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

st.set_page_config(page_title="Institutional Portfolio Advisor", page_icon="💼", layout="wide")

from db.database import get_global_engine, get_session
from sqlalchemy import text
from core.portfolio_advisor import generate_institutional_portfolio
from core.portfolio_optimizer import execute_paper_buy
from core.macro_regime import evaluate_macro_regime

engine = get_global_engine()


def format_price(p): return f"₹{p:,.2f}" if p else "—"


st.title("💼 Dynamic Institutional Multi-Asset Portfolio Advisor")
st.caption("Algorithmically constructs and rebalances 10, 20, 50+ asset diversified portfolios across Equities, Indexes, and Commodities tailored to your risk mandate and time horizon.")

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

# ── Sidebar / Top Controls ───────────────────────────────────────────────────
ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4 = st.columns(4)

with ctrl_col1:
    basket_choice = st.selectbox("Asset Basket Size", ["10 Assets (Concentrated Core)", "20 Assets (Institutional Optimal)", "50 Assets (Broad All-Weather)", "Custom N Assets"], index=1)
    if basket_choice == "10 Assets (Concentrated Core)":
        target_n = 10
    elif basket_choice == "20 Assets (Institutional Optimal)":
        target_n = 20
    elif basket_choice == "50 Assets (Broad All-Weather)":
        target_n = 50
    else:
        target_n = st.slider("Select Custom Asset Count", 5, 80, 25)

with ctrl_col2:
    risk_choice = st.selectbox(
        "Risk Profile Mandate",
        ["🛡️ Safe Fortress (Capital Preservation)", "⚖️ Balanced All-Weather (Sharpe Optimal)", "⚡ High Growth (Maximum Capital Appreciation)"],
        index=1
    )
    risk_code = "SAFE" if "Safe" in risk_choice else ("RISKY" if "High Growth" in risk_choice else "BALANCED")

with ctrl_col3:
    horizon_choice = st.selectbox(
        "Investment Time Horizon",
        ["⚡ Daily / Swing (1–30 Days)", "🌱 1 Year (Medium Term)", "🌳 3 Years (Long-Term Compounding)", "🏛️ 5 Years (Secular Wealth Fortress)"],
        index=2
    )
    horizon_code = "DAILY" if "Daily" in horizon_choice else ("1_YEAR" if "1 Year" in horizon_choice else ("3_YEARS" if "3 Years" in horizon_choice else "5_YEARS"))

with ctrl_col4:
    total_capital = st.number_input("Total Portfolio Capital (₹)", min_value=50000.0, max_value=500000000.0, value=1000000.0, step=100000.0)

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
    st.write("")

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