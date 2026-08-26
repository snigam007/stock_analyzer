"""
Page 6: Investment Strategies
Stock-level, sector-level, and portfolio strategies.
Includes Safe, Balanced, and Aggressive portfolio recommendations.
"""
import sys
from pathlib import Path
import streamlit as st
import pandas as pd

# Universal Root Directory Finder
_curr = Path(__file__).resolve()
while _curr != _curr.parent:
    if (_curr / "core").exists() and (_curr / "db").exists():
        break
    _curr = _curr.parent
BASE_DIR = _curr
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
st.set_page_config(page_title="Investment Strategies", page_icon="💼", layout="wide")

from db.database import get_global_engine, get_session
from sqlalchemy import text
from core.strategies import generate_portfolio_strategies

engine = get_global_engine()

st.title("💼 Investment Strategies")
st.caption("Actionable strategies for stocks, sectors, and portfolios")

tabs = st.tabs(["📊 Stock Strategies", "🏭 Sector Strategies", "🗂️ Portfolio Strategies"])

action_icons = {
    "BUY": "🟢", "SELL": "🔴", "HOLD": "🟡", "ACCUMULATE": "💚",
    "AVOID": "⛔", "WATCH": "🟡"
}
risk_colors = {"SAFE": "#1a4d2e", "MODERATE": "#3d3200", "RISKY": "#4d1a1a"}

@st.cache_data(ttl=30)
def get_stock_strategies(risk_filter="ALL", action_filter="ALL", limit=20):
    session = get_session(engine)
    query = """
        SELECT st.target_name as symbol, s.name, s.sector,
               st.strategy_name, st.strategy_type, st.risk_level, st.time_horizon,
               st.description, st.action, st.entry_price, st.target_price,
               st.stop_loss, st.expected_return_pct, st.rationale, st.risks
        FROM strategies st
        JOIN stocks s ON st.target_name = s.symbol
        WHERE st.target_type = 'stock'
        AND st.date = (SELECT MAX(date) FROM strategies WHERE target_type='stock')
    """
    params = {}
    if risk_filter != "ALL":
        query += " AND st.risk_level = :risk"
        params["risk"] = risk_filter
    if action_filter != "ALL":
        query += " AND st.action = :action"
        params["action"] = action_filter
    query += f" ORDER BY st.expected_return_pct DESC NULLS LAST LIMIT {limit}"
    result = session.execute(text(query), params).fetchall()
    session.close()
    return result


@st.cache_data(ttl=30)
def get_sector_strategies():
    session = get_session(engine)
    result = session.execute(text("""
        SELECT target_name, strategy_name, strategy_type, risk_level, time_horizon,
               description, action, rationale, risks
        FROM strategies
        WHERE target_type = 'sector'
        AND date = (SELECT MAX(date) FROM strategies WHERE target_type='sector')
        ORDER BY action DESC, target_name
    """)).fetchall()
    session.close()
    return result


# ── Tab 1: Stock Strategies ───────────────────────────────────────────────────
with tabs[0]:
    col1, col2, col3 = st.columns(3)
    risk_filter = col1.selectbox("Risk Level", ["ALL", "SAFE", "MODERATE", "RISKY"])
    action_filter = col2.selectbox("Action", ["ALL", "BUY", "ACCUMULATE", "HOLD", "SELL", "AVOID"])
    limit = col3.slider("Show N Stocks", 5, 50, 20)

    strategies = get_stock_strategies(risk_filter, action_filter, limit)

    if not strategies:
        st.info("No strategy data. Run `python initialize.py` first.")
    else:
        for row in strategies:
            (symbol, name, sector, strat_name, strat_type, risk, horizon,
             desc, action, entry, target, sl, exp_ret, rationale, risks) = row

            action_icon = action_icons.get(action, "🟡")
            risk_color = risk_colors.get(risk, "#333")

            with st.expander(
                f"{action_icon} **{symbol}** — {name[:35]} | "
                f"*{strat_name}* | {risk} | {horizon}-TERM",
                expanded=False,
            ):
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.markdown(f"**📂 Sector:** {sector}")
                    st.markdown(f"**🎯 Strategy:** {strat_name} ({strat_type})")
                    st.markdown(f"**⏰ Horizon:** {horizon}-TERM")
                    st.markdown(f"\n{desc}")
                    st.markdown(f"\n**💡 Rationale:** {rationale}")
                    st.markdown(f"\n**⚠️ Risks:** {risks}")

                with col2:
                    if entry:
                        st.metric("Entry Price", f"₹{entry:,.2f}")
                    if target:
                        exp_str = f"{exp_ret:+.1f}%" if exp_ret else None
                        st.metric("Target", f"₹{target:,.2f}", exp_str)
                    if sl:
                        st.metric("Stop Loss", f"₹{sl:,.2f}")
                    st.markdown(
                        f'<div style="background:{risk_color};padding:8px;border-radius:6px;text-align:center">'
                        f'<b>{risk}</b> RISK</div>',
                        unsafe_allow_html=True
                    )


# ── Tab 2: Sector Strategies ──────────────────────────────────────────────────
with tabs[1]:
    sector_strats = get_sector_strategies()
    if not sector_strats:
        st.info("No sector strategies available yet.")
    else:
        col1, col2, col3 = st.columns(3)
        buys = [s for s in sector_strats if s[6] == "BUY"]
        sells = [s for s in sector_strats if s[6] == "SELL"]
        watches = [s for s in sector_strats if s[6] not in ("BUY", "SELL")]

        with col1:
            st.markdown("### 🟢 Overweight Sectors")
            for s in buys:
                sector, strat_name, strat_type, risk, horizon, desc, action, rat, risks = s
                with st.expander(f"**{sector[:30]}** — {strat_name}"):
                    st.markdown(desc)
                    st.success(f"💡 {rat}")

        with col2:
            st.markdown("### 🔴 Underweight Sectors")
            for s in sells:
                sector, strat_name, strat_type, risk, horizon, desc, action, rat, risks = s
                with st.expander(f"**{sector[:30]}** — {strat_name}"):
                    st.markdown(desc)
                    st.error(f"⚠️ {rat}")

        with col3:
            st.markdown("### 🟡 Neutral Sectors")
            for s in watches:
                sector, strat_name, strat_type, risk, horizon, desc, action, rat, risks = s
                with st.expander(f"**{sector[:30]}** — {strat_name}"):
                    st.markdown(desc)
                    st.info(f"💡 {rat}")


# ── Tab 3: Portfolio Strategies ───────────────────────────────────────────────
with tabs[2]:
    st.subheader("🗂️ Portfolio Allocation Strategies")
    st.caption("Choose a strategy matching your risk tolerance and investment horizon")

    portfolios = generate_portfolio_strategies()

    for pf in portfolios:
        risk = pf["risk_level"]
        risk_color = risk_colors.get(risk, "#333")
        risk_icon = {"SAFE": "🛡️", "MODERATE": "⚖️", "RISKY": "⚡"}.get(risk, "⚖️")
        action_icon = action_icons.get(pf["action"], "🟡")

        with st.expander(
            f"{risk_icon} **{pf['name']}** | {risk} | {action_icon} {pf['action']}",
            expanded=(risk == "MODERATE"),
        ):
            st.markdown(f"#### {pf['name']}")
            st.markdown(pf["description"])
            st.markdown("")

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**✅ Rationale:**")
                st.success(pf["rationale"])
                st.markdown("**📂 Target Sectors:**")
                for sec in pf.get("sectors", []):
                    st.markdown(f"• {sec}")
            with col2:
                st.markdown("**⚠️ Risks:**")
                st.warning(pf["risks"])
                st.markdown(
                    f'<div style="background:{risk_color};padding:12px;border-radius:8px;text-align:center;margin-top:12px">'
                    f'<h3 style="color:white;margin:0">{risk_icon} {risk} PORTFOLIO</h3>'
                    f'<p style="color:#ccc;margin:4px 0 0 0">Action: {pf["action"]}</p>'
                    f'</div>',
                    unsafe_allow_html=True
                )

    st.markdown("---")
    st.markdown("### 📌 General Investment Guidelines")
    guidelines = [
        ("🔢 **Position Sizing**", "Never put more than 5% in a single stock. For risky plays, max 2-3%."),
        ("📊 **Diversification**", "Spread across at least 5-8 sectors to reduce sector-specific risk."),
        ("🛑 **Stop-Loss Discipline**", "Always set stop-loss before entering. Exit without hesitation if triggered."),
        ("⏰ **Time Horizon Match**", "Momentum plays = weeks. Value plays = months. Growth = years."),
        ("📰 **Catalyst Awareness**", "Watch for earnings results, RBI policy, global cues affecting positions."),
        ("🔄 **Rebalance Quarterly**", "Review and rebalance portfolio every 3 months based on fresh analysis."),
    ]
    col1, col2 = st.columns(2)
    for i, (title, text) in enumerate(guidelines):
        col = col1 if i % 2 == 0 else col2
        with col:
            with st.container():
                st.markdown(f"**{title}**")
                st.caption(text)
                st.markdown("")
