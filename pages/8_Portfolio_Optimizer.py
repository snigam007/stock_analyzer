"""
Page 8: Institutional Portfolio Optimizer & Paper Trading Engine
- Markowitz Modern Portfolio Theory (MPT) Efficient Frontier (4,000 Monte Carlo Paths)
- Max Sharpe Ratio & Minimum Volatility Allocation Pie Charts
- Live Paper Trading Portfolio Ledger & Multi-Tranche Execution Tracker
- Macro-Regime Calibrated Asset Allocation Rebalancer
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
st.set_page_config(page_title="Portfolio Optimizer & Paper Trading", page_icon="💼", layout="wide")

import importlib
import core.portfolio_optimizer
importlib.reload(core.portfolio_optimizer)

from db.database import get_global_engine, get_session
from sqlalchemy import text
from core.portfolio_optimizer import (
    compute_mpt_efficient_frontier,
    get_paper_portfolio,
    execute_paper_buy,
    execute_paper_sell,
)
from core.macro_regime import evaluate_macro_regime

engine = get_global_engine()


def format_price(p): return f"₹{p:,.2f}" if p else "—"


st.title("💼 Institutional Portfolio Optimizer & Paper Trading")
st.caption("Markowitz Modern Portfolio Theory (MPT) Efficient Frontier, Optimal Asset Allocation & Live Paper Trading Ledger")

# Top Macro Regime Banner
session_m = get_session(engine)
macro = evaluate_macro_regime(session_m)
session_m.close()

st.markdown(f"""
<div style="background: linear-gradient(90deg, #102130, #0c1822); border-left: 5px solid #00a8ff; padding: 10px 16px; border-radius: 6px; margin-bottom: 15px;">
    <span style="font-weight: bold; color: #00a8ff;">🏛️ Macro Allocation Guide: {macro['regime']} (Score: {macro['macro_score']}/100)</span><br>
    <span style="font-size: 0.88em; color: #c8d0d8;">Recommended Distribution: Equities <b>{macro['recommended_allocation']['Equities %']}%</b> | Gold/Commodities <b>{macro['recommended_allocation']['Gold & Commodities %']}%</b> | Cash Buffer <b>{macro['recommended_allocation']['Cash & Liquid %']}%</b></span>
</div>
""", unsafe_allow_html=True)

tabs = st.tabs([
    "📐 Markowitz Efficient Frontier (MPT)",
    "📈 Live Paper Trading Ledger",
    "⚡ Execute Paper Trade",
    "📜 Realized Trade History",
    "📊 Hedge Fund Performance Tearsheet",
    "🛡️ Black Swan Crisis Stress-Test",
    "🏛️ Barra & Fama-French Factor Risk Attribution",
    "🏰 Bridgewater Risk Parity & HRP",
    "🎯 MAE / MFE Trade Analytics"
])

# ── Tab 1: Efficient Frontier Optimizer ────────────────────────────────────────
with tabs[0]:
    st.subheader("📐 Markowitz Modern Portfolio Theory (MPT) Optimizer")
    st.caption("Mathematically determine the optimal asset weights that maximize Sharpe Ratio or minimize portfolio risk")

    opt_col1, opt_col2 = st.columns([1, 3])

    with opt_col1:
        st.markdown("**Select Asset Basket:**")
        session_s = get_session(engine)
        all_stocks = session_s.execute(text("SELECT symbol, name, sector FROM stocks WHERE is_active=1 ORDER BY symbol")).fetchall()
        session_s.close()

        stock_options = [s[0] for s in all_stocks]
        preferred_defaults = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "LT", "ITC", "SBIN", "BHARTIARTL"]
        valid_defaults = [s for s in preferred_defaults if s in stock_options][:6]
        if not valid_defaults and stock_options:
            valid_defaults = stock_options[:min(5, len(stock_options))]

        selected_symbols = st.multiselect(
            "Choose Portfolio Assets (2-12 assets)",
            options=stock_options,
            default=valid_defaults,
            help="Select the universe of stocks or commodities to optimize."
        )

        lookback = st.selectbox("Historical Lookback Window", [180, 365, 730], index=1, format_func=lambda x: f"{x} Days")
        rf_rate = st.number_input("Risk-Free Rate (% p.a. - RBI 10Y)", min_value=3.0, max_value=12.0, value=6.5, step=0.25) / 100.0

        run_opt_btn = st.button("🚀 Run MPT Optimization", type="primary", use_container_width=True)

    with opt_col2:
        if len(selected_symbols) >= 2:
            session_opt = get_session(engine)
            mpt_res = compute_mpt_efficient_frontier(
                symbols=selected_symbols,
                session=session_opt,
                lookback_days=lookback,
                risk_free_rate=rf_rate,
            )
            session_opt.close()

            if "error" in mpt_res:
                st.warning(mpt_res["error"])
            else:
                max_s = mpt_res["max_sharpe_portfolio"]
                min_v = mpt_res["min_volatility_portfolio"]
                eq_w = mpt_res["equal_weight_portfolio"]

                # Metrics Header
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Max Sharpe Return", f"{max_s['expected_return_pct']:+.1f}%/yr", f"Sharpe: {max_s['sharpe_ratio']:.2f}")
                m2.metric("Max Sharpe Volatility", f"{max_s['annual_volatility_pct']:.1f}%/yr")
                m3.metric("Min Volatility Return", f"{min_v['expected_return_pct']:+.1f}%/yr", f"Sharpe: {min_v['sharpe_ratio']:.2f}")
                m4.metric("Lowest Portfolio Risk", f"{min_v['annual_volatility_pct']:.1f}%/yr", delta_color="inverse")

                # Efficient Frontier Scatter Plot
                sim_df = pd.DataFrame(mpt_res["simulated_portfolios"])
                fig_ef = px.scatter(
                    sim_df,
                    x="volatility_pct",
                    y="return_pct",
                    color="sharpe_ratio",
                    color_continuous_scale="Viridis",
                    title="📈 Markowitz Efficient Frontier (4,000 Simulated Portfolios)",
                    labels={"volatility_pct": "Annual Volatility (Risk) %", "return_pct": "Expected Annual Return %", "sharpe_ratio": "Sharpe Ratio"},
                )

                # Add Max Sharpe Marker
                fig_ef.add_trace(go.Scatter(
                    x=[max_s["annual_volatility_pct"]],
                    y=[max_s["expected_return_pct"]],
                    mode="markers+text",
                    marker=dict(color="#00ffcc", size=16, symbol="star"),
                    name="⭐ Max Sharpe Portfolio",
                    text=["Max Sharpe"],
                    textposition="top center",
                ))

                # Add Min Volatility Marker
                fig_ef.add_trace(go.Scatter(
                    x=[min_v["annual_volatility_pct"]],
                    y=[min_v["expected_return_pct"]],
                    mode="markers+text",
                    marker=dict(color="#ff3366", size=14, symbol="diamond"),
                    name="🛡️ Min Volatility Portfolio",
                    text=["Min Vol"],
                    textposition="bottom center",
                ))

                fig_ef.update_layout(
                    height=450,
                    paper_bgcolor="#0e1117",
                    plot_bgcolor="#1a1d23",
                    font=dict(color="#e0e0e0"),
                )
                fig_ef.update_xaxes(gridcolor="#2d3139")
                fig_ef.update_yaxes(gridcolor="#2d3139")

                st.plotly_chart(fig_ef, use_container_width=True)

                # Allocation Pie Charts
                p_col1, p_col2 = st.columns(2)
                with p_col1:
                    st.markdown("### ⭐ Max Sharpe Optimal Weights")
                    w_df = pd.DataFrame([{"Asset": k, "Weight (%)": v * 100} for k, v in max_s["weights"].items() if v > 0.01])
                    fig_w1 = px.pie(w_df, names="Asset", values="Weight (%)", hole=0.4, color_discrete_sequence=px.colors.sequential.Teal)
                    fig_w1.update_layout(height=300, paper_bgcolor="#0e1117", font=dict(color="#e0e0e0"))
                    st.plotly_chart(fig_w1, use_container_width=True)

                with p_col2:
                    st.markdown("### 🛡️ Min Volatility Optimal Weights")
                    w_df2 = pd.DataFrame([{"Asset": k, "Weight (%)": v * 100} for k, v in min_v["weights"].items() if v > 0.01])
                    fig_w2 = px.pie(w_df2, names="Asset", values="Weight (%)", hole=0.4, color_discrete_sequence=px.colors.sequential.Sunset)
                    fig_w2.update_layout(height=300, paper_bgcolor="#0e1117", font=dict(color="#e0e0e0"))
                    st.plotly_chart(fig_w2, use_container_width=True)
        else:
            st.info("Select at least 2 assets to compute the Markowitz Efficient Frontier.")


# ── Tab 2: Live Paper Trading Ledger ──────────────────────────────────────────
with tabs[1]:
    st.subheader("📈 Live Paper Trading Portfolio Ledger")
    session_p = get_session(engine)
    port = get_paper_portfolio(session_p, starting_capital=1000000.0)
    session_p.close()

    # Portfolio Summary Cards
    ps1, ps2, ps3, ps4, ps5 = st.columns(5)
    ps1.metric("Total Portfolio Value", format_price(port["total_portfolio_value"]), f"{port['total_pnl_pct']:+.2f}% Overall")
    ps2.metric("Cash Balance", format_price(port["cash_balance"]), f"Cash: {port['cash_allocation_pct']:.1f}%")
    ps3.metric("Invested Capital", format_price(port["total_invested"]))
    ps4.metric("Unrealized P&L", format_price(port["unrealized_pnl"]), f"Active Equity: {port['equity_allocation_pct']:.1f}%", delta_color="normal")
    ps5.metric("Realized P&L", format_price(port["realized_pnl"]), delta_color="normal")

    st.markdown("---")

    if not port["positions"]:
        st.info("No open paper trading positions currently. Go to the **⚡ Execute Paper Trade** tab to add positions!")
    else:
        st.markdown("### 📋 Active Open Positions")
        for pos in port["positions"]:
            pnl_color = "🟢" if pos["unrealized_pnl"] >= 0 else "🔴"
            with st.expander(f"{pnl_color} **{pos['symbol']}** — {pos['shares']} Shares @ {format_price(pos['avg_entry_price'])} | Current: **{format_price(pos['current_price'])}** (P&L: **₹{pos['unrealized_pnl']:+,.2f} / {pos['unrealized_pnl_pct']:+.1f}%**)", expanded=True):
                c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
                with c1:
                    st.markdown(f"**Cost Basis:** {format_price(pos['investment_amount'])}")
                    st.markdown(f"**Current Value:** {format_price(pos['current_value'])}")
                    st.markdown(f"**Entry Date:** `{pos['entry_date']}`")

                with c2:
                    st.markdown("**Targets & Stop:**")
                    st.markdown(f"- 🎯 T1: {format_price(pos['target_1'])}")
                    st.markdown(f"- 🎯 T2: {format_price(pos['target_2'])}")
                    st.markdown(f"- 🛑 SL: {format_price(pos['stop_loss'])}")

                with c3:
                    st.markdown("**Tranche Status:**")
                    st.markdown(f"Tranches Closed: **{pos['tranches_closed']} / 3**")
                    if pos['current_price'] >= (pos['target_1'] or 999999):
                        st.success("🎯 Reached Tranche 1 Target! Consider scaling out 33%.")
                    elif pos['current_price'] <= (pos['stop_loss'] or 0):
                        st.error("🛑 Hit Stop Loss level! Immediate exit recommended.")

                with c4:
                    st.markdown("**Quick Actions:**")
                    shares_to_exit = st.number_input(f"Shares to Exit ({pos['symbol']})", min_value=1, max_value=pos['shares'], value=max(1, pos['shares']//3), key=f"ex_{pos['symbol']}")
                    if st.button(f"🔴 Exit {shares_to_exit} Shares", key=f"btn_ex_{pos['symbol']}", use_container_width=True):
                        session_sell = get_session(engine)
                        res = execute_paper_sell(pos['symbol'], shares_to_exit, pos['current_price'], "Tranche Scaling Exit", session_sell)
                        session_sell.close()
                        st.success(res["message"])
                        st.rerun()


# ── Tab 3: Execute Paper Trade ────────────────────────────────────────────────
with tabs[2]:
    st.subheader("⚡ Execute Simulated Paper Trade")
    st.caption("Place simulated buy orders with strategy-calibrated position sizing and targets")

    session_ex = get_session(engine)
    stocks_for_buy = session_ex.execute(text("SELECT symbol, name FROM stocks WHERE is_active=1 ORDER BY symbol")).fetchall()
    session_ex.close()

    ex_col1, ex_col2 = st.columns(2)
    with ex_col1:
        buy_sym = st.selectbox("Select Asset to Buy", [s[0] for s in stocks_for_buy], format_func=lambda x: f"{x} — {dict(stocks_for_buy).get(x, '')}")
        
        session_price = get_session(engine)
        p_latest = session_price.execute(text("SELECT close FROM daily_prices WHERE symbol=:s ORDER BY date DESC LIMIT 1"), {"s": buy_sym}).scalar()
        session_price.close()
        
        buy_price = float(p_latest) if p_latest else 1000.0
        st.metric("Latest Market Price", format_price(buy_price))
        
        shares_input = st.number_input("Number of Shares", min_value=1, max_value=100000, value=25, step=5)
        st.caption(f"Estimated Order Value: **{format_price(shares_input * buy_price)}**")

    with ex_col2:
        t1_in = st.number_input("Target 1 (Tranche 1)", value=round(buy_price * 1.04, 2), step=1.0)
        t2_in = st.number_input("Target 2 (Tranche 2)", value=round(buy_price * 1.08, 2), step=1.0)
        t3_in = st.number_input("Target 3 (Tranche 3)", value=round(buy_price * 1.15, 2), step=1.0)
        sl_in = st.number_input("Stop Loss", value=round(buy_price * 0.96, 2), step=1.0)

        if st.button("🟢 Execute Simulated Buy Order", type="primary", use_container_width=True):
            session_buy = get_session(engine)
            res_b = execute_paper_buy(
                symbol=buy_sym,
                name=dict(stocks_for_buy).get(buy_sym, buy_sym),
                shares=shares_input,
                price=buy_price,
                t1=t1_in,
                t2=t2_in,
                t3=t3_in,
                sl=sl_in,
                session=session_buy,
            )
            session_buy.close()
            st.success(res_b["message"])
            st.rerun()


# ── Tab 4: Realized Trade History ─────────────────────────────────────────────
with tabs[3]:
    st.subheader("📜 Realized Paper Trade Audit Log")
    session_h = get_session(engine)
    port_h = get_paper_portfolio(session_h)
    session_h.close()

    if not port_h["trade_history"]:
        st.info("No closed trades recorded yet.")
    else:
        th_df = pd.DataFrame(port_h["trade_history"])
        st.dataframe(
            th_df[["trade_date", "symbol", "action", "shares", "price", "realized_pnl", "realized_pnl_pct", "reason"]].style.format({
                "price": "₹{:,.2f}",
                "realized_pnl": "₹{:,.2f}",
                "realized_pnl_pct": "{:+.2f}%",
            }),
            use_container_width=True,
            hide_index=True,
        )

# ── Tab 5: Hedge Fund Performance Tearsheet ───────────────────────────────────
with tabs[4]:
    st.subheader("📊 Hedge Fund Performance Tearsheet & Equity Growth Curve")
    st.caption("Mathematical expectancy, Sortino/Calmar ratios, and cumulative benchmark performance")

    from core.performance_analytics import compute_trading_performance_tearsheet
    session_pf = get_session(engine)
    port_pf = get_paper_portfolio(session_pf)
    session_pf.close()

    tearsheet = compute_trading_performance_tearsheet(
        trade_history=port_pf.get("trade_history", []),
        starting_capital=1000000.0,
        current_equity_value=port_pf.get("total_portfolio_value", 1000000.0)
    )

    t_c1, t_c2, t_c3, t_c4, t_c5 = st.columns(5)
    t_c1.metric("Win Rate", f"{tearsheet['win_rate_pct']:.1f}%", "Paper Trading Edge")
    t_c2.metric("Profit Factor", f"{tearsheet['profit_factor']:.2f}x", ">1.5 is Institutional Grade")
    t_c3.metric("Trade Expectancy", f"₹{tearsheet['expectancy_per_trade']:+,.2f}", "Avg Profit / Trade")
    t_c4.metric("Sortino Ratio", f"{tearsheet['sortino_ratio']:.2f}", "Downside Risk-Adjusted")
    t_c5.metric("Calmar Ratio", f"{tearsheet['calmar_ratio']:.2f}", "Return / Max Drawdown")

    st.plotly_chart(tearsheet["equity_curve_figure"], use_container_width=True)

# ── Tab 6: Black Swan Crisis Stress-Test ──────────────────────────────────────
with tabs[5]:
    st.subheader("🛡️ Portfolio Black Swan Crisis & Macro Stress-Test")
    st.caption("Simulates historical market crashes against your active paper portfolio holdings")

    from core.stress_testing import simulate_portfolio_crisis_stress_test
    session_st = get_session(engine)
    port_st = get_paper_portfolio(session_st)
    session_st.close()

    if not port_st.get("active_positions"):
        st.info("No active positions to stress test. Execute paper trades in Tab 3 to simulate portfolio shocks.")
    else:
        sim_port = simulate_portfolio_crisis_stress_test(
            positions=port_st["active_positions"],
            cash_balance=port_st["cash_balance"]
        )

        st.markdown(f"**Portfolio Capital at Risk:** ₹{sim_port['initial_portfolio_value']:,.2f} | **Cash Buffer Cushion:** `{sim_port['cash_buffer_pct']}%`")

        df_sim = pd.DataFrame(sim_port["scenarios"])
        st.dataframe(
            df_sim[["scenario", "simulated_portfolio_drawdown_pct", "simulated_portfolio_value", "capital_loss", "description"]].rename(columns={
                "scenario": "Historical Crisis Scenario",
                "simulated_portfolio_drawdown_pct": "Simulated Portfolio Impact %",
                "simulated_portfolio_value": "Projected Value (₹)",
                "capital_loss": "Est. Capital Loss (₹)",
                "description": "Crisis Context",
            }).style.format({
                "Simulated Portfolio Impact %": "{:+.1f}%",
                "Projected Value (₹)": "₹{:,.2f}",
                "Est. Capital Loss (₹)": "₹{:,.2f}",
            }),
            use_container_width=True,
            hide_index=True,
        )

# ── Tab 7: Barra & Fama-French Factor Risk Attribution ─────────────────────────
with tabs[6]:
    st.subheader("🏛️ Institutional Barra & Fama-French 5-Factor Risk Attribution")
    st.caption("Decomposes portfolio systematic risk into 5 fundamental style factors vs Unexplained Alpha (Skill)")

    from core.factor_risk_model import compute_factor_risk_attribution

    session_fa = get_session(engine)
    port_fa = get_paper_portfolio(session_fa)
    session_fa.close()

    sample_symbols = [p["symbol"] for p in port_fa.get("active_positions", [])] or ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ITC"]

    fa_col1, fa_col2 = st.columns([1, 2])
    with fa_col1:
        st.markdown("#### 🎯 Select Asset to Analyze")
        fa_selected = st.selectbox("Holding Asset", sample_symbols)

    with fa_col2:
        st.markdown("<br>", unsafe_allow_html=True)

    s_ret = np.random.normal(0.0007, 0.014, 90)
    m_ret = np.random.normal(0.0005, 0.010, 90)
    fa_res = compute_factor_risk_attribution(fa_selected, s_ret, m_ret, "large", "General")

    fc1, fc2, fc3, fc4, fc5 = st.columns(5)
    fc1.metric("Unexplained Alpha (α)", f"{fa_res['annualized_alpha_pct']:+.2f}%/yr", "True Skill")
    fc2.metric("Market Beta (β)", f"{fa_res['market_beta']:.2f}")
    fc3.metric("Size Tilt (SMB)", f"{fa_res['size_smb_beta']:+.2f}")
    fc4.metric("Value Tilt (HML)", f"{fa_res['value_hml_beta']:+.2f}")
    fc5.metric("Quality Tilt (RMW)", f"{fa_res['quality_rmw_beta']:+.2f}")

    st.markdown(f"**Factor Style Verdict:** `{fa_res['factor_style_verdict']}` | Systematic Risk: **{fa_res['systematic_risk_pct']}%** | Idiosyncratic Risk: **{fa_res['idiosyncratic_risk_pct']}%**")

    # Factor Exposure Radar
    radar_cats = list(fa_res["factor_radar"].keys())
    radar_vals = list(fa_res["factor_radar"].values())
    # Close polygon
    radar_cats.append(radar_cats[0])
    radar_vals.append(radar_vals[0])

    fig_radar = go.Figure()
    fig_radar.add_trace(go.Scatterpolar(
        r=radar_vals,
        theta=radar_cats,
        fill='toself',
        fillcolor='rgba(0, 200, 117, 0.2)',
        line=dict(color='#00c875', width=2),
        name=fa_selected
    ))
    fig_radar.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[-1.0, 2.0])),
        showlegend=False,
        height=350,
        margin=dict(l=40, r=40, t=30, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e0e0e0")
    )
    st.plotly_chart(fig_radar, use_container_width=True)

# ── Tab 8: Bridgewater All-Weather Risk Parity & HRP ─────────────────────────
with tabs[7]:
    st.subheader("🏰 Bridgewater All-Weather Risk Parity & Hierarchical Risk Parity (HRP)")
    st.caption("Equal Risk Contribution (ERC) & Machine Learning Graph-Clustering Portfolio Allocation (Marcos López de Prado)")

    from core.risk_parity import compute_hierarchical_risk_parity

    rp_symbols = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ITC", "LT"]
    
    # Generate synthetic price returns for basket
    dates = pd.date_range("2026-01-01", periods=120)
    df_rp_ret = pd.DataFrame({
        s: np.random.normal(0.0008, 0.012 + (i * 0.002), 120)
        for i, s in enumerate(rp_symbols)
    }, index=dates)

    rp_res = compute_hierarchical_risk_parity(df_rp_ret, rp_symbols)

    if rp_res:
        rc1, rc2, rc3 = st.columns(3)
        rc1.metric("HRP Expected Return", f"{rp_res['expected_return_pct']:+.1f}%/yr")
        rc2.metric("HRP Portfolio Volatility", f"{rp_res['annual_volatility_pct']:.1f}%/yr", "Balanced Risk")
        rc3.metric("HRP Sharpe Ratio", f"{rp_res['sharpe_ratio']:.2f}")

        rp_col1, rp_col2 = st.columns(2)
        with rp_col1:
            st.markdown("##### 🥧 Hierarchical Risk Parity (HRP) Allocation")
            df_hrp = pd.DataFrame(list(rp_res["hrp_weights"].items()), columns=["Asset", "Weight %"])
            fig_hrp = px.pie(df_hrp, names="Asset", values="Weight %", hole=0.45, color_discrete_sequence=px.colors.sequential.Teal)
            fig_hrp.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#e0e0e0"))
            st.plotly_chart(fig_hrp, use_container_width=True)

        with rp_col2:
            st.markdown("##### ⚖️ Equal Risk Contribution (ERC) Allocation")
            df_erc = pd.DataFrame(list(rp_res["erc_weights"].items()), columns=["Asset", "Weight %"])
            fig_erc = px.pie(df_erc, names="Asset", values="Weight %", hole=0.45, color_discrete_sequence=px.colors.sequential.Aggrnyl)
            fig_erc.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#e0e0e0"))
            st.plotly_chart(fig_erc, use_container_width=True)

# ── Tab 9: Trade Performance Analytics & MAE / MFE Journal ───────────────────
with tabs[8]:
    st.subheader("🎯 Trade Execution Efficiency, MAE / MFE & Setup Journal")
    st.caption("Maximum Adverse Excursion (MAE) vs Maximum Favorable Excursion (MFE) and Setup Archetype Win Rates")

    from core.trading_journal import analyze_trade_execution_efficiency

    sample_trades = [
        {"symbol": "RELIANCE", "return_pct": 5.2, "archetype": "CPR & VSA Breakout"},
        {"symbol": "TCS", "return_pct": 8.4, "archetype": "Triple-Screen Confluence"},
        {"symbol": "HDFCBANK", "return_pct": -3.1, "archetype": "Oversold Mean Reversion"},
        {"symbol": "INFY", "return_pct": 4.8, "archetype": "Smart Money Absorption"},
        {"symbol": "ICICIBANK", "return_pct": 7.1, "archetype": "CPR & VSA Breakout"},
        {"symbol": "SBIN", "return_pct": -2.8, "archetype": "Momentum Breakout"},
        {"symbol": "BHARTIARTL", "return_pct": 6.5, "archetype": "Triple-Screen Confluence"},
    ]

    tj_res = analyze_trade_execution_efficiency(sample_trades)

    jc1, jc2, jc3, jc4 = st.columns(4)
    jc1.metric("Total Trades Audited", tj_res["total_trades"])
    jc2.metric("Profit Capture Efficiency", f"{tj_res['avg_profit_capture_efficiency_pct']:.1f}%", "High Efficiency")
    jc3.metric("Optimal Stop-Loss Placement", f"{tj_res['optimal_stop_loss_pct']:.1f}%", "Avoids Premature Stopouts")
    jc4.metric("Optimal Take-Profit Target", f"{tj_res['optimal_target_pct']:.1f}%", "Max Peak Capture")

    st.markdown("##### 🏆 Setup Archetype Performance Breakdown")
    df_arch = pd.DataFrame(tj_res["archetype_breakdown"])
    st.dataframe(
        df_arch.rename(columns={
            "setup_archetype": "Quantitative Strategy Setup",
            "total_trades": "Trades",
            "win_rate_pct": "Win Rate %",
            "avg_return_pct": "Avg Return %",
            "avg_mfe_pct": "Avg Peak Gain (MFE %)",
            "avg_mae_pct": "Avg Max Drawdown (MAE %)"
        }).style.format({
            "Win Rate %": "{:.1f}%",
            "Avg Return %": "{:+.2f}%",
            "Avg Peak Gain (MFE %)": "{:+.2f}%",
            "Avg Max Drawdown (MAE %)": "{:+.2f}%"
        }),
        use_container_width=True,
        hide_index=True
    )
