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
try:
    st.set_page_config(page_title="Investment Strategies", page_icon="💼", layout="wide")
except Exception:
    pass

from db.database import get_global_engine, get_session
from sqlalchemy import text
from core.strategies import generate_portfolio_strategies
from core.target_velocity import predict_time_to_target
from core.sector_clusters import get_sector_cluster, get_cluster_metadata

from core.apex_swing_engine import check_nifty_regime, scan_apex_swing_candidates, generate_apex_swing_execution_plan

engine = get_global_engine()

st.title("💼 Investment Strategies")
st.caption("Actionable strategies for stocks, sectors, portfolios, and systematic swing trading")

tabs = st.tabs([
    "🚀 Apex Swing Engine (Alpha Champion + Fortress)",
    "📊 Stock Strategies",
    "🏭 Sector Strategies",
    "🗂️ Portfolio Strategies"
])

action_icons = {
    "BUY": "🟢", "SELL": "🔴", "HOLD": "🟡", "ACCUMULATE": "💚",
    "AVOID": "⛔", "WATCH": "🟡"
}
risk_colors = {"SAFE": "#1a4d2e", "MODERATE": "#3d3200", "RISKY": "#4d1a1a"}

@st.cache_data(ttl=120)
def get_cached_swing_scan():
    return scan_apex_swing_candidates(limit=25)

@st.cache_data(ttl=30)
def get_stock_strategies(risk_filter="ALL", action_filter="ALL", limit=20):
    session = get_session(engine)
    query = """
        SELECT st.target_name as symbol, s.name, s.sector,
               st.strategy_name, st.strategy_type, st.risk_level, st.time_horizon,
               st.description, st.action,
               COALESCE(st.entry_price, sig.current_price, sig.buy_price) as entry_price,
               COALESCE(st.target_price, sig.target_price_1) as target_price,
               COALESCE(st.stop_loss, sig.stop_loss) as stop_loss,
               COALESCE(st.expected_return_pct, sig.target_1_upside_pct) as expected_return_pct,
               st.rationale, st.risks
        FROM strategies st
        JOIN stocks s ON st.target_name = s.symbol
        LEFT JOIN signals sig ON st.target_name = sig.symbol AND sig.date = (SELECT MAX(date) FROM signals)
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
    query += f" ORDER BY COALESCE(st.expected_return_pct, sig.target_1_upside_pct) DESC NULLS LAST LIMIT {limit}"
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


# ── Tab 0: Apex Swing Engine (SW_005479 + SW_000640) ──────────────────────────
with tabs[0]:
    st.subheader("🚀 Apex Systematic Swing Engine")
    st.caption("Empirically Champion Fusion Strategy: SW_005479 (Alpha Champion) + SW_000640 (Fortress Shield)")

    # 1. Strategy Summary Badges
    st.markdown("""
    <div style="background: linear-gradient(135deg, #0d1e30, #09131d); border: 1px solid #1e3a5f; padding: 14px 20px; border-radius: 8px; margin-bottom: 16px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
            <div>
                <span style="font-size: 1.15em; font-weight: bold; color: #38bdf8;">🏆 SW_005479 + SW_000640 Systematic Swing Champion</span>
                <div style="font-size: 0.88em; color: #94a3b8; margin-top: 4px;">
                    Multi-Lookback Momentum Screener • 3 Concentrated Slots (33.3% Capital) • 2.0x ATR Stop • +4% Pyramiding (+50% Size & BE Stop) • 3-Tier Exit (1.5x / 3.0x / 8.5x Runner)
                </div>
            </div>
            <div style="display: flex; gap: 8px;">
                <span style="background: rgba(16, 185, 129, 0.2); color: #34d399; font-weight: bold; padding: 4px 10px; border-radius: 6px; font-size: 0.85em;">1Y XIRR: +136.0%</span>
                <span style="background: rgba(56, 189, 248, 0.2); color: #38bdf8; font-weight: bold; padding: 4px 10px; border-radius: 6px; font-size: 0.85em;">Profit Factor: 2.51</span>
                <span style="background: rgba(245, 158, 11, 0.2); color: #fbbf24; font-weight: bold; padding: 4px 10px; border-radius: 6px; font-size: 0.85em;">Crash Return: +29.06%</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 2. Live Market Regime & Fortress Status
    scan_data = get_cached_swing_scan()
    regime = scan_data["regime"]
    candidates = scan_data["candidates"]

    if regime["is_bull"]:
        regime_banner_color = "#10b981"
        regime_bg = "rgba(16, 185, 129, 0.12)"
        regime_icon = "🟢"
        regime_badge = "BULL TRENDING — FULL 3-SLOT CONVICTION ACTIVE"
    else:
        regime_banner_color = "#f59e0b"
        regime_bg = "rgba(245, 158, 11, 0.12)"
        regime_icon = "🛡️"
        regime_badge = "BEAR MARKET FORTRESS ACTIVE — 1 SLOT MAX + CASH SWEEP"

    st.markdown(f"""
    <div style="background: {regime_bg}; border-left: 5px solid {regime_banner_color}; padding: 12px 18px; border-radius: 6px; margin-bottom: 16px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
            <span style="font-weight: bold; color: {regime_banner_color}; font-size: 1.05em;">{regime_icon} Market Regime: {regime_badge}</span>
            <span style="color: #cbd5e1; font-size: 0.9em;">NIFTY: <b>₹{regime['nifty_close']:,.2f}</b> | 50 EMA: <b>₹{regime['nifty_ema50']:,.2f}</b> | 21 EMA: <b>₹{regime['nifty_ema21']:,.2f}</b></span>
        </div>
        <div style="font-size: 0.88em; color: #94a3b8; margin-top: 6px;">
            {regime['explanation']}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 3. Interactive Execution Plan
    col_cap, col_refresh = st.columns([3, 1])
    with col_cap:
        swing_capital = st.number_input(
            "Account Capital for Swing Portfolio (₹)",
            min_value=25000,
            value=300000,
            step=25000,
            help="Total cash designated for the 3-Slot Swing Strategy. In Bull market: 33.3% allocated per slot. In Bear Fortress: max 1 slot, remaining swept to LiquidBees."
        )
    with col_refresh:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh Swing Screener", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    exec_plan = generate_apex_swing_execution_plan(portfolio_wallet=swing_capital, candidates=candidates)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Active Slots Deployed", f"{len(exec_plan['active_trades'])} / {exec_plan['allowed_slots']} Max")
    m2.metric("Equity Capital Deployed", f"₹{exec_plan['total_equity_deployed']:,.2f}")
    if exec_plan['liquidbees_sweep']['active']:
        m3.metric("🛡️ LiquidBees Cash Sweep", f"₹{exec_plan['liquidbees_sweep']['sweep_capital']:,.2f}", "+6.5% Yield")
    else:
        m3.metric("Liquid Reserves", f"₹{exec_plan['unallocated_cash']:,.2f}", "0% Sweep")
    m4.metric("Capital per Slot", f"₹{swing_capital / 3.0:,.2f}", "33.3% Target")

    st.markdown("### 📋 Live Whole-Share Execution Orders")
    if not exec_plan["active_trades"]:
        st.info("No candidates currently pass the strict Multi-Lookback + Trend Confirmation criteria. Remaining in 100% Cash / LiquidBees preservation mode.")
    else:
        for idx, trade in enumerate(exec_plan["active_trades"], 1):
            with st.container():
                st.markdown(f"""
                <div style="background: #111a26; border: 1px solid #1f2e42; border-radius: 8px; padding: 14px 18px; margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1f2e42; padding-bottom: 8px; margin-bottom: 10px;">
                        <div>
                            <span style="background: #0284c7; color: white; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 0.85em; margin-right: 8px;">SLOT {idx}</span>
                            <span style="font-size: 1.2em; font-weight: bold; color: #f8fafc;">{trade['symbol']}</span>
                            <span style="color: #94a3b8; font-size: 0.9em; margin-left: 8px;">({trade['name']} • {trade['sector']})</span>
                        </div>
                        <div>
                            <span style="font-size: 1.15em; font-weight: bold; color: #38bdf8;">BUY {trade['shares']} Shares</span>
                            <span style="color: #94a3b8; font-size: 0.9em;"> @ ₹{trade['current_price']:,.2f} = <b>₹{trade['allocated_capital']:,.2f}</b></span>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric(
                    "🛑 Dynamic Stop Loss",
                    f"₹{trade['stop_loss']:,.2f}",
                    f"{trade['stop_loss_pct']:.1f}% (-2.0x ATR)",
                    delta_color="inverse"
                )
                c2.metric(
                    "⚡ Pyramid Trigger (+50%)",
                    f"₹{trade['pyramid_trigger_price']:,.2f}",
                    "+4.0% Gain -> SL to BE"
                )
                c3.metric(
                    "🎯 Tier 1 (Trim 1/3rd)",
                    f"₹{trade['target_1']:,.2f}",
                    f"+{trade['target_1_pct']:.1f}% (+1.5x ATR)"
                )
                c4.metric(
                    "🎯 Tier 2 (Trim 1/3rd)",
                    f"₹{trade['target_2']:,.2f}",
                    f"+{trade['target_2_pct']:.1f}% (+3.0x ATR)"
                )
                c5.metric(
                    "🚀 Tier 3 Runner (1/3rd)",
                    f"₹{trade['target_3_runner']:,.2f}",
                    f"+{trade['target_3_pct']:.1f}% (+8.5x ATR)"
                )

    if exec_plan['liquidbees_sweep']['active']:
        st.markdown(f"""
        <div style="background: rgba(245, 158, 11, 0.1); border: 1px dashed #f59e0b; border-radius: 8px; padding: 12px 18px; margin-top: 10px; margin-bottom: 20px;">
            <span style="font-weight: bold; color: #f59e0b;">🛡️ Bear Fortress Cash Sweep Order:</span>
            <span style="color: #e2e8f0; margin-left: 8px;">Allocate remaining <b>₹{exec_plan['liquidbees_sweep']['sweep_capital']:,.2f}</b> into <b>LIQUIDBEES</b>. Accrues ~6.5% risk-free annualized yield while keeping capital 100% liquid for instant deployment when NIFTY reclaims its 21/50 EMAs.</span>
        </div>
        """, unsafe_allow_html=True)

    # 4. Strategy Architecture Blueprint
    with st.expander("📖 Systematic Strategy Architecture & Complete Rules Blueprint", expanded=False):
        b1, b2 = st.columns(2)
        with b1:
            st.markdown("""
            **1. Entry Screener & Multi-Lookback Momentum:**
            - **Weighting:** 15% 1-Month + 25% 3-Month + 40% 6-Month + 20% 12-Month Momentum.
            - **Trend Gate:** `Close >= 50 EMA >= 200 EMA` (must be in established structural stage-2 uptrend).
            - **Momentum Filter:** `1M > 0%`, `3M > 0%`, and `6M > 10.0%`.
            - **RSI Gate:** `45.0 <= RSI(14) <= 72.0` (eliminates dead stocks and overbought climaxes).

            **2. Conviction Concentration:**
            - **Slots:** Strictly 3 Slots (33.3% of wallet capital per position).
            - **Empirical Backtest Result:** 3 Slots concentrated conviction sharply outperformed 8-slot diversification (+24.0% vs +15.2% avg XIRR).
            """)
        with b2:
            st.markdown("""
            **3. Dynamic Risk & Exit Geometry:**
            - **Stop Loss:** Dynamic ATR 2.0x below entry price.
            - **Winner Pyramiding:** Add +50% position size when trade reaches +4.0% gain; immediately move stop to breakeven (`entry_price * 1.002`).
            - **Tier 1 (Base Gain):** Trim 1/3rd position at `+1.5x ATR`.
            - **Tier 2 (Core Profit):** Trim 1/3rd position at `+3.0x ATR` (trail stop to entry).
            - **Tier 3 (The Runner):** Let remaining 1/3rd ride with trailing Chandelier stop up to `+8.5x ATR`.

            **4. Bear Market Fortress Shield:**
            - If NIFTY closes below its 50 and 21 EMAs:
              - Restrict open positions to maximum 1 slot.
              - Sweep remaining unallocated cash to LiquidBees (~6.5% yield).
              - Converted a -14.4% market crash into +29.06% POSITIVE return.
            """)

    # 5. Full Candidates Screener Table
    st.markdown("### 🔍 All Passing Candidates from Screener")
    if candidates:
        cand_df = pd.DataFrame([{
            "Rank": i + 1,
            "Symbol": c["symbol"],
            "Company": c["name"],
            "Sector": c["sector"],
            "Price": f"₹{c['current_price']:,.2f}",
            "Score": c["composite_score"],
            "RSI": c["rsi_14"],
            "ATR": f"₹{c['atr_14']:.2f}",
            "1M %": f"{c['mom_1m']:+.1f}%",
            "3M %": f"{c['mom_3m']:+.1f}%",
            "6M %": f"{c['mom_6m']:+.1f}%",
            "Stop Loss": f"₹{c['stop_loss']:,.2f} ({c['stop_loss_pct']:.1f}%)",
            "Target 1": f"₹{c['target_1']:,.2f} (+{c['target_1_pct']:.1f}%)",
            "Target 2": f"₹{c['target_2']:,.2f} (+{c['target_2_pct']:.1f}%)",
            "Target 3": f"₹{c['target_3_runner']:,.2f} (+{c['target_3_pct']:.1f}%)",
            "R:R": f"{c['risk_reward_ratio']:.2f}x"
        } for i, c in enumerate(candidates)])
        st.dataframe(cand_df, use_container_width=True, hide_index=True)
    else:
        st.info("No stocks currently meet all multi-lookback momentum, trend, and RSI filters.")

    st.markdown("---")


# ── Tab 1: Stock Strategies ───────────────────────────────────────────────────
with tabs[1]:
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

            pred_ttt = predict_time_to_target(
                entry_price=entry or 0,
                target_1=target or 0,
                risk_level=risk,
                setup_type=strat_type
            )

            cluster_name = get_sector_cluster(sector)
            cluster_meta = get_cluster_metadata(cluster_name)

            ret_badge = f" | 📈 **{exp_ret:+.1f}%**" if (exp_ret is not None and not pd.isna(exp_ret)) else (" | ⚠️ No Price Data" if not entry else "")

            with st.expander(
                f"{action_icon} **{symbol}** — {name[:24]}{ret_badge} | "
                f"{cluster_meta['badge']} | *{strat_name}* | {risk} | ⏳ {pred_ttt['window_str']}",
                expanded=False,
            ):
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.markdown(f"**📂 Sector:** {sector} ({cluster_meta['badge']})")
                    st.markdown(f"**🎯 Strategy:** {strat_name} ({strat_type})")
                    st.markdown(f"**⏰ Horizon:** {horizon}-TERM • **Est. Velocity:** {pred_ttt['badge_html']}", unsafe_allow_html=True)
                    st.markdown(f"\n{desc}")
                    st.markdown(f"\n**💡 Rationale:** {rationale}")
                    st.markdown(f"\n**⚠️ Risks:** {risks}")

                with col2:
                    if entry:
                        st.metric("Entry Price", f"₹{entry:,.2f}")
                    if target:
                        exp_str = f"{exp_ret:+.1f}%" if exp_ret else None
                        st.metric("Target", f"₹{target:,.2f}", exp_str)
                    elif not entry:
                        st.caption("⚠️ Price targets awaiting next signal cycle")
                    st.metric("⏳ Est. Target Horizon", pred_ttt['window_str'], f"{pred_ttt['confidence_pct']}% Confidence")
                    if sl:
                        st.metric("Stop Loss", f"₹{sl:,.2f}")
                    st.markdown(
                        f'<div style="background:{risk_color};padding:8px;border-radius:6px;text-align:center">'
                        f'<b>{risk}</b> RISK</div>',
                        unsafe_allow_html=True
                    )


# ── Tab 2: Sector Strategies ──────────────────────────────────────────────────
with tabs[2]:
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
with tabs[3]:
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
